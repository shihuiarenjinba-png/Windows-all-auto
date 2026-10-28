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


def run_batch(args) -> dict:
    state_dir = args.state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    execution_origin = resolve_execution_origin(args.execution_origin, state_dir)
    prerequisite = check_prerequisites(args.provisioner_root.resolve())
    ledger, central_head, central_blob = fetch_central()
    spec, jobs = validate_queue(ledger, central_head, execution_origin)
    recheck_central(central_head)

    sync_receipt = sync_sources(jobs, state_dir)
    artifacts = {job["slug"]: verify_artifact(job, state_dir / "artifacts") for job in jobs}
    recheck_central(central_head)

    state_path = state_dir / "batch-state.json"
    final_path = state_dir / "final-batch-receipt.json"
    with batch.state_lock(state_path):
        if state_path.exists():
            state = operator.read_json(state_path, 512_000)
            if (state.get("batch_id") != spec["batch_id"]
                    or state.get("central_head_sha") != central_head
                    or state.get("execution_origin") != execution_origin):
                raise RunnerHold("BATCH_EXISTING_STATE_CONFLICT")
        else:
            state = batch.discover(ledger, spec)
            state = batch.attest_local_execution(
                state, execution_origin,
                verifier=lambda **kw: (
                    os.name == "nt"
                    and kw.get("execution_origin") == execution_origin
                    and kw.get("state", {}).get("central_head_sha") == central_head
                ),
            )
            batch.atomic_write(state_path, state)
        if state.get("final_status") == "MULTI_PRODUCT_IDENTITY_BATCH_PASS":
            return {
                "status": "NO_WORK", "discovered": 4, "processed": 4,
                "success": 4, "receipt": str(final_path),
                "execution_origin": execution_origin,
            }

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
                    captured, observation = driver.process(operator_job)
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

        if state.get("final_status") != "MULTI_PRODUCT_IDENTITY_BATCH_PASS":
            raise RunnerHold("MULTI_PRODUCT_IDENTITY_BATCH_PARTIAL")
        final = {
            "schema_version": 1,
            "status": "LOCAL_WINDOWS_NO_LLM_AUTOMATION_PASS",
            "batch_status": state["final_status"],
            "dispatch_origin": batch.DISPATCH_ORIGIN,
            "execution_origin": execution_origin,
            "central_repository": batch.CENTRAL_REPOSITORY,
            "central_branch": batch.CENTRAL_BRANCH,
            "central_head_sha": central_head,
            "central_blob_sha": central_blob,
            "fetched_at": spec["scheduled_at"],
            "discovered": 4, "processed": 4, "identity_captured": 4,
            "github_return": 4, "replay": 4,
            "duplicate_creation": state["duplicate_creation"],
            "cross_product_contamination": state["cross_product_contamination"],
            "store_submission": "NOT_PERFORMED",
            "ollama": "NOT_USED", "openai_api": "NOT_USED",
            **prerequisite,
            "finished_at": utc_now(),
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
    args = parser.parse_args(argv)
    try:
        result = run_batch(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (RunnerHold, batch.BatchHold, operator.OperatorHold,
            local_code_sync.SyncHold, PartnerCenterHold) as exc:
        code = exc.code if isinstance(exc, RunnerHold) else str(exc)
        result = {
            "status": "HOLD", "reason": code,
            "dispatch_origin": batch.DISPATCH_ORIGIN,
            "execution_origin": args.execution_origin,
            "store_submission": "NOT_PERFORMED",
            "ollama": "NOT_USED", "openai_api": "NOT_USED",
        }
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
