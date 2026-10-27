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

OWNER = "shihuiarenjinba-png"
CENTRAL_REPO = OWNER + "/Windows-all-auto"
CENTRAL_BRANCH = "codex/e2e-belt-connection-20261027"
CENTRAL_PATH = "ops/active_e2e_handoff.json"
REFERENCE_PATH = "store/unsigned_msix_submission_inputs.json"
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
    if any(p.is_symlink() for p in original_ancestors):
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
        if job.get("kind") not in {"STORE_KNOWN_GOOD", "GAME_SIGNAL_SPRINT", "APP_CANARY"}:
            raise Hold("CONFLICT", "UNKNOWN_JOB_KIND")
        if job["kind"] == "STORE_KNOWN_GOOD":
            if repo.split("/", 1)[1] not in STORE_REFS or branch != STORE_REFS[repo.split("/", 1)[1]]:
                raise Hold("CONFLICT", "STORE_REFERENCE_BRANCH_MISMATCH")
        if job["kind"] == "GAME_SIGNAL_SPRINT" and repo != OWNER + "/AI-Game-Factory":
            raise Hold("CONFLICT", "GAME_FACTORY_MISMATCH")
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
    if not validate_operator_evidence(job, reference):
        raise Hold("WAITING_PARTNER_CENTER_AUTH", "LOCAL_OPERATOR_EVIDENCE_MISSING")
    return {
        "stage": "WAITING_PARTNER_CENTER_AUTH", "reason": "LOCAL_OPERATOR_MATCH_NOT_AUTHENTICATED__STORE_CAS_NOT_CONNECTED",
        "identity_discovery": True, "identity_authentication": False,
        "identity_observation": "LOCAL_OPERATOR_OBSERVED_MATCH",
        "identity_return": False, "msix_build_allowed": version_gate(reference),
        "msix_build": False, "builder": builder, "reference_blob_sha": blob,
        "package_sha256": package,
        "approval_hold": None if version_gate(reference) else "STORE_VERSION_OR_BRAND_APPROVAL_MISSING",
    }


def game_job(job: dict, observed_sha: str, args) -> dict:
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
    if args.apply_request_id != job["request_id"]:
        raise Hold("WAITING_PARTNER_CENTER_AUTH", "GAME_WORKER_CHECK_ONLY_OR_IDENTITY_HOLD")
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
        "--ledger-sha", ledger_sha, "--apply", "--confirm-request-id", job["request_id"],
    ]
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
            "identity_return": True, "factory_return_commit_sha": commit,
            "msix_build": False, "package_sha256": package}


def process(job: dict, args, state_dir: Path) -> dict:
    state_path = state_dir / (hashlib.sha256(job["request_id"].encode()).hexdigest() + ".json")
    previous = read_previous(state_path, job)
    if previous and previous.get("stage") in {"WAITING_FACTORY_MSIX", "CAS_RETURNED", "DONE"}:
        return previous  # Do not replay CAS; reconcile via dedicated worker/QA.
    result = {
        "schema_version": 1, "request_id": job["request_id"],
        "source_sha": job["source_sha"], "repository": job["repository"],
        "branch": job["branch"], "kind": job["kind"], "stage": "DISCOVER_JOB",
        "reason": None, "identity_discovery": False, "identity_authentication": False,
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
            result.update(game_job(job, observed, args))
        else:
            raise Hold("HOLD", "APP_CANARY_REFERENCE_AND_IDENTITY_NOT_READY")
    except Hold as exc:
        result["stage"], result["reason"] = exc.stage, exc.reason
    atomic_json(state_path, result)
    return result


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
        selected = jobs[index % len(jobs)]  # exactly one job per invocation
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
