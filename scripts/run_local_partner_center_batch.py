"""One-command, no-LLM Windows Partner Center APP Identity batch runner."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from typing import Any
import zipfile

from scripts import local_code_sync
from scripts import audit_identity_rotation as rotation_audit
from scripts import mixed_rotation_dispatch as rotation_plan
from scripts import mixed_artifact_expiry as artifact_expiry
from scripts import mixed_batch_resume as mixed_resume
from scripts import mixed_resume_rebase as mixed_rebase
from scripts import local_identity_batch as batch
from scripts import local_partner_center_operator as operator
from scripts.partner_center_cdp import (
    IdentityObservation,
    PartnerCenterDriver,
    PartnerCenterHold,
)


EXPECTED_ORDER = (
    "focus-session-desk",
    "file-integrity-ledger",
    "offline-text-diff-desk",
    "offline-image-inventory-desk",
)
PROVISIONER_BASE_SHA = "5d8f28520f8d6e89874c1cc8ce9cffede18a5e1b"
EXECUTION_ORIGINS = batch.EXECUTION_ORIGINS
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024


class RunnerHold(RuntimeError):
    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 180,
        input_text: str | None = None, binary_output=None) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            input=input_text,
            stdout=binary_output if binary_output is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=binary_output is None,
            encoding="utf-8" if binary_output is None else None,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RunnerHold("HOLD_LOCAL_PREREQUISITE") from exc
    if result.returncode != 0:
        detail = result.stderr
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        raise RunnerHold("HOLD_COMMAND_FAILED", str(detail or "")[:240])
    return result.stdout.strip() if isinstance(result.stdout, str) else ""


def gh_json(endpoint: str, *, allow_missing: bool = False) -> dict | None:
    command = ["gh", "api", "--method", "GET", endpoint]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8",
            timeout=60, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RunnerHold("HOLD_GITHUB_API") from exc
    if allow_missing and result.returncode != 0 and "HTTP 404" in result.stderr:
        return None
    if result.returncode != 0:
        raise RunnerHold("HOLD_GITHUB_API")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RunnerHold("HOLD_GITHUB_API") from exc
    if not isinstance(value, dict):
        raise RunnerHold("HOLD_GITHUB_API")
    return value


def git_value(root: Path, *args: str) -> str:
    return run(["git", "-C", str(root), *args], timeout=60)


def check_prerequisites(provisioner_root: Path) -> dict:
    if os.name != "nt":
        raise RunnerHold("HOLD_LOCAL_PREREQUISITE")
    for command in (["py", "-3", "--version"], ["git", "--version"],
                    ["gh", "--version"], ["gh", "auth", "status"]):
        run(command, timeout=30)
    if not provisioner_root.is_dir():
        raise RunnerHold("HOLD_LOCAL_PREREQUISITE")
    head = git_value(provisioner_root, "rev-parse", "HEAD")
    try:
        run(["git", "-C", str(provisioner_root), "merge-base", "--is-ancestor",
             PROVISIONER_BASE_SHA, head], timeout=30)
    except RunnerHold as exc:
        raise RunnerHold("HOLD_UNREVIEWED_PROVISIONER") from exc
    if git_value(provisioner_root, "status", "--porcelain"):
        raise RunnerHold("HOLD_UNREVIEWED_PROVISIONER")
    branch = git_value(provisioner_root, "branch", "--show-current")
    if not branch.startswith("codex/"):
        raise RunnerHold("HOLD_UNREVIEWED_PROVISIONER")
    remote = gh_json(
        "repos/shihuiarenjinba-png/Repository-Provisioner-app/git/ref/heads/" + branch
    )
    if remote is None or remote.get("object", {}).get("sha") != head:
        raise RunnerHold("HOLD_UNREVIEWED_PROVISIONER")
    return {"provisioner_head": head, "provisioner_branch": branch}


def fetch_central() -> tuple[dict, str, str]:
    ref = gh_json(
        f"repos/{batch.CENTRAL_REPOSITORY}/git/ref/heads/{batch.CENTRAL_BRANCH}"
    )
    head = ref.get("object", {}).get("sha") if ref else None
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RunnerHold("HOLD_GITHUB_API")
    item = gh_json(
        f"repos/{batch.CENTRAL_REPOSITORY}/contents/ops/active_e2e_handoff.json"
        f"?ref={batch.CENTRAL_BRANCH}"
    )
    if item is None or item.get("encoding") != "base64":
        raise RunnerHold("HOLD_GITHUB_API")
    try:
        raw = base64.b64decode("".join(str(item["content"]).split()), validate=True)
        ledger = json.loads(raw.decode("utf-8"), object_pairs_hook=operator._no_duplicates)
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunnerHold("HOLD_GITHUB_API") from exc
    if not isinstance(ledger, dict):
        raise RunnerHold("HOLD_GITHUB_API")
    return ledger, head, str(item.get("sha", ""))


def live_branch_head(repository: str, branch: str) -> str:
    ref = gh_json(f"repos/{repository}/git/ref/heads/{branch}")
    value = ref.get("object", {}).get("sha") if ref else None
    if not isinstance(value, str):
        raise RunnerHold("HOLD_GITHUB_API")
    return value


def recheck_central(expected: str) -> None:
    current = live_branch_head(batch.CENTRAL_REPOSITORY, batch.CENTRAL_BRANCH)
    if current != expected:
        raise RunnerHold("HOLD_CENTRAL_QUEUE_HEAD_DRIFT")


def validate_queue(ledger: dict, central_head: str, execution_origin: str) -> tuple[dict, list[dict]]:
    jobs = (ledger.get("rotation_cohorts") or {}).get("app_jobs")
    ready = [x for x in jobs or [] if isinstance(x, dict)
             and x.get("status") == "PRE_IDENTITY_READY"]
    if len(ready) != 4 or tuple(x.get("slug") for x in ready) != EXPECTED_ORDER:
        raise RunnerHold("HOLD_BATCH_DISCOVERY_INCOMPLETE")
    products = []
    for index, job in enumerate(ready, 1):
        if live_branch_head(job["source_repository"], job["source_branch"]) != job["source_sha"]:
            raise RunnerHold("HOLD_CANONICAL_PRODUCT_REVISION_MISMATCH")
        artifact = gh_json(
            f"repos/{job['source_repository']}/actions/artifacts/{job['factory_artifact_id']}"
        )
        digest = "sha256:" + str(job.get("factory_artifact_zip_sha256", ""))
        if (artifact is None or artifact.get("expired") is not False
                or artifact.get("name") != job.get("factory_artifact_name")
                or artifact.get("digest") != digest
                or job.get("artifact_metadata_verified") is not True
                or job.get("factory_build_head") != job.get("source_sha")):
            raise RunnerHold("HOLD_ARTIFACT_MISMATCH")
        products.append({
            "batch_index": index,
            "request_id": job["request_id"],
            "slug": job["slug"],
            "source_sha": job["source_sha"],
            "artifact_id": job["factory_artifact_id"],
            "expected_exe_sha256": job["expected_exe_sha256"],
            "identity_return_target": job["identity_return_target"],
        })
    spec = {
        "schema_version": 1,
        "batch_id": "app-batch4-" + central_head[:12],
        "trigger_origin": batch.TRIGGER_ORIGIN,
        "dispatch_origin": batch.DISPATCH_ORIGIN,
        "execution_origin": execution_origin,
        "automation_id": batch.AUTOMATION_ID,
        "central_repository": batch.CENTRAL_REPOSITORY,
        "central_branch": batch.CENTRAL_BRANCH,
        "central_head_sha": central_head,
        "scheduled_at": utc_now(),
        "products": products,
    }
    return spec, ready


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifact(job: dict, root: Path) -> dict:
    target = root / job["slug"]
    target.mkdir(parents=True, exist_ok=True)
    archive = target / (str(job["factory_artifact_id"]) + ".zip")
    expected_zip = job["factory_artifact_zip_sha256"]
    if archive.exists():
        if archive.stat().st_size > MAX_ARTIFACT_BYTES or sha256_file(archive) != expected_zip:
            raise RunnerHold("HOLD_ARTIFACT_MISMATCH")
    else:
        partial = target / (archive.name + ".partial")
        if partial.exists():
            raise RunnerHold("HOLD_ARTIFACT_PARTIAL_CONFLICT")
        with partial.open("xb") as output:
            run([
                "gh", "api", "--method", "GET",
                f"repos/{job['source_repository']}/actions/artifacts/{job['factory_artifact_id']}/zip",
            ], timeout=180, binary_output=output)
        if partial.stat().st_size > MAX_ARTIFACT_BYTES or sha256_file(partial) != expected_zip:
            raise RunnerHold("HOLD_ARTIFACT_MISMATCH")
        os.replace(partial, archive)
    with zipfile.ZipFile(archive) as bundle:
        matches = []
        total = 0
        for info in bundle.infolist():
            name = PurePosixPath(info.filename.replace("\\", "/"))
            if name.is_absolute() or ".." in name.parts:
                raise RunnerHold("HOLD_ARTIFACT_UNSAFE")
            total += info.file_size
            if total > MAX_ARTIFACT_BYTES:
                raise RunnerHold("HOLD_ARTIFACT_UNSAFE")
            if info.is_dir() or name.suffix.lower() != ".exe":
                continue
            digest = hashlib.sha256()
            size = 0
            with bundle.open(info) as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            if digest.hexdigest() == job["expected_exe_sha256"] and size == job["expected_exe_bytes"]:
                matches.append((info, name.name, size))
        if len(matches) != 1:
            raise RunnerHold("HOLD_ARTIFACT_MISMATCH")
        info, name, size = matches[0]
        extracted = target / name
        if extracted.exists():
            if extracted.stat().st_size != size or sha256_file(extracted) != job["expected_exe_sha256"]:
                raise RunnerHold("HOLD_ARTIFACT_MISMATCH")
        else:
            temporary = target / (name + ".partial")
            if temporary.exists():
                raise RunnerHold("HOLD_ARTIFACT_PARTIAL_CONFLICT")
            with bundle.open(info) as source, temporary.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            if temporary.stat().st_size != size or sha256_file(temporary) != job["expected_exe_sha256"]:
                raise RunnerHold("HOLD_ARTIFACT_MISMATCH")
            os.replace(temporary, extracted)
    return {
        "artifact_id": job["factory_artifact_id"],
        "artifact_zip_sha256": expected_zip,
        "exe_sha256": job["expected_exe_sha256"],
        "exe_bytes": job["expected_exe_bytes"],
        "exe_path": str(extracted),
    }


def sync_sources(jobs: list[dict], state_dir: Path) -> dict:
    manifest_path = state_dir / "source-sync-manifest.json"
    receipt_path = state_dir / "source-sync-receipt.json"
    manifest = {"schema_version": 1, "jobs": [{
        "repository": job["source_repository"],
        "branch": job["source_branch"],
        "source_sha": job["source_sha"],
        "slug": job["slug"],
        "request_id": job["request_id"],
    } for job in jobs]}
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") != encoded:
        raise RunnerHold("HOLD_LOCAL_SOURCE_SYNC")
    if not manifest_path.exists():
        manifest_path.write_text(encoded, encoding="utf-8")
    try:
        return local_code_sync.sync_manifest(
            manifest_path, state_dir / "sources", receipt_path
        )
    except (local_code_sync.SyncHold, OSError) as exc:
        raise RunnerHold("HOLD_LOCAL_SOURCE_SYNC") from exc


def import_provisioner(root: Path):
    location = str(root.resolve())
    if location not in sys.path:
        sys.path.insert(0, location)
    importlib.invalidate_caches()
    return importlib.import_module("identity_only_return"), importlib.import_module(
        "package_identity_provisioner"
    )


def write_once(path: Path, value: dict) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != payload:
            raise RunnerHold("HOLD_RECEIPT_CONFLICT")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def complete_name_unavailable(state: dict, claimed: dict,
                              product_dir: Path, source_sync_status: str) -> dict:
    """Advance one product only when name availability failed before Reserve.

    Authentication, uncertain creation, duplicate products and CAS conflicts
    are intentionally *not* handled here: those stop the whole batch.
    """
    result = {
        "batch_id": state["batch_id"],
        "batch_index": claimed["batch_index"],
        "request_id": claimed["request_id"],
        "slug": claimed["slug"],
        "source_sha": claimed["source_sha"],
        "identity_return_target": claimed["identity_return_target"],
        "github_return_status": "HOLD",
        "source_sync_status": source_sync_status,
        "package_version_gate": "HOLD",
        "store_submission": "NOT_PERFORMED",
        "error_code": "HOLD_NAME_UNAVAILABLE",
    }
    completed = batch.complete_active(state, result)
    batch.atomic_write(product_dir.parent.parent / "batch-state.json", completed)
    write_once(product_dir / "result.json", result)
    return completed


def existing_observation(driver: PartnerCenterDriver, receipt: dict) -> IdentityObservation:
    count = driver.page.search_product(receipt["display_name"])
    if count != 1:
        raise RunnerHold("HOLD_DUPLICATE_PRODUCT")
    identity = driver.page.open_identity(receipt["display_name"])
    expected = {key: receipt[key] for key in operator.IDENTITY}
    if identity != expected:
        raise RunnerHold("HOLD_IDENTITY_DETAILS_AMBIGUOUS")
    snapshot = driver.page.safe_snapshot()
    return IdentityObservation(
        target_id=driver.page.target_id,
        display_name=receipt["display_name"],
        creation_status=receipt["creation_status"],
        initial_search_count=0 if receipt["creation_status"] == "CREATED" else 1,
        identity=identity,
        observed_url=str(snapshot["url"]),
        observed_title=str(snapshot["title"]),
    )


def github_result_verified(job: dict, receipt: dict, commit_sha: str,
                           central_head: str, source_path: Path) -> bool:
    try:
        recheck_central(central_head)
        if git_value(source_path, "rev-parse", "HEAD") != job["source_sha"]:
            return False
        if git_value(source_path, "status", "--porcelain"):
            return False
        current = live_branch_head(job["source_repository"], job["source_branch"])
        if current != commit_sha:
            return False
        item = gh_json(
            f"repos/{job['source_repository']}/contents/{job['identity_return_target']}"
            f"?ref={job['source_branch']}"
        )
        if item is None or item.get("encoding") != "base64":
            return False
        raw = base64.b64decode("".join(str(item["content"]).split()), validate=True)
        approved = json.loads(raw.decode("utf-8"), object_pairs_hook=operator._no_duplicates)
        exact = {
            "request_id": job["request_id"], "source_sha": job["source_sha"],
            "store_id": receipt["store_id"], "name": receipt["identity_name"],
            "publisher": receipt["publisher"],
            "package_family_name": receipt["package_family_name"],
            "package_sid": receipt["package_sid"],
            "dispatch_origin": batch.DISPATCH_ORIGIN,
            "execution_origin": receipt["execution_origin"],
        }
        return all(approved.get(k) == v for k, v in exact.items())
    except Exception:
        return False


def resolve_execution_origin(requested: str, state_dir: Path) -> str:
    if requested not in EXECUTION_ORIGINS:
        raise RunnerHold("HOLD_EXECUTION_ORIGIN_CONFLICT")
    marker = state_dir / "scheduler-manual-start.marker"
    if requested == "WINDOWS_TASK_SCHEDULER" and marker.exists():
        marker.unlink()
        return "WINDOWS_TASK_SCHEDULER_MANUAL_START"
    return requested


def validate_existing_state(state: dict, spec: dict, central_head: str,
                            execution_origin: str) -> bool:
    """Validate resumability and report whether this batch already completed.

    A completed manual batch is intentionally reusable by the scheduled runner as
    a no-work receipt.  An in-progress batch remains bound to its original
    execution origin so that a scheduler cannot take over a terminal run.
    """
    if (state.get("batch_id") != spec["batch_id"]
            or state.get("central_head_sha") != central_head):
        raise RunnerHold("BATCH_EXISTING_STATE_CONFLICT")
    if state.get("final_status") in {
            "MULTI_PRODUCT_IDENTITY_BATCH_PASS",
            "MULTI_PRODUCT_IDENTITY_BATCH_PARTIAL"}:
        if state.get("processed_count") != 4:
            raise RunnerHold("BATCH_EXISTING_STATE_CONFLICT")
        if state["final_status"] == "MULTI_PRODUCT_IDENTITY_BATCH_PASS":
            # Legacy or user-edited state cannot turn a manual run into PASS.
            if (state.get("execution_origin") != "WINDOWS_TASK_SCHEDULER"
                    or state.get("execution_trigger_proven") is not True):
                raise RunnerHold("BATCH_SCHEDULE_TRIGGER_NOT_PROVEN")
        return True
    if state.get("execution_origin") != execution_origin:
        raise RunnerHold("BATCH_EXISTING_STATE_CONFLICT")
    return False


def audit_queue_only(args, *, central_snapshot=None) -> dict:
    """Read-only GitHub audit; NEVER a local Identity, CAS, or scheduler PASS.

    Unlike the legacy four-PRE-Identity runner this can inspect a returned
    Focus Identity and three still-PRE products without treating the former
    as a new Partner Center product. No browser or local Windows required.
    """
    ledger, central_head, _ = (central_snapshot if central_snapshot is not None
                               else fetch_central())

    def fetch_approved(repository: str, target: str, source_branch: str):
        item = gh_json(
            f"repos/{repository}/contents/{target}?ref={source_branch}",
            allow_missing=True,
        )
        if item is None:
            return None
        if item.get("encoding") != "base64":
            raise RunnerHold("HOLD_APPROVED_IDENTITY_FILE_INVALID")
        try:
            raw = base64.b64decode(
                "".join(str(item["content"]).split()), validate=True
            )
            return raw.decode("utf-8")
        except (KeyError, ValueError, UnicodeError) as exc:
            raise RunnerHold("HOLD_APPROVED_IDENTITY_FILE_INVALID") from exc

    result = rotation_audit.audit_rotation(
        ledger,
        fetch_head=live_branch_head,
        fetch_approved=fetch_approved,
        fetch_artifact=lambda repo, artifact_id: gh_json(
            f"repos/{repo}/actions/artifacts/{artifact_id}"
        ),
    )
    recheck_central(central_head)
    return {**result, "central_head_sha": central_head}


def plan_queue_only(args) -> dict:
    """Read-only mixed-state plan; never runs the legacy four-PRE local worker."""
    snapshot = fetch_central()
    audit = audit_queue_only(args, central_snapshot=snapshot)
    result = rotation_plan.build_dispatch_plan(snapshot[0], audit)
    recheck_central(snapshot[1])
    return {**result, "central_head_sha": snapshot[1]}


def mixed_preflight_root(state_dir: Path, pending: list[dict]) -> Path:
    """Namespace immutable source/EXE snapshots by the exact pending cohort.

    After a successful CAS, the central single writer promotes one PRE job to
    POST. Reusing the previous mutable manifest would otherwise cause a
    permanent HOLD_LOCAL_SOURCE_SYNC on the next (smaller) cohort. Never
    rewrite the previous cohort's manifest or immutable source snapshots.
    """
    if not isinstance(pending, list) or not pending:
        raise RunnerHold("HOLD_MIXED_PREFLIGHT_COHORT_INVALID")
    keys = ("batch_index", "slug", "request_id", "source_repository",
            "source_branch", "source_sha", "identity_return_target")
    try:
        binding = [{key: item[key] for key in keys} for item in pending]
    except (KeyError, TypeError) as exc:
        raise RunnerHold("HOLD_MIXED_PREFLIGHT_COHORT_INVALID") from exc
    if any(not isinstance(value, (str, int)) or value == ""
           for item in binding for value in item.values()):
        raise RunnerHold("HOLD_MIXED_PREFLIGHT_COHORT_INVALID")
    digest = hashlib.sha256(json.dumps(
        binding, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()[:24]
    return state_dir.resolve() / "mixed-preflight" / "cohorts" / digest


def validated_mixed_source_path(state_dir: Path, receipt: dict,
                                job: dict) -> Path:
    """Resolve an untrusted receipt path only inside a pinned cohort snapshot."""
    raw = receipt.get("source_snapshot_path")
    if not isinstance(raw, str) or not raw:
        raise RunnerHold("HOLD_MIXED_SOURCE_PATH_UNTRUSTED")
    supplied = Path(raw)
    if not supplied.is_absolute():
        raise RunnerHold("HOLD_MIXED_SOURCE_PATH_UNTRUSTED")
    try:
        path = supplied.resolve(strict=True)
        root = (state_dir / "mixed-preflight" / "cohorts").resolve(strict=True)
        relative = path.relative_to(root)
    except (OSError, ValueError, RuntimeError) as exc:
        raise RunnerHold("HOLD_MIXED_SOURCE_PATH_UNTRUSTED") from exc
    repository = str(job.get("source_repository", ""))
    sha = str(job.get("source_sha", ""))
    if (path != supplied or not path.is_dir()
            or len(relative.parts) != 4
            or re.fullmatch(r"[0-9a-f]{24}", relative.parts[0]) is None
            or relative.parts[1] != "sources"
            or relative.parts[2] != repository.split("/")[-1]
            or relative.parts[3] != sha[:12]
            or re.fullmatch(r"[0-9a-f]{40}", sha) is None):
        raise RunnerHold("HOLD_MIXED_SOURCE_PATH_UNTRUSTED")
    return path


def preflight_mixed_local(args) -> dict:
    """Windows-only exact-source/EXE preflight for a mixed PRE/POST APP queue.

    A POST job is GitHub-verified and deliberately skipped. PRE jobs receive
    exact local source and Artifact verification but NO browser, Identity
    capture, CAS, submission draft, or Task Scheduler registration. This
    preflight does not mutate the central ledger or grant local E2E PASS.
    """
    prerequisite = check_prerequisites(args.provisioner_root.resolve())
    snapshot = fetch_central()
    ledger, central_head, _ = snapshot
    audit = audit_queue_only(args, central_snapshot=snapshot)
    plan = rotation_plan.build_dispatch_plan(ledger, audit)
    pending = [p for p in plan["products"]
               if p["dispatch_action"] ==
               "LOCAL_OPERATOR_PENDING_REVIEWED_MIXED_RUNNER"]
    jobs = (ledger.get("rotation_cohorts") or {}).get("app_jobs", [])
    by_slug = {job["slug"]: job for job in jobs}
    if len(by_slug) != 4:
        raise RunnerHold("HOLD_MIXED_LOCAL_DISCOVERY")
    # The same lock used by the legacy runner prevents simultaneous local
    # source/Artifact work. Keep a separate preflight manifest so a former
    # four-PRE manifest cannot be mistaken for the current three-PRE cohort.
    with batch.state_lock(args.state_dir.resolve() / "batch-state.json"):
        recheck_central(central_head)
        if not pending:
            return {
                "status": "MIXED_LOCAL_NO_IDENTITY_WORK",
                "central_head_sha": central_head,
                "post_identity_skip_count": 4,
                "pre_identity_preflight_count": 0,
                "local_windows_no_llm_pass": False,
                "task_scheduler_registration_allowed": False,
                "store_submission": "NOT_PERFORMED",
                **prerequisite,
            }
        ready = []
        for item in pending:
            job = by_slug[item["slug"]]
            if any(job.get(k) != item.get(k) for k in (
                    "request_id", "slug", "source_repository", "source_branch",
                    "source_sha", "identity_return_target", "registration_type",
                    "partner_center_selection")):
                raise RunnerHold("HOLD_MIXED_LOCAL_BINDING_CONFLICT")
            if live_branch_head(job["source_repository"], job["source_branch"]) != job["source_sha"]:
                raise RunnerHold("HOLD_CANONICAL_PRODUCT_REVISION_MISMATCH")
            artifact = gh_json(
                f"repos/{job['source_repository']}/actions/artifacts/{job['factory_artifact_id']}"
            )
            if (artifact is None or artifact.get("expired") is not False
                    or artifact.get("name") != job.get("factory_artifact_name")
                    or artifact.get("digest") !=
                    "sha256:" + str(job.get("factory_artifact_zip_sha256", ""))
                    or job.get("factory_build_head") != job["source_sha"]
                    or job.get("artifact_metadata_verified") is not True):
                raise RunnerHold("HOLD_ARTIFACT_MISMATCH")
            # GitHub's expired=false flag can lag the actual UTC deadline.
            # Validate both recorded and live expiry before source sync or ZIP IO.
            try:
                artifact_expiry.validate(job, artifact)
            except artifact_expiry.ExpiryHold as exc:
                raise RunnerHold(exc.code) from exc
            ready.append(job)
        isolated = mixed_preflight_root(args.state_dir, pending)
        isolated.mkdir(parents=True, exist_ok=True)
        sync_receipt = sync_sources(ready, isolated)
        if (sync_receipt.get("status") != "PASS"
                or sync_receipt.get("exact_sha_verified") is not True):
            raise RunnerHold("HOLD_LOCAL_SOURCE_SYNC")
        verified = []
        for item, job in zip(pending, ready):
            prepared = operator.prepare(
                ledger, sync_receipt, isolated / "sources", job["slug"],
                central_repository=batch.CENTRAL_REPOSITORY,
                central_branch=batch.CENTRAL_BRANCH,
                central_head_sha=central_head,
                batch=None,
            )
            if (prepared.get("request_id") != job["request_id"]
                    or prepared.get("source_snapshot_head") != job["source_sha"]
                    or prepared.get("queue_job_digest") !=
                    operator.canonical_digest(job)):
                raise RunnerHold("HOLD_MIXED_LOCAL_BINDING_CONFLICT")
            artifact = verify_artifact(job, isolated / "artifacts")
            if live_branch_head(job["source_repository"], job["source_branch"]) != job["source_sha"]:
                raise RunnerHold("HOLD_CANONICAL_PRODUCT_REVISION_MISMATCH")
            verified.append({
                "batch_index": item["batch_index"],
                "slug": job["slug"], "request_id": job["request_id"],
                "source_sha": job["source_sha"],
                "source_snapshot_status": prepared["source_snapshot_status"],
                "source_snapshot_head": prepared["source_snapshot_head"],
                "queue_job_digest": prepared["queue_job_digest"],
                "artifact_id": artifact["artifact_id"],
                "exe_sha256": artifact["exe_sha256"],
                "exe_bytes": artifact["exe_bytes"],
                "identity_return_target": job["identity_return_target"],
                "identity_capture": "NOT_PERFORMED",
                "github_return": "NOT_PERFORMED",
            })
        recheck_central(central_head)
    return {
        "status": "MIXED_LOCAL_PRECHECK_PASS",
        "central_head_sha": central_head,
        "discovered_count": 4,
        "post_identity_skip_count": plan["post_identity_skip_count"],
        "pre_identity_preflight_count": len(verified),
        "preflight_namespace": str(isolated),
        "products": verified,
        "mixed_state_local_runner_ready": False,
        "local_windows_no_llm_pass": False,
        "multi_product_identity_batch_pass": False,
        "task_scheduler_registration_allowed": False,
        "partner_center": "NOT_OPENED",
        "cas": "NOT_PERFORMED",
        "store_submission": "NOT_PERFORMED",
        "next_action": "REVIEW_MIXED_STATE_RESUMABLE_EXECUTION_RUNNER",
        **prerequisite,
    }




def verify_mixed_local_return(old_entry: dict, result: dict, fresh_entry: dict,
                              ledger: dict, state_dir: Path, central_head: str,
                              driver: PartnerCenterDriver) -> bool:
    """Independently recheck a completed mixed return against UI and GitHub.

    Local JSON alone cannot authenticate a Store Identity or CAS. The caller
    must hold the shared OS lock and supply a live authenticated Edge driver.
    This is a *read-only* verifier: it never creates a product or applies CAS.
    """
    try:
        jobs = (ledger.get("rotation_cohorts") or {}).get("app_jobs", [])
        matching = [j for j in jobs if j.get("slug") == old_entry.get("slug")]
        if len(matching) != 1:
            return False
        job = matching[0]
        if (old_entry.get("request_id") != job.get("request_id")
                or old_entry.get("source_sha") != job.get("source_sha")
                or old_entry.get("identity_return_target") !=
                    job.get("identity_return_target")
                or result.get("request_id") != old_entry.get("request_id")
                or result.get("source_sha") != old_entry.get("source_sha")
                or result.get("plan_job_digest") !=
                    old_entry.get("plan_job_digest")
                or fresh_entry.get("request_id") != old_entry.get("request_id")
                or fresh_entry.get("source_sha") != old_entry.get("source_sha")
                or fresh_entry.get("identity_return_target") !=
                    old_entry.get("identity_return_target")
                or fresh_entry.get("status") not in {
                    "PENDING", "SKIPPED_GITHUB_POST_VERIFIED",
                    "IDENTITY_RETURN_VERIFIED"
                }):
            return False
        receipt_path = (state_dir / "products" / job["request_id"] /
                        "official-identity.json")
        receipt = operator.read_json(receipt_path, 64_000)
        for key in ("request_id", "slug", "source_sha",
                    "source_repository", "source_branch",
                    "identity_return_target"):
            if receipt.get(key) != job.get(key):
                return False
        if (receipt.get("queue_job_digest") != result.get("queue_job_digest")
                or result.get("store_id") != receipt.get("store_id")
                or result.get("pfn") != receipt.get("package_family_name")
                or result.get("package_sid") != receipt.get("package_sid")
                or result.get("identity_return_commit_sha") !=
                    job.get("identity_return_commit_sha")
                    and fresh_entry.get("status") ==
                        "SKIPPED_GITHUB_POST_VERIFIED"):
            return False
        observation = existing_observation(driver, receipt)
        if driver.verify_current(observation, receipt) is not True:
            return False
        source_path = validated_mixed_source_path(state_dir, receipt, job)
        return github_result_verified(
            job, receipt, result["identity_return_commit_sha"],
            central_head, source_path
        )
    except (OSError, KeyError, ValueError, RunnerHold, operator.OperatorHold,
            PartnerCenterHold):
        return False


def prepare_mixed_resume_state(args, *, verify_local_returns: bool = False) -> dict:
    """Persist a verified mixed PRE/POST resume contract, without UI or CAS.

    This is intentionally a pre-execution gate, not the executable mixed
    Partner Center worker.  The existing exact-source/EXE preflight runs
    under the same OS lock first; a second locked phase rejects queue drift
    before persisting a restart-safe state.  Persisted success cannot be
    replayed without an independent UI+GitHub verifier, so this mode never
    silently upgrades a local JSON receipt into PASS.
    """
    preflight = preflight_mixed_local(args)
    if preflight.get("status") not in {
            "MIXED_LOCAL_PRECHECK_PASS", "MIXED_LOCAL_NO_IDENTITY_WORK"}:
        raise RunnerHold("HOLD_MIXED_RESUME_PREFLIGHT")
    snapshot = fetch_central()
    ledger, central_head, _ = snapshot
    if preflight.get("central_head_sha") != central_head:
        raise RunnerHold("HOLD_MIXED_RESUME_CENTRAL_DRIFT")
    audit = audit_queue_only(args, central_snapshot=snapshot)
    plan = rotation_plan.build_dispatch_plan(ledger, audit)
    expected = mixed_resume.initialize(
        plan, central_head_sha=central_head,
        execution_origin=args.execution_origin,
    )
    pending = [item for item in plan["products"]
               if item["dispatch_action"] == mixed_resume.PRE_ACTION]
    verified = preflight.get("products", [])
    if not isinstance(verified, list) or len(verified) != len(pending):
        raise RunnerHold("HOLD_MIXED_RESUME_PREFLIGHT_COUNT")
    jobs = (ledger.get("rotation_cohorts") or {}).get("app_jobs")
    if not isinstance(jobs, list) or len(jobs) != 4:
        raise RunnerHold("HOLD_MIXED_RESUME_DISCOVERY")
    by_slug = {item.get("slug"): item for item in jobs}
    if len(by_slug) != 4:
        raise RunnerHold("HOLD_MIXED_RESUME_DISCOVERY")
    for planned, proof in zip(pending, verified):
        job = by_slug.get(planned["slug"])
        if not isinstance(job, dict):
            raise RunnerHold("HOLD_MIXED_RESUME_PREFLIGHT_BINDING")
        required = (
            proof.get("batch_index") == planned["batch_index"]
            and proof.get("slug") == planned["slug"]
            and proof.get("request_id") == planned["request_id"]
            and proof.get("source_sha") == planned["source_sha"]
            and proof.get("source_snapshot_head") == planned["source_sha"]
            and proof.get("identity_return_target") ==
                planned["identity_return_target"]
            and proof.get("queue_job_digest") == operator.canonical_digest(job)
            and proof.get("exe_sha256") == job.get("expected_exe_sha256")
            and proof.get("identity_capture") == "NOT_PERFORMED"
            and proof.get("github_return") == "NOT_PERFORMED"
        )
        if not required:
            raise RunnerHold("HOLD_MIXED_RESUME_PREFLIGHT_BINDING")
    state_dir = args.state_dir.resolve()
    state_path = state_dir / "mixed-resume-state.json"
    rebase_applied = False
    with batch.state_lock(state_dir / "batch-state.json"):
        recheck_central(central_head)
        for item in pending:
            if live_branch_head(item["source_repository"],
                                item["source_branch"]) != item["source_sha"]:
                raise RunnerHold("HOLD_CANONICAL_PRODUCT_REVISION_MISMATCH")
        ui_rechecked = False
        if state_path.exists():
            state = operator.read_json(state_path, 512_000)
            needs_ui = any(
                item.get("status") == "IDENTITY_RETURN_VERIFIED"
                for item in state.get("products", [])
                if isinstance(item, dict)
            )
            driver = PartnerCenterDriver() if verify_local_returns and needs_ui else None
            try:
                def verified_return(old, result, fresh):
                    if driver is None:
                        return False
                    return verify_mixed_local_return(
                        old, result, fresh, ledger, state_dir, central_head, driver
                    )
                if state.get("central_head_sha") != central_head:
                    # The central single writer may advance HEAD. Only a
                    # fresh authenticated UI+GitHub check may rebase a local
                    # return; the default preparation mode fails closed.
                    state = mixed_rebase.rebase_after_reconciliation(
                        state, plan, new_central_head_sha=central_head,
                        execution_origin=args.execution_origin,
                        independent_return_verifier=verified_return if driver else None,
                    )
                    recheck_central(central_head)
                    batch.atomic_write(state_path, state)
                    rebase_applied = True
                else:
                    mixed_resume.validate_replay(
                        state, expected,
                        verified_result_verifier=(
                            lambda old, result: verified_return(old, result, old)
                        ) if driver else None,
                    )
                ui_rechecked = driver is not None
            finally:
                if driver is not None:
                    driver.close()
        else:
            batch.atomic_write(state_path, expected)
            state = expected
    result = mixed_resume.summary(state)
    return {
        **result,
        "status": "MIXED_RESUME_STATE_PREPARED",
        "central_head_sha": central_head,
        "state_path": str(state_path),
        "central_rebase_applied": rebase_applied,
        "independent_ui_github_return_rechecked": ui_rechecked,
        "pre_identity_preflight_count": len(verified),
        "post_identity_skip_count": plan["post_identity_skip_count"],
        "local_windows_no_llm_pass": False,
        "multi_product_identity_batch_pass": False,
        "task_scheduler_registration_allowed": False,
        "partner_center": ("READ_ONLY_AUTHENTICATED_UI_RECHECK" if ui_rechecked
                           else "NOT_OPENED"),
        "identity_capture": "NOT_PERFORMED",
        "cas": "NOT_PERFORMED",
        "store_submission": "NOT_PERFORMED",
        "next_action": "REVIEW_AND_WIRE_AUTHENTICATED_MIXED_EXECUTOR",
    }


def preflight_only(args) -> dict:
    """Read-only live queue gate for task registration, never host proof.

    Do not create local state, download EXEs, sync sources, open a browser,
    apply Identity CAS, or infer a scheduled 36-minute trigger here.
    """
    prerequisite = check_prerequisites(args.provisioner_root.resolve())
    ledger, central_head, _ = fetch_central()
    spec, jobs = validate_queue(ledger, central_head, args.execution_origin)
    recheck_central(central_head)
    state = batch.discover(ledger, spec)
    recheck_central(central_head)
    return {
        "status": "BATCH_PREFLIGHT_READY",
        "discovered_count": state["discovered_count"],
        "central_head_sha": central_head,
        "execution_trigger_proven": False,
        "local_execution": "NOT_PERFORMED",
        "identity_capture": "NOT_PERFORMED",
        "cas": "NOT_PERFORMED",
        "store_submission": "NOT_PERFORMED",
        "source_snapshots": "NOT_VERIFIED_ON_LOCAL_PC",
        "artifact_bytes": "NOT_DOWNLOADED",
        **prerequisite,
    }


def run_batch(args) -> dict:
    state_dir = args.state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    prerequisite = check_prerequisites(args.provisioner_root.resolve())
    ledger, central_head, central_blob = fetch_central()
    state_path = state_dir / "batch-state.json"
    final_path = state_dir / "final-batch-receipt.json"
    # A manually started scheduled task leaves a one-shot marker. Do not
    # consume that marker until the OS single-flight lock is held: a
    # competing runner must not steal the real task's execution origin.
    # The lock also protects local source/Artifact IO, browser and CAS.
    with batch.state_lock(state_path):
        execution_origin = resolve_execution_origin(args.execution_origin, state_dir)
        spec, jobs = validate_queue(ledger, central_head, execution_origin)
        recheck_central(central_head)
        # Reject expired or malformed Factory artifacts before local sync,
        # ZIP download, browser interaction or CAS.
        preflight_state = batch.discover(ledger, spec)
        if state_path.exists():
            state = operator.read_json(state_path, 512_000)
            already_complete = validate_existing_state(
                state, spec, central_head, execution_origin
            )
        else:
            state = preflight_state
            already_complete = False
        if already_complete:
            # A terminal batch must never re-download, re-open the browser,
            # or turn a terminal PARTIAL state into a no-work PASS.
            if not final_path.is_file():
                raise RunnerHold("HOLD_FINAL_BATCH_RECEIPT_MISSING")
            final_receipt = operator.read_json(final_path, 256_000)
            if (final_receipt.get("batch_status") != state["final_status"]
                    or final_receipt.get("central_head_sha") != central_head):
                raise RunnerHold("HOLD_FINAL_BATCH_RECEIPT_CONFLICT")
            return {
                "status": state["final_status"], "discovered": 4,
                "processed": state["processed_count"],
                "success": state["success_count"],
                "hold": state["hold_count"],
                "receipt": str(final_path),
                "execution_origin": execution_origin,
            }

        recheck_central(central_head)
        sync_receipt = sync_sources(jobs, state_dir)
        artifacts = {
            job["slug"]: verify_artifact(job, state_dir / "artifacts")
            for job in jobs
        }
        recheck_central(central_head)
        if not state_path.exists():
            # Do not create resumable state until the local source/Artifact
            # bytes have been independently verified. The lock stays held.
            # Windows presence or a claimed execution origin never proves
            # the saved ChatGPT 36-minute scheduled trigger.
            batch.atomic_write(state_path, state)

        provisioner, provisioner_core = import_provisioner(args.provisioner_root.resolve())
        config = provisioner_core.ProductConfig.load(args.provisioner_root / "config.json")
        driver = PartnerCenterDriver()
        try:
            while state.get("processed_count") < 4:
                state, claimed = batch.claim_or_resume(state)
                batch.atomic_write(state_path, state)
                recheck_central(central_head)
                if live_branch_head(claimed["source_repository"], claimed["source_branch"]) != claimed["source_sha"]:
                    existing = gh_json(
                        f"repos/{claimed['source_repository']}/contents/{claimed['identity_return_target']}"
                        f"?ref={claimed['source_branch']}", allow_missing=True,
                    )
                    if existing is None:
                        raise RunnerHold("HOLD_CANONICAL_PRODUCT_REVISION_MISMATCH")
                batch_meta = {
                    "batch_id": state["batch_id"],
                    "batch_index": claimed["batch_index"], "batch_total": 4,
                    "trigger_origin": batch.TRIGGER_ORIGIN,
                    "dispatch_origin": batch.DISPATCH_ORIGIN,
                    "execution_origin": execution_origin,
                    "automation_id": batch.AUTOMATION_ID,
                }
                operator_job = operator.prepare(
                    ledger, sync_receipt, state_dir / "sources", claimed["slug"],
                    central_repository=batch.CENTRAL_REPOSITORY,
                    central_branch=batch.CENTRAL_BRANCH,
                    central_head_sha=central_head,
                    batch=batch_meta,
                )
                product_dir = state_dir / "products" / claimed["request_id"]
                job_path = product_dir / "operator-job.json"
                receipt_path = product_dir / "official-identity.json"
                write_once(job_path, operator_job)
                if receipt_path.exists():
                    receipt = operator.read_json(receipt_path, 64_000)
                    observation = existing_observation(driver, receipt)
                else:
                    try:
                        captured, observation = driver.process(operator_job)
                    except PartnerCenterHold as exc:
                        # Only a confirmed unavailable name (before Reserve)
                        # is safe to skip. Auth/MFA/uncertain creation stop all.
                        if str(exc) != "HOLD_NAME_UNAVAILABLE":
                            raise
                        state = complete_name_unavailable(
                            state, claimed, product_dir,
                            operator_job["source_snapshot_status"],
                        )
                        continue
                    receipt = operator.validate_capture(operator_job, captured)
                    write_once(receipt_path, receipt)

                recheck_central(central_head)
                source_path = (state_dir / "sources" /
                               claimed["source_repository"].split("/", 1)[1] /
                               claimed["source_sha"][:12])

                def ui_verifier(candidate, job_object, queue_job):
                    return (
                        candidate.get("request_id") == claimed["request_id"]
                        and queue_job.get("source_sha") == claimed["source_sha"]
                        and driver.verify_current(observation, candidate)
                    )

                first = provisioner.run_identity_return(
                    ledger=ledger, operator_job=operator_job,
                    receipt_path=receipt_path, config=config, apply=True,
                    independent_ui_verifier=ui_verifier,
                )
                if first.get("status") not in {"APPLIED", "EXISTING_VERIFIED"}:
                    raise RunnerHold("HOLD_CAS_CONTRACT_BROKEN")
                replay = provisioner.run_identity_return(
                    ledger=ledger, operator_job=operator_job,
                    receipt_path=receipt_path, config=config, apply=True,
                    independent_ui_verifier=ui_verifier,
                )
                if replay.get("status") != "EXISTING_VERIFIED":
                    raise RunnerHold("HOLD_CAS_CONTRACT_BROKEN")
                commit_sha = replay.get("github_return", {}).get("commit_sha")
                if not isinstance(commit_sha, str):
                    raise RunnerHold("HOLD_CAS_CONTRACT_BROKEN")

                result = {
                    "batch_id": state["batch_id"], "batch_index": claimed["batch_index"],
                    "request_id": claimed["request_id"], "slug": claimed["slug"],
                    "source_sha": claimed["source_sha"],
                    "source_snapshot_head": claimed["source_sha"],
                    "identity_return_target": claimed["identity_return_target"],
                    "registration_type": claimed["registration_type"],
                    "partner_center_selection": claimed["partner_center_selection"],
                    "queue_job_digest": claimed["queue_job_digest"],
                    "central_head_sha": central_head,
                    "source_sync_status": operator_job["source_snapshot_status"],
                    "partner_center_search_count": observation.initial_search_count,
                    "creation_status": receipt["creation_status"],
                    "overview_exact_match_count": 1,
                    "identity_capture_status": "IDENTITY_CAPTURED__AUTHENTICATED_UI__GITHUB_BOUND",
                    "authenticated_partner_center_pass": True,
                    "identity_details_observed": True,
                    "store_id": receipt["store_id"],
                    "identity_name": receipt["identity_name"],
                    "pfn": receipt["package_family_name"],
                    "package_sid": receipt["package_sid"],
                    "github_return_status": first["status"],
                    "github_replay_status": replay["status"],
                    "identity_return_commit_sha": commit_sha,
                    "package_version_gate": "HOLD",
                    "store_submission": "NOT_PERFORMED",
                    "cross_product_contamination": 0,
                    "duplicate_creation": 0,
                    "dispatch_origin": batch.DISPATCH_ORIGIN,
                    "execution_origin": execution_origin,
                    "artifact": artifacts[claimed["slug"]],
                }

                def evidence_verifier(**kw):
                    return (
                        kw["job"]["request_id"] == claimed["request_id"]
                        and driver.verify_current(observation, receipt)
                        and github_result_verified(
                            claimed, receipt, commit_sha, central_head, source_path
                        )
                    )

                state = batch.complete_active(
                    state, result, independent_evidence_verifier=evidence_verifier
                )
                batch.atomic_write(state_path, state)
                write_once(product_dir / "result.json", result)
        finally:
            driver.close()

        schedule_proven = state.get("execution_trigger_proven") is True
        batch_pass = state.get("final_status") == "MULTI_PRODUCT_IDENTITY_BATCH_PASS"
        # A successful manual 4/4 Identity return is still PARTIAL until the
        # independently proven scheduled-host trigger gate has passed.
        products = []
        for job in state["products"]:
            result = job.get("result") or {}
            products.append({
                "batch_index": job["batch_index"],
                "product": job["display_name"],
                "slug": job["slug"],
                "request_id": job["request_id"],
                "source_sha": job["source_sha"],
                "source_sync_status": result.get("source_sync_status", "NOT_RUN"),
                "partner_center_search_count": result.get("partner_center_search_count"),
                "creation_status": result.get("creation_status", "HOLD"),
                "registration_type": job["registration_type"],
                "partner_center_selection": job["partner_center_selection"],
                "identity_capture_status": result.get("identity_capture_status", "NOT_RUN"),
                "store_id": result.get("store_id"),
                "identity_name": result.get("identity_name"),
                "pfn": result.get("pfn"),
                "package_sid": result.get("package_sid"),
                "github_return_status": result.get("github_return_status", "NOT_RUN"),
                "identity_return_commit_sha": result.get("identity_return_commit_sha"),
                "package_version_gate": "HOLD",
                "store_submission": "NOT_PERFORMED",
                "error_code": result.get("error_code"),
            })
        completed_at = utc_now()
        final = {
            "schema_version": 1,
            "batch_id": state["batch_id"],
            "trigger_origin": batch.TRIGGER_ORIGIN,
            "automation_id": batch.AUTOMATION_ID,
            "started_at": state["scheduled_at"],
            "completed_at": completed_at,
            "batch_total": 4,
            "status": ("LOCAL_WINDOWS_NO_LLM_AUTOMATION_PASS" if batch_pass
                       else "MULTI_PRODUCT_IDENTITY_BATCH_PARTIAL"),
            "batch_status": state["final_status"],
            "dispatch_origin": batch.DISPATCH_ORIGIN,
            "execution_origin": execution_origin,
            "central_repository": batch.CENTRAL_REPOSITORY,
            "central_branch": batch.CENTRAL_BRANCH,
            "central_head_sha": central_head,
            "central_blob_sha": central_blob,
            "fetched_at": spec["scheduled_at"],
            "discovered_count": 4,
            "processed_count": state["processed_count"],
            "success_count": state["success_count"],
            "hold_count": state["hold_count"],
            "next_resume_index": state["next_resume_index"],
            "schedule_trigger_proven": schedule_proven,
            "products": products,
            "identity_captured": sum(
                p["identity_capture_status"] ==
                "IDENTITY_CAPTURED__AUTHENTICATED_UI__GITHUB_BOUND"
                for p in products
            ),
            "github_return": sum(
                p["github_return_status"] in {"APPLIED", "EXISTING_VERIFIED"}
                for p in products
            ),
            "replay": state["success_count"],
            "duplicate_creation": state["duplicate_creation"],
            "cross_product_contamination": state["cross_product_contamination"],
            "store_submission": "NOT_PERFORMED",
            "ollama": "NOT_USED", "openai_api": "NOT_USED",
            **prerequisite,
            "finished_at": completed_at,
        }
        write_once(final_path, final)
        return final


def main(argv: list[str] | None = None) -> int:
    default_state = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / (
        "WindowsAllAuto/PartnerCenterBatch"
    )
    default_provisioner = Path(__file__).resolve().parents[2] / "provisioner-app-ui-attestation"
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", type=Path, default=default_state)
    parser.add_argument("--provisioner-root", type=Path, default=default_provisioner)
    parser.add_argument("--execution-origin", choices=sorted(EXECUTION_ORIGINS),
                        default="MANUAL_WINDOWS_TERMINAL")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--audit-queue", action="store_true")
    parser.add_argument("--plan-queue", action="store_true")
    parser.add_argument("--mixed-local-preflight", action="store_true")
    parser.add_argument("--prepare-mixed-resume", action="store_true")
    parser.add_argument("--verify-mixed-rebase-ui", action="store_true")
    args = parser.parse_args(argv)
    try:
        if sum((args.audit_queue, args.plan_queue, args.preflight_only,
                args.mixed_local_preflight, args.prepare_mixed_resume,
                args.verify_mixed_rebase_ui)) > 1:
            raise RunnerHold("HOLD_CONFLICTING_READ_ONLY_MODES")
        result = (audit_queue_only(args) if args.audit_queue else
                  plan_queue_only(args) if args.plan_queue else
                  preflight_mixed_local(args) if args.mixed_local_preflight else
                  prepare_mixed_resume_state(
                      args, verify_local_returns=args.verify_mixed_rebase_ui
                  ) if (args.prepare_mixed_resume or args.verify_mixed_rebase_ui) else
                  preflight_only(args) if args.preflight_only else run_batch(args))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") in {
            "LOCAL_WINDOWS_NO_LLM_AUTOMATION_PASS", "BATCH_PREFLIGHT_READY",
            "MIXED_ROTATION_AUDITED", "MIXED_ROTATION_DISPATCH_PLAN_READY",
            "MIXED_LOCAL_PRECHECK_PASS", "MIXED_LOCAL_NO_IDENTITY_WORK",
            "MIXED_RESUME_STATE_PREPARED"
        } else 2
    except (RunnerHold, rotation_audit.AuditHold, rotation_plan.PlanHold,
            mixed_resume.MixedResumeHold, mixed_rebase.RebaseHold,
            batch.BatchHold, operator.OperatorHold,
            local_code_sync.SyncHold, PartnerCenterHold) as exc:
        code = exc.code if isinstance(exc, RunnerHold) else str(exc)
        result = {
            "status": "HOLD", "reason": code,
            "dispatch_origin": batch.DISPATCH_ORIGIN,
            "execution_origin": args.execution_origin,
            "store_submission": "NOT_PERFORMED",
            "ollama": "NOT_USED", "openai_api": "NOT_USED",
        }
        if not (args.audit_queue or args.plan_queue):
            try:
                args.state_dir.mkdir(parents=True, exist_ok=True)
                (args.state_dir / "last-hold-receipt.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            except OSError:
                pass
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
