"""Validate, deduplicate and dispatch configured Store upload jobs.

The current API adapter intentionally refuses live MSIX writes until the
specific existing-draft API contract is verified. It never submits for
certification or publishes.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable


class UploadError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


REQUIRED = ("product_name", "product_id", "submission_id", "repository", "ref", "path", "version", "destination")
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


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


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("schema_version") != 1:
        raise UploadError("API_SCHEMA_CHANGED", "Unsupported job config schema")
    missing = [key for key in REQUIRED if not isinstance(config.get(key), str) or not config[key].strip()]
    if missing:
        raise UploadError("INVALID_JOB", "Missing required fields: " + ", ".join(missing))
    if not SAFE_ID.fullmatch(config["product_id"]) or not SAFE_ID.fullmatch(config["submission_id"]):
        raise UploadError("INVALID_JOB", "Product ID or Submission ID has invalid characters")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", config["repository"]):
        raise UploadError("INVALID_JOB", "repository must be owner/name")
    if config["destination"] != "microsoft_partner_center_existing_draft":
        raise UploadError("DESTINATION_MISMATCH", "Unsupported upload destination")
    return config


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
    digest = sha256(path.read_bytes()).hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise UploadError("HASH_MISMATCH", "SHA-256 does not match registered artifact")
    return VerifiedJob(
        config["product_name"], config["product_id"], config["submission_id"],
        config["repository"], config["ref"], config["path"], config["version"],
        config["destination"], path.name, size, digest,
    )


class JobLedger:
    """SQLite idempotency ledger; attempted remote writes become UNKNOWN."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=15, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS uploads (
            job_key TEXT PRIMARY KEY, product_id TEXT NOT NULL, submission_id TEXT NOT NULL,
            sha256 TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL,
            error_code TEXT NOT NULL DEFAULT '', receipt_json TEXT NOT NULL DEFAULT '')""")

    def close(self):
        self.db.close()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    @staticmethod
    def key(job: VerifiedJob) -> str:
        return sha256(f"{job.product_id}:{job.submission_id}:{job.sha256}".encode()).hexdigest()

    def begin(self, job: VerifiedJob) -> tuple[str, int]:
        key = self.key(job)
        row = self.db.execute("SELECT status,attempts FROM uploads WHERE job_key=?", (key,)).fetchone()
        if row:
            if row[0] == "SUCCEEDED": return "DUPLICATE", row[1]
            if row[0] == "DRY_RUN": return "DRY_RUN_ALREADY_DONE", row[1]
            if row[0] in {"UPLOADING", "UNKNOWN"}: return "RECONCILE_REQUIRED", row[1]
            attempts = int(row[1])
            if attempts >= 3: return "RETRY_LIMIT", attempts
            self.db.execute("UPDATE uploads SET status='UPLOADING',attempts=?,error_code='' WHERE job_key=?", (attempts + 1, key))
            return "READY", attempts + 1
        self.db.execute("INSERT INTO uploads(job_key,product_id,submission_id,sha256,status,attempts) VALUES(?,?,?,?,?,1)",
                         (key, job.product_id, job.submission_id, job.sha256, "UPLOADING"))
        return "READY", 1

    def finish(self, job: VerifiedJob, status: str, *, error_code: str = "", receipt: dict[str, Any] | None = None):
        if status not in {"SUCCEEDED", "FAILED", "UNKNOWN", "DRY_RUN"}:
            raise ValueError("illegal terminal status")
        self.db.execute("UPDATE uploads SET status=?,error_code=?,receipt_json=? WHERE job_key=?",
                        (status, error_code, json.dumps(receipt or {}, sort_keys=True), self.key(job)))


def process_job(config: dict[str, Any], package_path: Path, ledger: JobLedger, *,
                expected_sha256: str | None = None, dry_run: bool = True,
                live_adapter: Callable[[VerifiedJob, Path], dict[str, Any]] | None = None) -> dict[str, Any]:
    job = verify_file(config, package_path, expected_sha256=expected_sha256)
    status, attempts = ledger.begin(job)
    if status != "READY":
        return {"status": status, "attempts": attempts, "product_id": job.product_id,
                "submission_id": job.submission_id, "sha256": job.sha256}
    if dry_run:
        ledger.finish(job, "DRY_RUN", receipt={"verified": True, "remote_write": False})
        return {"status": "DRY_RUN", "attempts": attempts, "product_id": job.product_id,
                "submission_id": job.submission_id, "sha256": job.sha256}
    if live_adapter is None:
        ledger.finish(job, "FAILED", error_code="API_UNSUPPORTED")
        raise UploadError("API_UNSUPPORTED", "Existing MSIX draft upload adapter is not enabled")
    try:
        receipt = live_adapter(job, package_path)
        if receipt.get("partner_center_confirmed") is not True:
            ledger.finish(job, "UNKNOWN", error_code="UPLOAD_RESULT_UNCONFIRMED", receipt=receipt)
            raise UploadError("UPLOAD_RESULT_UNCONFIRMED", "Partner Center did not confirm completion")
        ledger.finish(job, "SUCCEEDED", receipt=receipt)
        return {"status": "SUCCEEDED", "attempts": attempts, "product_id": job.product_id,
                "submission_id": job.submission_id, "sha256": job.sha256}
    except UploadError:
        raise
    except Exception as exc:
        ledger.finish(job, "UNKNOWN", error_code="UPLOAD_RESULT_UNKNOWN", receipt={"error_type": type(exc).__name__})
        raise UploadError("UPLOAD_RESULT_UNKNOWN", "Remote write outcome requires reconciliation") from exc
