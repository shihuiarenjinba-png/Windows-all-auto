"""Validate, deduplicate and dispatch configured Store upload jobs."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Callable

from uploader.receipts import ReceiptJournal, ReceiptJournalError, new_execution_receipt, receipt_matches_job


class UploadError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


REQUIRED = ("product_name", "product_id", "submission_id", "repository", "ref", "path", "version", "destination")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class VerifiedJob:
    product_name: str
    product_id: str
    submission_id: str
    repository: str
    ref: str
    path: str
    version: str
    destination: str
    file_name: str
    size: int
    sha256: str
    identity_name: str = ""
    publisher: str = ""
    architecture: str = ""


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("schema_version") != 1:
        raise UploadError("CONFIG_SCHEMA_UNSUPPORTED", "Unsupported job config schema")
    missing = [key for key in REQUIRED if not isinstance(config.get(key), str) or not config[key].strip()]
    if missing:
        raise UploadError("INVALID_JOB", "Missing required fields: " + ", ".join(missing))
    if not SAFE_ID.fullmatch(config["product_id"]) or not SAFE_ID.fullmatch(config["submission_id"]):
        raise UploadError("INVALID_JOB", "Product ID or Submission ID has invalid characters")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", config["repository"]):
        raise UploadError("INVALID_JOB", "repository must be owner/name")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}", config["ref"])
            or ".." in config["ref"].split("/") or "?" in config["ref"] or "#" in config["ref"]):
        raise UploadError("INVALID_JOB", "ref must identify a safe branch, tag, or commit")
    if config["path"].startswith(("/", "\\")) or ".." in Path(config["path"]).parts or "\\" in config["path"]:
        raise UploadError("INVALID_JOB", "path must be a safe repository-relative path")
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", config["version"]):
        raise UploadError("INVALID_JOB", "version must be four numeric MSIX components")
    if config["destination"] != "microsoft_partner_center_existing_draft":
        raise UploadError("DESTINATION_MISMATCH", "Unsupported upload destination")
    if config.get("submission_route", "msix_pwa_app") not in {"msix_pwa_app", "msix_pwa_game"}:
        raise UploadError("ROUTE_UNSUPPORTED", "Only previously verified MSIX/PWA app or game Packages routes are enabled")
    if config.get("upload_approved") not in (True, False):
        raise UploadError("INVALID_JOB", "upload_approved must be a boolean")
    if not isinstance(config.get("max_bytes", 4_000_000_000), int) or config.get("max_bytes", 4_000_000_000) <= 0:
        raise UploadError("INVALID_JOB", "max_bytes must be a positive integer")
    for field in ("known_warnings", "expected_existing_package_names", "expected_replaced_package_names"):
        values = config.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise UploadError("INVALID_JOB", f"{field} must be a list of exact non-empty strings")
    return config


def read_msix_identity(path: Path) -> dict[str, str]:
    """Read the manifest identity from the exact MSIX bytes before a Store write."""
    try:
        with zipfile.ZipFile(path) as package:
            xml = package.read("AppxManifest.xml")
        root = ET.fromstring(xml)
        identity = next(node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "Identity")
        values = {key: identity.attrib.get(key, "") for key in ("Name", "Publisher", "Version", "ProcessorArchitecture")}
    except (OSError, KeyError, StopIteration, ET.ParseError, zipfile.BadZipFile) as exc:
        raise UploadError("INVALID_FILE_FORMAT", "MSIX manifest could not be read") from exc
    if not all(values.values()):
        raise UploadError("INVALID_FILE_FORMAT", "MSIX manifest Identity is incomplete")
    return values


def read_msix_manifest_metadata(path: Path) -> dict[str, Any]:
    """Read target device families and signature presence from exact MSIX bytes."""
    try:
        with zipfile.ZipFile(path) as package:
            root = ET.fromstring(package.read("AppxManifest.xml"))
            families = sorted({
                node.attrib.get("Name", "").strip()
                for node in root.iter()
                if node.tag.rsplit("}", 1)[-1] == "TargetDeviceFamily"
                and node.attrib.get("Name", "").strip()
            })
            signed = "AppxSignature.p7x" in package.namelist()
    except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
        raise UploadError("INVALID_FILE_FORMAT", "MSIX manifest metadata could not be read") from exc
    return {"target_device_families": families,
            "signature_state": "SIGNED_BLOCK_PRESENT" if signed else "UNSIGNED"}


def verify_file(config: dict[str, Any], path: Path, *, expected_sha256: str | None = None,
                max_bytes: int = 4_000_000_000) -> VerifiedJob:
    validate_config(config)
    if not path.is_file():
        raise UploadError("FILE_NOT_FOUND", "Downloaded package does not exist")
    if path.suffix.lower() != ".msix":
        raise UploadError("INVALID_FILE_FORMAT", "Only .msix packages are allowed")
    size = path.stat().st_size
    if size <= 0 or size > max_bytes:
        raise UploadError("FILE_SIZE_LIMIT", "Package size is empty or exceeds configured limit")
    hasher = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise UploadError("HASH_MISMATCH", "SHA-256 does not match registered artifact")
    manifest = read_msix_identity(path)
    expected_manifest = {
        "Name": config.get("identity_name"),
        "Publisher": config.get("publisher"),
        "Version": config["version"],
        "ProcessorArchitecture": config.get("architecture", "x64"),
    }
    if expected_sha256 and any(not value for value in expected_manifest.values()):
        raise UploadError("INVALID_JOB", "Live upload requires exact Identity, Publisher, Version and Architecture")
    mismatches = [key for key, expected in expected_manifest.items() if expected and manifest[key].casefold() != str(expected).casefold()]
    if mismatches:
        raise UploadError("PACKAGE_IDENTITY_MISMATCH", "MSIX manifest does not match configured " + ", ".join(mismatches))
    return VerifiedJob(
        config["product_name"], config["product_id"], config["submission_id"],
        config["repository"], config["ref"], config["path"], config["version"],
        config["destination"], path.name, size, digest,
        manifest["Name"], manifest["Publisher"], manifest["ProcessorArchitecture"],
    )


LEGACY_PREWRITE_FAILURE_CODES = frozenset({
    # These failures are raised before the package file input is selected.
    # Keep this allowlist deliberately narrow; ambiguous/post-write errors
    # remain charged conservatively and require reconciliation.
    "BROWSER_CONNECTION_FAILED",
    "PARTNER_CENTER_TAB_AMBIGUOUS",
    "HOLD_NO_MATCHING_PRODUCT_TAB",
    "BROWSER_RUNTIME_MISSING",
    "CDP_ENDPOINT_NOT_LOOPBACK",
    "BROWSER_NOT_EDGE",
})


class JobLedger:
    """SQLite idempotency ledger with separate historical and remote-write counts."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=15, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS uploads (
            job_key TEXT PRIMARY KEY, product_id TEXT NOT NULL, submission_id TEXT NOT NULL,
            package_file_name TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL,
            error_code TEXT NOT NULL DEFAULT '', receipt_json TEXT NOT NULL DEFAULT '')""")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(uploads)")}
        if "package_file_name" not in columns:
            # Old cache rows lack the filename binding; they cannot prove identity.
            self.db.execute("ALTER TABLE uploads ADD COLUMN package_file_name TEXT NOT NULL DEFAULT ''")

        # Additive migration: keep the original uploads rows and their attempts
        # untouched. This companion table separates true remote-write reservations
        # from legacy preflight-only failures which older versions counted.
        self.db.execute("""CREATE TABLE IF NOT EXISTS upload_write_attempts (
            job_key TEXT PRIMARY KEY,
            remote_write_attempts INTEGER NOT NULL,
            classification TEXT NOT NULL,
            legacy_status TEXT NOT NULL DEFAULT '',
            legacy_error_code TEXT NOT NULL DEFAULT '')""")
        placeholders = ",".join("?" for _ in LEGACY_PREWRITE_FAILURE_CODES)
        codes = tuple(sorted(LEGACY_PREWRITE_FAILURE_CODES))
        self.db.execute(
            f"""INSERT OR IGNORE INTO upload_write_attempts
                (job_key, remote_write_attempts, classification, legacy_status, legacy_error_code)
                SELECT job_key,
                    CASE
                        WHEN status = 'DRY_RUN' THEN 0
                        WHEN status = 'FAILED' AND error_code IN ({placeholders}) THEN 0
                        ELSE attempts
                    END,
                    CASE
                        WHEN status = 'DRY_RUN' THEN 'LEGACY_DRY_RUN'
                        WHEN status = 'FAILED' AND error_code IN ({placeholders}) THEN 'LEGACY_PREUPLOAD_FAILURE'
                        ELSE 'LEGACY_CONSERVATIVE'
                    END,
                    status, error_code
                FROM uploads""",
            codes * 2,
        )

    def close(self):
        self.db.close()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    @staticmethod
    def key(job: VerifiedJob) -> str:
        return sha256(f"{job.product_id}:{job.submission_id}:{job.file_name}:{job.sha256}".encode()).hexdigest()

    def state_for(self, job: VerifiedJob) -> tuple[str, int] | None:
        """Read current local attempt state without reserving or incrementing it."""
        row = self.db.execute("SELECT status,attempts FROM uploads WHERE job_key=?", (self.key(job),)).fetchone()
        if row:
            return str(row[0]), int(row[1])
        legacy = self.db.execute(
            "SELECT status,attempts FROM uploads WHERE product_id=? AND submission_id=? AND sha256=? AND package_file_name='' ORDER BY attempts DESC LIMIT 1",
            (job.product_id, job.submission_id, job.sha256),
        ).fetchone()
        return (str(legacy[0]), int(legacy[1])) if legacy else None

    def begin(self, job: VerifiedJob, *, dry_run: bool = False) -> tuple[str, int]:
        key = self.key(job)
        row = self.db.execute("SELECT status,attempts FROM uploads WHERE job_key=?", (key,)).fetchone()
        if row:
            status, attempts = str(row[0]), int(row[1])
            if status == "SUCCEEDED": return "DUPLICATE", attempts
            if status == "DRY_RUN" and dry_run: return "DRY_RUN_ALREADY_DONE", attempts
            if status in {"UPLOADING", "UNKNOWN"}: return "RECONCILE_REQUIRED", attempts
            if dry_run:
                # A dry-run against an existing failed row must not reserve a
                # remote attempt or rewrite the historical upload state.
                return "DRY_RUN", attempts
            accounting = self.db.execute(
                "SELECT remote_write_attempts FROM upload_write_attempts WHERE job_key=?", (key,)
            ).fetchone()
            # Rows created before the companion table appeared are conservatively
            # charged their full historical count; do not silently zero them.
            remote_attempts = int(accounting[0]) if accounting else attempts
            if remote_attempts >= 3:
                return "RETRY_LIMIT", attempts
            if status == "DRY_RUN":
                # Dry-run does not consume the historical count or write budget.
                attempts = max(1, attempts)
                self.db.execute("UPDATE uploads SET status='UPLOADING',attempts=?,error_code='' WHERE job_key=?",
                                (attempts, key))
            else:
                attempts += 1
                self.db.execute("UPDATE uploads SET status='UPLOADING',attempts=?,error_code='' WHERE job_key=?",
                                (attempts, key))
            self.db.execute(
                "UPDATE upload_write_attempts SET remote_write_attempts=? WHERE job_key=?",
                (remote_attempts + 1, key),
            )
            return "READY", attempts

        legacy = self.db.execute("SELECT status,attempts FROM uploads WHERE product_id=? AND submission_id=? AND sha256=? AND package_file_name='' ORDER BY attempts DESC LIMIT 1",
                                 (job.product_id, job.submission_id, job.sha256)).fetchone()
        if legacy and legacy[0] in {"SUCCEEDED", "UPLOADING", "UNKNOWN"}:
            return "RECONCILE_REQUIRED", int(legacy[1])
        initial_remote_attempts = 0 if dry_run else 1
        self.db.execute("INSERT INTO uploads(job_key,product_id,submission_id,package_file_name,sha256,status,attempts) VALUES(?,?,?,?,?,?,1)",
                         (key, job.product_id, job.submission_id, job.file_name, job.sha256, "UPLOADING"))
        self.db.execute(
            """INSERT INTO upload_write_attempts
               (job_key, remote_write_attempts, classification, legacy_status, legacy_error_code)
               VALUES(?, ?, 'NEW_JOB', '', '')""",
            (key, initial_remote_attempts),
        )
        return "READY", 1

    def finish(self, job: VerifiedJob, status: str, *, error_code: str = "", receipt: dict[str, Any] | None = None):
        if status not in {"SUCCEEDED", "FAILED", "UNKNOWN", "DRY_RUN"}:
            raise ValueError("illegal terminal status")
        details = dict(receipt or {})
        confirmation = details.get("partner_center_confirmation")
        if confirmation is None:
            if status == "SUCCEEDED" and details.get("partner_center_confirmed") is True:
                confirmation = "UI_VALIDATED_SHA_UNOBSERVABLE"
            elif status == "UNKNOWN":
                confirmation = "UNKNOWN"
            elif status == "DRY_RUN":
                confirmation = "NOT_ATTEMPTED"
            else:
                confirmation = "NOT_CONFIRMED"
        normalized = new_execution_receipt(
            product_id=job.product_id, submission_id=job.submission_id,
            package_file_name=job.file_name, sha256=job.sha256, result=status,
            partner_center_confirmation=confirmation, details=details,
        )
        normalized.update({key: value for key, value in details.items() if key not in normalized})
        self.db.execute("UPDATE uploads SET status=?,error_code=?,receipt_json=? WHERE job_key=?",
                        (status, error_code, json.dumps(normalized, sort_keys=True), self.key(job)))

    def get_receipt(self, job: VerifiedJob) -> dict[str, Any] | None:
        row = self.db.execute("SELECT receipt_json FROM uploads WHERE job_key=?", (self.key(job),)).fetchone()
        if not row or not row[0]:
            return None
        try:
            value = json.loads(row[0])
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def mark_reconciled_not_written(self, job: VerifiedJob) -> None:
        self.db.execute("UPDATE uploads SET status='FAILED',error_code='RECONCILED_NOT_WRITTEN' WHERE job_key=?",
                        (self.key(job),))


def process_job(config: dict[str, Any], package_path: Path, ledger: JobLedger, *,
                expected_sha256: str | None = None, dry_run: bool = True,
                live_adapter: Callable[[VerifiedJob, Path], dict[str, Any]] | None = None,
                live_preflight_adapter: Callable[[VerifiedJob, Path], dict[str, Any]] | None = None,
                reconcile_adapter: Callable[[VerifiedJob, Path, dict[str, Any] | None], dict[str, Any]] | None = None,
                receipt_journal: ReceiptJournal | None = None) -> dict[str, Any]:
    job = verify_file(config, package_path, expected_sha256=expected_sha256,
                      max_bytes=int(config.get("max_bytes", 4_000_000_000)))
    prior_state = "NO_MATCH"
    prior_success_receipt = None
    if receipt_journal is not None and not dry_run:
        try:
            prior_state = receipt_journal.classify(job)
            if prior_state == "EXACT_SUCCESS":
                prior_success_receipt = next((receipt for receipt in receipt_journal.records()
                                              if receipt_matches_job(receipt, job)), None)
        except ReceiptJournalError as exc:
            raise UploadError("DURABLE_LEDGER_INVALID", "Durable receipt ledger is unreadable; refusing a Store write") from exc
        if prior_state == "IDENTITY_CONFLICT":
            return {"status": "RECONCILE_REQUIRED", "attempts": 0, "product_id": job.product_id,
                    "submission_id": job.submission_id, "package_file_name": job.file_name, "sha256": job.sha256,
                    "reason": "A prior successful receipt has the same filename or hash with a different tuple"}
    if not dry_run and prior_state == "NO_MATCH":
        local_state = ledger.state_for(job)
        if local_state and local_state[0] == "SUCCEEDED":
            local_receipt = ledger.get_receipt(job)
            if receipt_matches_job(local_receipt, job):
                prior_state = "EXACT_SUCCESS"
                prior_success_receipt = local_receipt
            else:
                return {"status": "RECONCILE_REQUIRED", "attempts": local_state[1],
                        "product_id": job.product_id, "submission_id": job.submission_id,
                        "package_file_name": job.file_name, "sha256": job.sha256,
                        "reason": "LOCAL_LEDGER_SUCCESS_MISSING_EXACT_SHA_BOUND_RECEIPT"}
    if dry_run:
        status, attempts = ledger.begin(job, dry_run=True)
        if status == "DRY_RUN_ALREADY_DONE":
            return {"status": status, "attempts": attempts, "product_id": job.product_id,
                    "submission_id": job.submission_id, "package_file_name": job.file_name, "sha256": job.sha256}
        if status != "READY":
            return {"status": status, "attempts": attempts, "product_id": job.product_id,
                    "submission_id": job.submission_id, "package_file_name": job.file_name, "sha256": job.sha256}
        ledger.finish(job, "DRY_RUN", receipt={"verified": True, "remote_write": False})
        return {"status": "DRY_RUN", "attempts": attempts, "product_id": job.product_id,
                "submission_id": job.submission_id, "package_file_name": job.file_name, "sha256": job.sha256}

    # Check all static live gates and attach/resolve the exact existing Draft
    # before reserving an upload attempt. Local CDP/tab failures therefore do
    # not consume the remote-write retry budget.
    duplicate_reconcile_only = prior_state == "EXACT_SUCCESS"
    if not duplicate_reconcile_only and config.get("upload_approved") is not True:
        raise UploadError("UPLOAD_NOT_APPROVED", "This product job is not approved for a live package write")
    if not expected_sha256 or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise UploadError("EXPECTED_SHA_REQUIRED", "Live upload requires a frozen 64-character SHA-256")
    if (live_adapter is None and live_preflight_adapter is None and
            not (duplicate_reconcile_only and reconcile_adapter is not None)):
        raise UploadError("BROWSER_ADAPTER_UNSUPPORTED", "Existing MSIX Draft browser adapter is not enabled")
    if not duplicate_reconcile_only:
        from uploader.live_gates import package_write_hold_reason
        live_hold = package_write_hold_reason(config, package_path)
        if live_hold:
            raise UploadError(live_hold, "Shared Store live-write QA/approval gate did not pass")
    if live_preflight_adapter is not None:
        prior_local_state = ledger.state_for(job)
        recovery_required = bool(prior_local_state and prior_local_state[0] in {"UPLOADING", "UNKNOWN"})
        recovery_required = recovery_required or duplicate_reconcile_only
        prepared = live_preflight_adapter(job, package_path, recovery_required=recovery_required)
        if (not isinstance(prepared, dict) or
                (not duplicate_reconcile_only and not callable(prepared.get("live_adapter"))) or
                (duplicate_reconcile_only and not callable(prepared.get("reconcile_adapter")))):
            raise UploadError("BROWSER_PREFLIGHT_INVALID", "Live browser preflight did not return a verified upload adapter")
        if callable(prepared.get("live_adapter")):
            live_adapter = prepared["live_adapter"]
        if callable(prepared.get("reconcile_adapter")):
            reconcile_adapter = prepared["reconcile_adapter"]
    if duplicate_reconcile_only:
        if not callable(reconcile_adapter) or prior_success_receipt is None:
            return {"status": "RECONCILE_REQUIRED", "attempts": 0,
                    "product_id": job.product_id, "submission_id": job.submission_id,
                    "package_file_name": job.file_name, "sha256": job.sha256,
                    "reason": "EXACT_SUCCESS_RECEIPT_REQUIRES_CURRENT_PARTNER_CENTER_RECONCILIATION"}
        try:
            current = reconcile_adapter(job, package_path, prior_success_receipt)
        except Exception as exc:
            return {"status": "RECONCILE_REQUIRED", "attempts": 0,
                    "product_id": job.product_id, "submission_id": job.submission_id,
                    "package_file_name": job.file_name, "sha256": job.sha256,
                    "reason": "CURRENT_PARTNER_CENTER_RECONCILIATION_FAILED",
                    "error_type": type(exc).__name__}
        current_matches = (
            isinstance(current, dict)
            and current.get("partner_center_confirmed") is True
            and current.get("current_partner_center_reconciled") is True
            and current.get("product_id") == job.product_id
            and current.get("submission_id") == job.submission_id
            and current.get("package_file_name") == job.file_name
            and str(current.get("local_package_sha256", "")).lower() == job.sha256.lower()
            and current.get("partner_center_sha256") is None
            and current.get("prior_receipt_sha256_match") is True
            and current.get("partner_center_confirmation") == "UI_VALIDATED_SHA_UNOBSERVABLE"
            and current.get("partner_center_validation") == "Validated"
        )
        if not current_matches:
            return {"status": "RECONCILE_REQUIRED", "attempts": 0,
                    "product_id": job.product_id, "submission_id": job.submission_id,
                    "package_file_name": job.file_name, "sha256": job.sha256,
                    "reason": "DURABLE_SUCCESS_RECEIPT_NOT_CONFIRMED_BY_CURRENT_PARTNER_CENTER_STATE",
                    "current_observation": current if isinstance(current, dict) else {"status": "INVALID"}}
        return {"status": "DUPLICATE_CONFIRMED", "attempts": 0,
                "product_id": job.product_id, "submission_id": job.submission_id,
                "package_file_name": job.file_name, "sha256": job.sha256,
                "partner_center_confirmed": True, "partner_center_reconfirmed": True,
                "current_partner_center_reconciled": True,
                "partner_center_sha256": None,
                "partner_center_confirmation": "UI_VALIDATED_SHA_UNOBSERVABLE",
                "partner_center_validation": "Validated",
                "writes_performed": False, "current_observation": current}
    status, attempts = ledger.begin(job, dry_run=dry_run)
    if status == "RECONCILE_REQUIRED" and not dry_run and reconcile_adapter is not None:
        previous_receipt = ledger.get_receipt(job)
        if not receipt_matches_job(previous_receipt, job) and receipt_journal is not None:
            previous_receipt = next((receipt for receipt in receipt_journal.records()
                                     if receipt_matches_job(receipt, job)), None)
        try:
            reconciliation = reconcile_adapter(job, package_path, previous_receipt)
        except Exception as exc:
            ledger.finish(job, "UNKNOWN", error_code="RECONCILE_UNRESOLVED",
                          receipt={"error_type": type(exc).__name__})
            return {"status": "RECONCILE_REQUIRED", "attempts": attempts, "product_id": job.product_id,
                    "submission_id": job.submission_id, "sha256": job.sha256}
        if reconciliation.get("partner_center_confirmed") is True and receipt_matches_job(previous_receipt, job):
            ledger.finish(job, "SUCCEEDED", receipt=reconciliation)
            return {"status": "SUCCEEDED_RECONCILED", "attempts": attempts, "product_id": job.product_id,
                    "submission_id": job.submission_id, "package_file_name": job.file_name, "sha256": job.sha256}
        if reconciliation.get("safe_to_retry") is True:
            ledger.mark_reconciled_not_written(job)
            status, attempts = ledger.begin(job, dry_run=False)
        else:
            ledger.finish(job, "UNKNOWN", error_code="RECONCILE_UNRESOLVED", receipt=reconciliation)
            return {"status": "RECONCILE_REQUIRED", "attempts": attempts, "product_id": job.product_id,
                    "submission_id": job.submission_id, "package_file_name": job.file_name, "sha256": job.sha256}
    if status != "READY":
        return {"status": status, "attempts": attempts, "product_id": job.product_id,
                "submission_id": job.submission_id, "package_file_name": job.file_name, "sha256": job.sha256}
    if live_adapter is None:
        ledger.finish(job, "FAILED", error_code="BROWSER_ADAPTER_UNSUPPORTED")
        raise UploadError("BROWSER_ADAPTER_UNSUPPORTED", "Existing MSIX Draft browser adapter is not enabled")
    try:
        receipt = live_adapter(job, package_path)
        if receipt.get("partner_center_confirmed") is not True:
            ledger.finish(job, "UNKNOWN", error_code="UPLOAD_RESULT_UNCONFIRMED", receipt=receipt)
            raise UploadError("UPLOAD_RESULT_UNCONFIRMED", "Partner Center did not confirm completion")
        ledger.finish(job, "SUCCEEDED", receipt=receipt)
        if receipt_journal is not None:
            durable_receipt = ledger.get_receipt(job)
            if durable_receipt is not None:
                receipt_journal.append(durable_receipt)
        return {"status": "SUCCEEDED", "attempts": attempts, "product_id": job.product_id,
                "submission_id": job.submission_id, "package_file_name": job.file_name, "sha256": job.sha256}
    except UploadError as exc:
        ambiguous = {"UPLOAD_RESULT_UNKNOWN", "UPLOAD_RESULT_UNCONFIRMED", "RECONCILE_REQUIRED",
                     "UNKNOWN_WARNING", "PARTNER_CENTER_VALIDATION_FAILED", "PACKAGE_METADATA_MISMATCH",
                     "DEVICE_FAMILY_MISMATCH", "OLD_PACKAGE_RETAINED", "AUTH_FAILED",
                     "PARTNER_CENTER_UI_CHANGED", "SUBMISSION_MISMATCH", "PRODUCT_MISMATCH"}
        ledger.finish(job, "UNKNOWN" if exc.code in ambiguous else "FAILED", error_code=exc.code)
        raise
    except Exception as exc:
        ledger.finish(job, "UNKNOWN", error_code="UPLOAD_RESULT_UNKNOWN", receipt={"error_type": type(exc).__name__})
        raise UploadError("UPLOAD_RESULT_UNKNOWN", "Remote write outcome requires reconciliation") from exc
