"""Local-only, fail-closed multi-product Identity scheduler.

This is an ORCHESTRATOR, not a second CAS implementation. Only the reviewed
Signal Sprint worker may perform CAS, after explicit request-specific approval.
Store reference discovery is NOT Partner Center authentication.
No raw authenticated evidence, tokens, cookies or URLs enter a receipt.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote

from scripts import registration_router

OWNER = "shihuiarenjinba-png"
CENTRAL_REPO = OWNER + "/Windows-all-auto"
CENTRAL_BRANCH = "codex/e2e-belt-connection-20261027"
CENTRAL_PATH = "ops/active_e2e_handoff.json"
REFERENCE_PATH = "store/unsigned_msix_submission_inputs.json"
IDENTITY_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "ops" / "user_provided_store_identities.json"
STORE_REFS = {
    "-AI-Upload-Guard-AI-": "codex/store-p1-ai-upload-guard-20261023",
    "-Excel-CSV-Privacy-Cleaner": "codex/store-p1-excel-csv-privacy-20261023",
    "-Screenshot-Image-Privacy-Cleaner": "codex/store-p1-image-privacy-20261023",
}
SHA = re.compile(r"^[0-9a-f]{40}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
REQUEST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,159}$")
BRANCH = re.compile(r"^codex/[A-Za-z0-9._/-]+$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$")
IDENTITY_FIELDS = {
    "store_id": "owner_confirmed_store_id",
    "reserved_display_name": "partner_center_reserved_display_name",
    "identity_name": "package_identity_name",
    "publisher": "package_identity_publisher",
    "publisher_display_name": "publisher_display_name",
    "package_family_name": "package_family_name",
    "package_sid": "package_sid",
}
STAGES = {
    "DISCOVER_JOB", "VERIFY_REPOSITORY", "VERIFY_BRANCH_HEAD",
    "VERIFY_LOCAL_PACKAGE", "WAITING_PARTNER_CENTER_AUTH",
    "WAITING_USER_IDENTITY", "USER_IDENTITY_RECEIVED", "IDENTITY_VALIDATED",
    "LOOKUP_OFFICIAL_IDENTITY", "VERIFY_IDENTITY", "IDENTITY_READY",
    "WAITING_CAS_APPROVAL", "CAS_RETURN", "CAS_RETURNED",
    "WAITING_FACTORY_MSIX", "MSIX_READY", "WAITING_GITHUB_INTAKE",
    "GITHUB_BACKLOG", "LOCAL_QA_PENDING", "CHECKER_PENDING",
    "GUI_QA_PENDING", "DONE", "HOLD", "CONFLICT",
}
# These are the ONLY keys accepted in local operator evidence. In particular,
# do not accept URLs, screenshots, raw HTML, authentication material or secrets.
EVIDENCE_KEYS = set(IDENTITY_FIELDS) | {"observation", "request_id", "source_sha"}


class Hold(Exception):
    def __init__(self, stage: str, reason: str):
        super().__init__(reason)
        self.stage, self.reason = stage, reason


def unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Hold("CONFLICT", "DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def decode_json(raw: str, max_bytes: int = 200_000) -> dict:
    if len(raw.encode("utf-8")) > max_bytes:
        raise Hold("HOLD", "JSON_TOO_LARGE")
    try:
        data = json.loads(raw, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError) as exc:
        raise Hold("HOLD", "INVALID_JSON") from exc
    if not isinstance(data, dict):
        raise Hold("HOLD", "JSON_ROOT_NOT_OBJECT")
    return data


def gh(endpoint: str) -> dict:
    try:
        result = subprocess.run(["gh", "api", "-X", "GET", endpoint],
                                capture_output=True, text=True, encoding="utf-8",
                                timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("HOLD", "GITHUB_READ_UNAVAILABLE") from exc
    if result.returncode:
        raise Hold("HOLD", "GITHUB_READ_UNAVAILABLE")
    return decode_json(result.stdout)


def head(repo: str, branch: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo) or not BRANCH.fullmatch(branch):
        raise Hold("CONFLICT", "UNSAFE_REPOSITORY_OR_BRANCH")
    response = gh("repos/" + repo + "/git/ref/heads/" + quote(branch, safe=""))
    sha = (response.get("object") or {}).get("sha")
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise Hold("HOLD", "BRANCH_HEAD_UNVERIFIED")
    return sha


def remote_json(repo: str, path: str, sha: str) -> tuple[dict, str]:
    if not SHA.fullmatch(sha):
        raise Hold("CONFLICT", "REMOTE_SHA_INVALID")
    data = gh("repos/" + repo + "/contents/" + path + "?ref=" + sha)
    if data.get("encoding") != "base64" or not isinstance(data.get("content"), str):
        raise Hold("HOLD", "REFERENCE_ENCODING_INVALID")
    try:
        raw = base64.b64decode("".join(data["content"].split()), validate=True).decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise Hold("HOLD", "REFERENCE_DECODE_INVALID") from exc
    blob = data.get("sha")
    if not isinstance(blob, str) or not SHA.fullmatch(blob):
        raise Hold("HOLD", "REFERENCE_BLOB_UNVERIFIED")
    return decode_json(raw), blob


def safe_local(path: Path) -> Path:
    path = path.expanduser().absolute()
    # Reject symlinked ancestors too: a private-looking path may redirect
    # into a Git checkout through a parent junction/symlink.
    original_ancestors = (path, *path.parents)
    # Windows junctions are reparse points but not always symlinks.
    # Reject them before resolving private evidence and state paths.
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
           for p in original_ancestors):
        raise Hold("HOLD", "PRIVATE_PATH_INSIDE_GIT_OR_SYMLINK")
    resolved = path.resolve(strict=False)
    if any((p / ".git").exists() for p in (resolved, *resolved.parents)):
        raise Hold("HOLD", "PRIVATE_PATH_INSIDE_GIT_OR_SYMLINK")
    return resolved


def atomic_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".identity-", suffix=".tmp", delete=False) as fp:
        json.dump(data, fp, indent=2, ensure_ascii=False, sort_keys=True)
        fp.write("\n")
        temporary = Path(fp.name)
    try:
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class ExclusiveLock:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise Hold("HOLD", "SCHEDULER_ALREADY_RUNNING_LOCK_REQUIRES_OPERATOR_REVIEW") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("pid=" + str(os.getpid()) + "\n")
        return self

    def __exit__(self, *_):
        self.path.unlink(missing_ok=True)


def validate_jobs(config: dict) -> list[dict]:
    jobs = config.get("jobs")
    if not isinstance(jobs, list) or not jobs or len(jobs) > 100:
        raise Hold("HOLD", "JOBS_REQUIRED")
    seen = set()
    for job in jobs:
        if not isinstance(job, dict):
            raise Hold("CONFLICT", "JOB_NOT_OBJECT")
        rid, sha, repo, branch = (job.get(k) for k in
                                  ("request_id", "source_sha", "repository", "branch"))
        if (not isinstance(rid, str) or not REQUEST.fullmatch(rid)
                or not isinstance(sha, str) or not SHA.fullmatch(sha)
                or not isinstance(repo, str) or not repo.startswith(OWNER + "/")
                or not isinstance(branch, str) or not BRANCH.fullmatch(branch)):
            raise Hold("CONFLICT", "INVALID_JOB_BINDING")
        if rid in seen:
            raise Hold("CONFLICT", "DUPLICATE_REQUEST_ID")
        seen.add(rid)
        if job.get("kind") not in {"STORE_KNOWN_GOOD", "GAME_SIGNAL_SPRINT", "APP_CANARY", "GAME_3D_CANARY"}:
            raise Hold("CONFLICT", "UNKNOWN_JOB_KIND")
        if job["kind"] == "STORE_KNOWN_GOOD":
            if repo.split("/", 1)[1] not in STORE_REFS or branch != STORE_REFS[repo.split("/", 1)[1]]:
                raise Hold("CONFLICT", "STORE_REFERENCE_BRANCH_MISMATCH")
        if job["kind"] == "GAME_SIGNAL_SPRINT" and repo != OWNER + "/AI-Game-Factory":
            raise Hold("CONFLICT", "GAME_FACTORY_MISMATCH")
        if job["kind"] == "APP_CANARY" and repo != OWNER + "/AI-App-Factory":
            raise Hold("CONFLICT", "APP_FACTORY_MISMATCH")
        if job["kind"] == "GAME_3D_CANARY" and repo != OWNER + "/3d-game-factory":
            raise Hold("CONFLICT", "THREE_D_FACTORY_MISMATCH")
        try:
            registration_router.validate_handoff_job(job)
        except registration_router.RegistrationHold as exc:
            raise Hold("CONFLICT", str(exc)) from exc
    return jobs


def inspect_package(job: dict) -> str:
    filename, expected = job.get("package_path"), job.get("package_sha256")
    if not filename or not expected:
        raise Hold("VERIFY_LOCAL_PACKAGE", "LOCAL_PACKAGE_NOT_YET_AVAILABLE")
    if not isinstance(expected, str) or not HASH.fullmatch(expected):
        raise Hold("CONFLICT", "PACKAGE_SHA_INVALID")
    path = safe_local(Path(filename))
    if not path.is_file() or path.stat().st_size == 0:
        raise Hold("VERIFY_LOCAL_PACKAGE", "LOCAL_PACKAGE_NOT_YET_AVAILABLE")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise Hold("CONFLICT", "LOCAL_PACKAGE_SHA_MISMATCH")
    return digest.hexdigest()


def validate_operator_evidence(job: dict, reference: dict) -> bool:
    filename = job.get("evidence_path")
    if not filename:
        return False
    path = safe_local(Path(filename))
    if not path.is_file():
        return False
    if path.stat().st_size > 32_768:
        raise Hold("HOLD", "EVIDENCE_TOO_LARGE")
    evidence = decode_json(path.read_text(encoding="utf-8"), 32_768)
    if set(evidence) != EVIDENCE_KEYS:
        raise Hold("CONFLICT", "EVIDENCE_FIELDS_NOT_ALLOWED")
    if (evidence["observation"] != "LOCAL_OPERATOR_OBSERVED_MATCH"
            or evidence["request_id"] != job["request_id"]
            or evidence["source_sha"] != job["source_sha"]):
        raise Hold("CONFLICT", "EVIDENCE_BINDING_MISMATCH")
    for local_key, remote_key in IDENTITY_FIELDS.items():
        value = evidence[local_key]
        if (not isinstance(value, str) or not value or value != reference.get(remote_key)):
            raise Hold("CONFLICT", "IDENTITY_REFERENCE_MISMATCH")
    return True


# Private, user-managed files are inputs only. No browser, Partner Center API,
# authentication session or secret-bearing Identity data enters scheduler state.
GAME_USER_IDENTITY_REQUIRED = {
    "request_id", "product_type", "slug", "source_sha",
    "official_evidence_url", "authenticated_account", "verified_at",
    "store_id", "name", "publisher", "version",
    "package_family_name", "package_sid",
}
GAME_USER_IDENTITY_ALLOWED = GAME_USER_IDENTITY_REQUIRED | {
    "source_repository", "source_branch", "publisher_display_name",
    "identity_name", "reserved_display_name",
}
GDK_USER_IDENTITY_REQUIRED = {
    "request_id", "product_type", "slug", "source_sha",
    "identity_source", "provided_at", "store_id", "name", "publisher",
    "publisher_display_name", "package_family_name", "package_sid",
    "packaging_family", "xbox_title_id", "xbox_scid", "msa_app_id",
}
STORE_USER_IDENTITY_REQUIRED = set(IDENTITY_FIELDS) | {
    "request_id", "source_sha", "source_repository", "source_branch",
    "product_type",
}


def user_provided_registry() -> dict:
    if not IDENTITY_REGISTRY_PATH.is_file() or IDENTITY_REGISTRY_PATH.stat().st_size > 64_000:
        raise Hold("HOLD", "USER_PROVIDED_IDENTITY_REGISTRY_MISSING")
    data = decode_json(IDENTITY_REGISTRY_PATH.read_text(encoding="utf-8"), 64_000)
    if (data.get("schema_version") != 1
            or data.get("source") != "USER_PROVIDED_PARTNER_CENTER"
            or not isinstance(data.get("products"), dict)):
        raise Hold("CONFLICT", "USER_PROVIDED_IDENTITY_REGISTRY_INVALID")
    return data


def materialize_game_registry_identity(job: dict, path: Path) -> bool:
    registry = user_provided_registry()
    record = registry["products"].get(job.get("slug") or "signal-sprint")
    if not isinstance(record, dict):
        return False
    exact = {
        "product_type": "GAME",
        "packaging_family": "GDK",
        "request_id": job["request_id"],
        "source_repository": job["repository"],
        "source_branch": job["branch"],
        "source_sha": job["source_sha"],
    }
    if any(record.get(key) != value for key, value in exact.items()):
        # The reviewed registry belongs only to its exact immutable product.
        # A different test/future request simply has no auto-materializable
        # Identity; explicit evidence will still be binding-checked later.
        return False
    required = {
        "store_id", "identity_name", "publisher", "publisher_display_name",
        "package_family_name", "package_sid", "xbox_title_id", "xbox_scid", "msa_app_id",
    }
    if any(not isinstance(record.get(key), str) or not record[key].strip() for key in required):
        raise Hold("CONFLICT", "USER_PROVIDED_IDENTITY_REGISTRY_FIELDS_MISSING")
    payload = {
        "request_id": job["request_id"],
        "product_type": "GAME",
        "slug": "signal-sprint",
        "source_sha": job["source_sha"],
        "identity_source": "USER_PROVIDED_PARTNER_CENTER",
        "provided_at": registry.get("provided_at"),
        "store_id": record["store_id"],
        "name": record["identity_name"],
        "publisher": record["publisher"],
        "publisher_display_name": record["publisher_display_name"],
        "package_family_name": record["package_family_name"],
        "package_sid": record["package_sid"],
        "packaging_family": "GDK",
        "xbox_title_id": record["xbox_title_id"],
        "xbox_scid": record["xbox_scid"],
        "msa_app_id": record["msa_app_id"],
    }
    if not isinstance(payload["provided_at"], str) or not payload["provided_at"]:
        raise Hold("CONFLICT", "USER_PROVIDED_IDENTITY_TIMESTAMP_MISSING")
    # The first operator run normally starts with no request-specific secure
    # directory. Create it without assuming that a prior worker already did.
    # Re-check after mkdir: an ancestor must not redirect into a checkout via
    # a symlink or Windows junction. Never overwrite an operator's own file.
    path.parent.mkdir(parents=True, exist_ok=True)
    if safe_local(path) != path:
        raise Hold("HOLD", "USER_IDENTITY_PATH_CHANGED_OR_EXISTS")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise Hold("HOLD", "USER_IDENTITY_PATH_CHANGED_OR_EXISTS") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return True


def user_identity_path(job: dict) -> Path | None:
    filename = job.get("identity_path")
    if not filename and job["kind"] == "GAME_SIGNAL_SPRINT":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise Hold("WAITING_USER_IDENTITY", "LOCALAPPDATA_REQUIRED_FOR_USER_IDENTITY")
        filename = str(Path(base) / "FactoryIdentityWorker" / "secure"
                       / job["request_id"] / "official-identity.json")
    if not filename:
        return None
    if not isinstance(filename, str):
        raise Hold("CONFLICT", "USER_IDENTITY_PATH_INVALID")
    path = safe_local(Path(filename))
    if job["kind"] == "GAME_SIGNAL_SPRINT" and path.name != "official-identity.json":
        raise Hold("CONFLICT", "GAME_IDENTITY_FILENAME_MISMATCH")
    return path


def validate_user_identity(job: dict, reference: dict | None = None) -> Path | None:
    path = user_identity_path(job)
    if path is None:
        return None
    if not path.exists() and job["kind"] == "GAME_SIGNAL_SPRINT":
        materialize_game_registry_identity(job, path)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > 32_768:
        raise Hold("HOLD", "USER_IDENTITY_FILE_INVALID_OR_TOO_LARGE")
    data = decode_json(path.read_text(encoding="utf-8"), 32_768)

    if job["kind"] == "GAME_SIGNAL_SPRINT":
        legacy = GAME_USER_IDENTITY_REQUIRED.issubset(data) and set(data).issubset(GAME_USER_IDENTITY_ALLOWED)
        gdk = set(data) == GDK_USER_IDENTITY_REQUIRED
        if not legacy and not gdk:
            raise Hold("CONFLICT", "USER_IDENTITY_SCHEMA_MISMATCH")
        if (data.get("request_id") != job["request_id"]
                or data.get("source_sha") != job["source_sha"]
                or data.get("product_type") != "GAME"
                or data.get("slug") != "signal-sprint"):
            raise Hold("CONFLICT", "USER_IDENTITY_BINDING_MISMATCH")
        if gdk:
            if (data.get("identity_source") != "USER_PROVIDED_PARTNER_CENTER"
                    or data.get("packaging_family") != "GDK"):
                raise Hold("CONFLICT", "USER_IDENTITY_GDK_SOURCE_MISMATCH")
            registry = user_provided_registry()
            record = registry["products"].get("signal-sprint")
            mapping = {
                "store_id": "store_id", "name": "identity_name",
                "publisher": "publisher", "publisher_display_name": "publisher_display_name",
                "package_family_name": "package_family_name", "package_sid": "package_sid",
                "xbox_title_id": "xbox_title_id", "xbox_scid": "xbox_scid",
                "msa_app_id": "msa_app_id",
            }
            exact_registry_binding = {
                "request_id": job["request_id"], "source_sha": job["source_sha"],
                "source_repository": job["repository"], "source_branch": job["branch"],
                "product_type": "GAME", "packaging_family": "GDK",
            }
            if (not isinstance(record, dict)
                    or any(record.get(key) != value for key, value in exact_registry_binding.items())
                    or data.get("provided_at") != registry.get("provided_at")
                    or any(data[left] != record.get(right) for left, right in mapping.items())):
                raise Hold("CONFLICT", "USER_IDENTITY_REFERENCE_MISMATCH")
        else:
            for key in GAME_USER_IDENTITY_REQUIRED:
                if not isinstance(data[key], str) or not data[key].strip():
                    raise Hold("CONFLICT", "USER_IDENTITY_FIELD_INVALID")
            if (data.get("source_repository", job["repository"]) != job["repository"]
                    or data.get("source_branch", job["branch"]) != job["branch"]):
                raise Hold("CONFLICT", "USER_IDENTITY_SOURCE_MISMATCH")
    else:
        required = STORE_USER_IDENTITY_REQUIRED
        if not required.issubset(data) or set(data) != required:
            raise Hold("CONFLICT", "USER_IDENTITY_SCHEMA_MISMATCH")
        if (data.get("request_id") != job["request_id"]
                or data.get("source_sha") != job["source_sha"]):
            raise Hold("CONFLICT", "USER_IDENTITY_BINDING_MISMATCH")
        if (reference is None or data["product_type"] != "APP"
                or data["source_repository"] != job["repository"]
                or data["source_branch"] != job["branch"]):
            raise Hold("CONFLICT", "USER_IDENTITY_SOURCE_MISMATCH")
        for local_key, remote_key in IDENTITY_FIELDS.items():
            if data[local_key] != reference.get(remote_key):
                raise Hold("CONFLICT", "USER_IDENTITY_REFERENCE_MISMATCH")
    # The dedicated worker/Provisioner independently performs the CAS.
    # A registry/schema match records operator-provided Store identity; it is
    # not browser authentication and does not authorize Store submission.
    return path


def version_gate(reference: dict) -> bool:
    version = reference.get("approved_store_version")
    return (isinstance(version, str) and VERSION.fullmatch(version) is not None
            and reference.get("package_version_approval") == "APPROVED"
            and reference.get("brand_assets_approval") == "APPROVED")


def read_previous(state_path: Path, job: dict) -> dict | None:
    if not state_path.exists():
        return None
    if state_path.is_symlink():
        raise Hold("CONFLICT", "STATE_SYMLINK")
    state = decode_json(state_path.read_text(encoding="utf-8"), 64_000)
    if (state.get("request_id") != job["request_id"]
            or state.get("source_sha") != job["source_sha"]
            or state.get("repository") != job["repository"]
            or state.get("branch") != job["branch"]
            or state.get("kind") != job["kind"]
            or state.get("stage") not in STAGES):
        raise Hold("CONFLICT", "PERSISTED_JOB_BINDING_MISMATCH")
    # A delegated CAS may have committed even if its process crashed or its
    # response was lost. Never retry it from an unresolved local marker.
    if (state["stage"] == "CAS_RETURN" or
            (state["stage"] == "HOLD" and state.get("reason") ==
             "DELEGATED_CAS_OUTCOME_REQUIRES_RECONCILIATION")):
        raise Hold("HOLD", "DELEGATED_CAS_OUTCOME_REQUIRES_RECONCILIATION")
    # A resumable CAS-completed state is not proof by itself. Reject a
    # truncated/forged local receipt before the idempotent fast path.
    if state["stage"] in {"WAITING_FACTORY_MSIX", "CAS_RETURNED", "DONE"}:
        commit = state.get("factory_return_commit_sha")
        if (job["kind"] != "GAME_SIGNAL_SPRINT"
                or state.get("identity_return") is not True
                or not isinstance(commit, str) or not SHA.fullmatch(commit)):
            raise Hold("CONFLICT", "PERSISTED_CAS_RECEIPT_UNVERIFIED")
    return state


def store_job(job: dict, observed_sha: str) -> dict:
    reference, blob = remote_json(job["repository"], REFERENCE_PATH, observed_sha)
    if reference.get("product_repo") != job["repository"].split("/", 1)[1]:
        raise Hold("CONFLICT", "REFERENCE_REPOSITORY_MISMATCH")
    builder = reference.get("existing_msix_builder")
    if not isinstance(builder, str) or not re.fullmatch(r"store/[A-Za-z0-9._/-]+\.ps1", builder):
        raise Hold("HOLD", "BUILDER_NOT_DECLARED")
    # Detect each product's builder from its own reviewed reference. No build.
    builder_data = gh("repos/" + job["repository"] + "/contents/" + builder + "?ref=" + observed_sha)
    if builder_data.get("type") != "file":
        raise Hold("HOLD", "BUILDER_NOT_FOUND")
    package = inspect_package(job)
    operator_match = validate_operator_evidence(job, reference)
    identity_file = validate_user_identity(job, reference)
    return {
        "stage": "IDENTITY_VALIDATED" if identity_file else "WAITING_USER_IDENTITY",
        "reason": ("USER_IDENTITY_VALIDATED__STORE_CAS_NOT_CONNECTED"
                   if identity_file else "USER_IDENTITY_FILE_MISSING"),
        "identity_discovery": True, "identity_authentication": False,
        "user_identity_validated": bool(identity_file),
        "identity_observation": "LOCAL_OPERATOR_OBSERVED_MATCH" if operator_match else None,
        "identity_return": False,
        # Version/asset approval is necessary but never sufficient: this job
        # has neither authenticated Identity nor a verified CAS return.
        "msix_build_allowed": False,
        "version_approvals_ready": version_gate(reference),
        "msix_build": False, "builder": builder, "reference_blob_sha": blob,
        "package_sha256": package,
        "approval_hold": None if version_gate(reference) else "STORE_VERSION_OR_BRAND_APPROVAL_MISSING",
    }


def game_job(job: dict, observed_sha: str, args, on_cas_start=None) -> dict:
    ledger_sha = head(CENTRAL_REPO, CENTRAL_BRANCH)
    ledger, _ = remote_json(CENTRAL_REPO, CENTRAL_PATH, ledger_sha)
    product = ledger.get("active_product") or {}
    required = {
        "request_id": job["request_id"], "source_sha": job["source_sha"],
        "source_branch": job["branch"], "source_repository": job["repository"],
        "expected_head_sha": job["source_sha"],
    }
    if any(product.get(k) != v for k, v in required.items()):
        raise Hold("CONFLICT", "CENTRAL_GAME_LEDGER_BINDING_MISMATCH")
    if observed_sha != job["source_sha"]:
        raise Hold("CONFLICT", "GAME_SOURCE_HEAD_CHANGED")
    package = inspect_package(job)
    if package != (product.get("local_execution_result") or {}).get("package_sha256"):
        raise Hold("CONFLICT", "GAME_PACKAGE_NOT_PINNED_TO_LEDGER")
    identity_file = validate_user_identity(job)
    if identity_file is None:
        raise Hold("WAITING_USER_IDENTITY", "USER_IDENTITY_FILE_MISSING")
    if args.apply_request_id != job["request_id"]:
        raise Hold("WAITING_CAS_APPROVAL", "USER_IDENTITY_VALIDATED__EXPLICIT_CAS_APPROVAL_REQUIRED")
    if args.confirm_request_id != job["request_id"] or os.name != "nt":
        raise Hold("WAITING_CAS_APPROVAL", "LOCAL_WINDOWS_EXPLICIT_APPROVAL_REQUIRED")
    if not args.provisioner_root or not args.provisioner_result:
        raise Hold("WAITING_CAS_APPROVAL", "PROVISIONER_INPUTS_REQUIRED")
    safety = product.get("provisioner_package_safety") or {}
    if not SHA.fullmatch(safety.get("head_sha", "")):
        raise Hold("CONFLICT", "PROVISIONER_SHA_UNVERIFIED")
    if head(job["repository"], job["branch"]) != job["source_sha"]:
        raise Hold("CONFLICT", "GAME_HEAD_CHANGED_BEFORE_CAS")
    command = [
        sys.executable, "-m", "scripts.local_identity_return",
        "--provisioner-root", str(args.provisioner_root),
        "--provisioner-branch", safety["branch"],
        "--provisioner-sha", safety["head_sha"],
        "--provisioner-result", str(args.provisioner_result),
        "--source-branch", job["branch"], "--source-sha", job["source_sha"],
        "--request-id", job["request_id"], "--ledger-ref", CENTRAL_BRANCH,
        "--ledger-sha", ledger_sha, "--local-dir", str(identity_file.parent),
        "--official-identity", str(identity_file),
        "--apply", "--confirm-request-id", job["request_id"],
    ]
    # Durable intent MUST precede the external CAS subprocess: a power loss
    # or unparseable response must not cause an automatic second CAS.
    if on_cas_start is not None:
        on_cas_start()
    try:
        proc = subprocess.run(command, capture_output=True, text=True,
                              encoding="utf-8", timeout=2700, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Hold("HOLD", "DELEGATED_WORKER_UNAVAILABLE_RECONCILE") from exc
    # Never copy subprocess stdout/stderr into a receipt.
    if proc.returncode:
        raise Hold("HOLD", "DELEGATED_WORKER_HOLD_CHECK_PRIVATE_RECEIPT")
    output = decode_json(proc.stdout, 32_768)
    commit = output.get("factory_return_commit_sha")
    if output.get("status") != "CAS_RETURNED_MSIX_PENDING" or not isinstance(commit, str) or not SHA.fullmatch(commit):
        raise Hold("HOLD", "DELEGATED_CAS_UNCONFIRMED")
    return {"stage": "WAITING_FACTORY_MSIX", "reason": "CAS_RETURNED_MSIX_PENDING",
            "identity_discovery": True, "identity_authentication": False,
            "user_identity_validated": True,
            "identity_return": True, "factory_return_commit_sha": commit,
            "msix_build": False, "package_sha256": package}


def process(job: dict, args, state_dir: Path) -> dict:
    state_path = state_dir / (hashlib.sha256(job["request_id"].encode()).hexdigest() + ".json")
    previous = read_previous(state_path, job)
    if previous and previous.get("stage") in {"WAITING_FACTORY_MSIX", "CAS_RETURNED", "DONE"}:
        # CAS moves the original Factory branch to the returned commit. Later
        # integration must happen on a separate branch; never trust stale state
        # after an unexpected source-branch move, and never replay CAS.
        if head(job["repository"], job["branch"]) != previous["factory_return_commit_sha"]:
            raise Hold("CONFLICT", "FACTORY_HEAD_CHANGED_AFTER_CAS")
        return previous
    result = {
        "schema_version": 1, "request_id": job["request_id"],
        "source_sha": job["source_sha"], "repository": job["repository"],
        "branch": job["branch"], "kind": job["kind"], "stage": "DISCOVER_JOB",
        "reason": None, "identity_discovery": False, "identity_authentication": False,
        "user_identity_validated": False,
        "identity_return": False, "msix_build": False, "github_backlog": False,
        "local_pull": False, "checker": False, "gui_qa": False, "e2e_pass": False,
    }
    try:
        observed = head(job["repository"], job["branch"])
        if observed != job["source_sha"]:
            raise Hold("CONFLICT", "BRANCH_HEAD_CHANGED")
        result["stage"] = "VERIFY_BRANCH_HEAD"
        if job["kind"] == "STORE_KNOWN_GOOD":
            result.update(store_job(job, observed))
        elif job["kind"] == "GAME_SIGNAL_SPRINT":
            def mark_cas_start():
                atomic_json(state_path, {
                    **result, "stage": "CAS_RETURN",
                    "reason": "DELEGATED_CAS_OUTCOME_REQUIRES_RECONCILIATION",
                })
            result.update(game_job(job, observed, args, mark_cas_start))
        else:
            raise Hold("HOLD", "ROTATION_IDENTITY_ROUTING_NOT_YET_APPROVED")
    except Hold as exc:
        # If the worker was launched, its result is uncertain even when it
        # returned an error. Preserve the durable marker until manual review.
        pending = (decode_json(state_path.read_text(encoding="utf-8"), 64_000)
                   if state_path.is_file() else {})
        if pending.get("stage") == "CAS_RETURN":
            result["stage"] = "HOLD"
            result["reason"] = "DELEGATED_CAS_OUTCOME_REQUIRES_RECONCILIATION"
        else:
            result["stage"], result["reason"] = exc.stage, exc.reason
    atomic_json(state_path, result)
    return result



def choose_job(jobs: list[dict], index: int, apply_request_id: str) -> tuple[int, dict]:
    """Select exactly the approved GAME job, or use ordinary round-robin."""
    if apply_request_id:
        matches = [(i, job) for i, job in enumerate(jobs)
                   if job["request_id"] == apply_request_id]
        if len(matches) != 1:
            raise Hold("CONFLICT", "APPLY_REQUEST_ID_NOT_IN_QUEUE")
        selected_index, selected = matches[0]
        if selected["kind"] != "GAME_SIGNAL_SPRINT":
            raise Hold("HOLD", "CAS_DELEGATION_GAME_ONLY")
        return selected_index, selected
    selected_index = index % len(jobs)
    return selected_index, jobs[selected_index]


def run(args) -> dict:
    if os.name != "nt" and args.apply_request_id:
        raise Hold("HOLD", "LOCAL_WINDOWS_REQUIRED_FOR_CAS")
    state_dir = safe_local(args.state_dir)
    config_path = safe_local(args.jobs_file)
    if not config_path.is_file() or config_path.stat().st_size > 200_000:
        raise Hold("HOLD", "LOCAL_JOB_FILE_MISSING_OR_TOO_LARGE")
    config = decode_json(config_path.read_text(encoding="utf-8"))
    jobs = validate_jobs(config)
    state_dir.mkdir(parents=True, exist_ok=True)
    with ExclusiveLock(state_dir / ".scheduler.lock"):
        cursor_path = state_dir / "cursor.json"
        cursor = decode_json(cursor_path.read_text(encoding="utf-8")) if cursor_path.exists() else {}
        index = cursor.get("next_index", 0)
        if type(index) is not int or index < 0:
            raise Hold("CONFLICT", "CURSOR_INVALID")
        # A human-authorized CAS must target its exact immutable request_id,
        # regardless of the round-robin cursor. Never silently process another
        # job and consume an approval intended for a different product.
        index, selected = choose_job(jobs, index, args.apply_request_id)
        result = process(selected, args, state_dir)
        atomic_json(cursor_path, {"next_index": (index + 1) % len(jobs)})
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local-only one-job-per-run Identity scheduler")
    parser.add_argument("--jobs-file", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--apply-request-id", default="")
    parser.add_argument("--confirm-request-id", default="")
    parser.add_argument("--provisioner-root", type=Path)
    parser.add_argument("--provisioner-result", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except Hold as exc:
        result = {"stage": exc.stage, "reason": exc.reason, "e2e_pass": False}
    except (OSError, ValueError, UnicodeError, TypeError):
        result = {"stage": "HOLD", "reason": "LOCAL_INPUT_OR_FILESYSTEM_ERROR", "e2e_pass": False}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("stage") in {"WAITING_FACTORY_MSIX", "DONE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
