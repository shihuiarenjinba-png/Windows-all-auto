"""Fail-closed four-product Partner Center Identity batch contract.

The module discovers an explicit ordered batch from the GitHub-owned central
ledger.  It never performs browser actions, Store submission, package upload,
or GitHub CAS.  A scheduled local worker may use the durable state transitions
to process exactly one product at a time and resume after interruption.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys

from scripts import local_partner_center_operator as operator

AUTOMATION_ID = "6adf4b1e7654819193b997fb4fb83c85"
TRIGGER_ORIGIN = "SCHEDULED_36_MIN_LOOP"
CENTRAL_REPOSITORY = "shihuiarenjinba-png/Windows-all-auto"
CENTRAL_BRANCH = "codex/e2e-belt-connection-20261027"
TOTAL = 4
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA64 = re.compile(r"[0-9a-f]{64}")
SPEC_KEYS = {
    "schema_version", "batch_id", "trigger_origin", "automation_id",
    "central_repository", "central_branch", "central_head_sha",
    "scheduled_at", "products",
}
PRODUCT_KEYS = {
    "batch_index", "request_id", "slug", "source_sha", "artifact_id",
    "expected_exe_sha256", "identity_return_target",
}


class BatchHold(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise BatchHold(code)


def _iso(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _validate_spec(spec: dict) -> list[dict]:
    require(set(spec) == SPEC_KEYS, "BATCH_TRIGGER_RECEIPT_SCHEMA_INVALID")
    require(spec.get("schema_version") == 1, "BATCH_SCHEMA_UNSUPPORTED")
    require(spec.get("trigger_origin") == TRIGGER_ORIGIN
            and spec.get("automation_id") == AUTOMATION_ID,
            "BATCH_SCHEDULE_TRIGGER_NOT_PROVEN")
    require(spec.get("central_repository") == CENTRAL_REPOSITORY
            and spec.get("central_branch") == CENTRAL_BRANCH
            and SHA40.fullmatch(str(spec.get("central_head_sha", ""))) is not None
            and _iso(spec.get("scheduled_at")),
            "BATCH_SCHEDULE_TRIGGER_NOT_PROVEN")
    products = spec.get("products")
    require(isinstance(products, list) and len(products) == TOTAL,
            "HOLD_BATCH_DISCOVERY_INCOMPLETE")
    for item in products:
        require(isinstance(item, dict) and set(item) == PRODUCT_KEYS,
                "BATCH_PRODUCT_SPEC_INVALID")
        require(SHA40.fullmatch(str(item.get("source_sha", ""))) is not None
                and SHA64.fullmatch(str(item.get("expected_exe_sha256", ""))) is not None
                and type(item.get("artifact_id")) is int and item["artifact_id"] > 0,
                "BATCH_PRODUCT_SPEC_INVALID")
        require(item.get("identity_return_target") ==
                f"products/{item.get('slug')}/store/approved-identity.json",
                "WRONG_IDENTITY_RETURN_TARGET")
    require([x["batch_index"] for x in products] == list(range(1, TOTAL + 1)),
            "BATCH_ORDER_INVALID")
    for field in ("request_id", "slug", "source_sha", "identity_return_target"):
        require(len({x[field] for x in products}) == TOTAL,
                "CROSS_PRODUCT_DUPLICATE_" + field.upper())
    return products


def discover(ledger: dict, spec: dict) -> dict:
    expected = _validate_spec(spec)
    cohorts = (ledger.get("rotation_cohorts") or {}).get("app_jobs")
    require(isinstance(cohorts, list), "HOLD_BATCH_DISCOVERY_INCOMPLETE")
    ready = [x for x in cohorts if isinstance(x, dict)
             and x.get("status") == "PRE_IDENTITY_READY"]
    expected_slugs = [x["slug"] for x in expected]
    ready_slugs = [x.get("slug") for x in ready]
    if len(ready) < TOTAL or any(slug not in ready_slugs for slug in expected_slugs):
        raise BatchHold("HOLD_BATCH_DISCOVERY_INCOMPLETE")
    require(len(ready) == TOTAL and set(ready_slugs) == set(expected_slugs),
            "HOLD_BATCH_SCOPE_CONFLICT")
    jobs = []
    for wanted in expected:
        job = operator.expected_job(ledger, wanted["slug"])
        source = next(x for x in ready if x.get("slug") == wanted["slug"])
        checks = {
            "request_id": wanted["request_id"], "slug": wanted["slug"],
            "source_sha": wanted["source_sha"], "product_type": "APP",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "identity_return_target": wanted["identity_return_target"],
        }
        require(all(job.get(key) == value for key, value in checks.items()),
                "CROSS_PRODUCT_OR_SOURCE_BINDING_CONFLICT")
        require(source.get("factory_artifact_id") == wanted["artifact_id"]
                and source.get("expected_exe_sha256") == wanted["expected_exe_sha256"]
                and source.get("factory_build_head") == wanted["source_sha"]
                and source.get("artifact_metadata_verified") is True,
                "HOLD_ARTIFACT_MISMATCH")
        jobs.append({
            **job,
            "batch_index": wanted["batch_index"],
            "artifact_id": wanted["artifact_id"],
            "expected_exe_sha256": wanted["expected_exe_sha256"],
            "state": "PENDING",
            "result": None,
        })
    return {
        "schema_version": 1,
        "batch_id": spec["batch_id"],
        "trigger_origin": TRIGGER_ORIGIN,
        "automation_id": AUTOMATION_ID,
        "central_repository": CENTRAL_REPOSITORY,
        "central_branch": CENTRAL_BRANCH,
        "central_head_sha": spec["central_head_sha"],
        "scheduled_at": spec["scheduled_at"],
        "schedule_trigger_proven": False,  # metadata alone is not host attestation
        "batch_total": TOTAL,
        "discovered_count": TOTAL,
        "processed_count": 0,
        "success_count": 0,
        "hold_count": 0,
        "active_index": None,
        "next_resume_index": 1,
        "products": jobs,
        "cross_product_contamination": 0,
        "duplicate_creation": 0,
        "store_submission": 0,
        "final_status": "BATCH_DISCOVERED",
    }


# A status string alone is never proof of an Identity capture or a GitHub CAS.
# These fields are local, independently corroborated evidence requirements.
PRODUCT_LEVEL_HOLDS = {
    "HOLD_NAME_UNAVAILABLE", "HOLD_PRODUCT_JOB_INVALID",
    "HOLD_ARTIFACT_MISMATCH", "HOLD_SOURCE_HEAD_DRIFT",
    "HOLD_LOCAL_SOURCE_SYNC", "HOLD_PRODUCT_CREATE_NOT_CONFIRMED",
    "HOLD_LOCAL_CAPACITY",
}
GLOBAL_STOP_CODES = {
    "HOLD_PARTNER_CENTER_AUTH_REQUIRED", "HOLD_MFA_REQUIRED",
    "HOLD_DUPLICATE_PRODUCT", "HOLD_BROWSER_STATE_AMBIGUOUS",
    "HOLD_CAS_CONTRACT_BROKEN", "CROSS_PRODUCT_IDENTITY_CONTAMINATION",
    "HOLD_QUEUE_DIGEST_CONFLICT",
}


def _validate_success_evidence(state: dict, job: dict, result: dict) -> None:
    """Reject a fabricated APPLIED flag without the complete local evidence chain."""
    exact = {
        "batch_id": state["batch_id"],
        "batch_index": job["batch_index"],
        "request_id": job["request_id"],
        "slug": job["slug"],
        "source_sha": job["source_sha"],
        "source_snapshot_head": job["source_sha"],
        "identity_return_target": job["identity_return_target"],
        "registration_type": job["registration_type"],
        "partner_center_selection": job["partner_center_selection"],
        "queue_job_digest": job["queue_job_digest"],
        "central_head_sha": state["central_head_sha"],
        "identity_capture_status": "IDENTITY_CAPTURED__AUTHENTICATED_UI__GITHUB_BOUND",
        "github_replay_status": "EXISTING_VERIFIED",
        "package_version_gate": "HOLD",
        "store_submission": "NOT_PERFORMED",
        "cross_product_contamination": 0,
        "duplicate_creation": 0,
    }
    require(all(result.get(k) == v for k, v in exact.items()),
            "HOLD_BATCH_SUCCESS_EVIDENCE_INCOMPLETE")
    require(result.get("source_sync_status") in
            {"DOWNLOADED_EXACT_SNAPSHOT", "REUSED_EXACT_SNAPSHOT"}
            and result.get("authenticated_partner_center_pass") is True
            and result.get("identity_details_observed") is True
            and type(result.get("overview_exact_match_count")) is int
            and result["overview_exact_match_count"] == 1,
            "HOLD_BATCH_SUCCESS_EVIDENCE_INCOMPLETE")
    count = result.get("partner_center_search_count")
    created = result.get("creation_status")
    require(type(count) is int and count in (0, 1)
            and ((count == 0 and created == "CREATED")
                 or (count == 1 and created == "REUSED_EXISTING")),
            "HOLD_BATCH_PRODUCT_CREATION_NOT_PROVEN")
    require(SHA40.fullmatch(str(result.get("identity_return_commit_sha", ""))) is not None,
            "HOLD_BATCH_GITHUB_RETURN_COMMIT_NOT_PROVEN")
    require(re.fullmatch(r"[A-Za-z0-9]{8,32}", str(result.get("store_id", ""))) is not None
            and re.fullmatch(r"[A-Za-z0-9._-]+_[a-z0-9]{13}",
                             str(result.get("pfn", ""))) is not None
            and re.fullmatch(r"S-1-15-2(?:-\d+){7}",
                             str(result.get("package_sid", ""))) is not None
            and isinstance(result.get("identity_name"), str)
            and bool(result["identity_name"].strip()),
            "HOLD_BATCH_IDENTITY_SCHEMA_INVALID")


def _validate_product_hold(result: dict) -> None:
    code = result.get("error_code")
    require(result.get("github_return_status") == "HOLD"
            and isinstance(code, str)
            and code not in GLOBAL_STOP_CODES
            and code in PRODUCT_LEVEL_HOLDS,
            "HOLD_BATCH_GLOBAL_STOP_REQUIRED")


def claim_next(state: dict) -> tuple[dict, dict]:
    current = deepcopy(state)
    require(current.get("batch_total") == TOTAL
            and current.get("discovered_count") == TOTAL,
            "HOLD_BATCH_DISCOVERY_INCOMPLETE")
    require(current.get("active_index") is None
            and not any(x.get("state") == "PROCESSING" for x in current["products"]),
            "BATCH_SINGLE_FLIGHT_LOCKED")
    pending = next((x for x in current["products"] if x.get("state") == "PENDING"), None)
    require(pending is not None, "BATCH_NO_PENDING_PRODUCT")
    require(pending["batch_index"] == current.get("next_resume_index"),
            "BATCH_RESUME_INDEX_CONFLICT")
    pending["state"] = "PROCESSING"
    current["active_index"] = pending["batch_index"]
    return current, deepcopy(pending)


def complete_active(state: dict, result: dict) -> dict:
    current = deepcopy(state)
    index = current.get("active_index")
    if index is None:
        previous = [x for x in current.get("products", [])
                    if x.get("state") in {"SUCCESS", "HOLD"}
                    and x.get("result") == result]
        require(len(previous) == 1, "BATCH_NO_ACTIVE_JOB_OR_REPLAY_CONFLICT")
        return current
    active = [x for x in current.get("products", [])
              if x.get("batch_index") == index and x.get("state") == "PROCESSING"]
    require(len(active) == 1, "BATCH_ACTIVE_JOB_NOT_UNIQUE")
    job = active[0]
    for key in ("request_id", "slug", "source_sha", "identity_return_target"):
        require(result.get(key) == job.get(key), "CROSS_PRODUCT_IDENTITY_CONTAMINATION")
    status = result.get("github_return_status")
    require(status in {"APPLIED", "EXISTING_VERIFIED", "HOLD", "CONFLICT"},
            "BATCH_RESULT_STATUS_INVALID")
    require(result.get("store_submission") == "NOT_PERFORMED"
            and result.get("package_version_gate") == "HOLD",
            "BATCH_RESULT_SAFETY_CONFLICT")
    if status in {"APPLIED", "EXISTING_VERIFIED"}:
        _validate_success_evidence(current, job, result)
        job["state"] = "SUCCESS"
    elif status == "HOLD":
        _validate_product_hold(result)
        job["state"] = "HOLD"
    else:
        raise BatchHold("HOLD_BATCH_GLOBAL_STOP_REQUIRED")
    job["result"] = result
    current["active_index"] = None
    current["processed_count"] += 1
    current["success_count"] += job["state"] == "SUCCESS"
    current["hold_count"] += job["state"] == "HOLD"
    current["next_resume_index"] = index + 1 if index < TOTAL else None
    if current["processed_count"] == TOTAL:
        current["final_status"] = (
            "MULTI_PRODUCT_IDENTITY_BATCH_PASS"
            if (current["success_count"] == TOTAL
                and current.get("schedule_trigger_proven") is True)
            else "MULTI_PRODUCT_IDENTITY_BATCH_PARTIAL"
        )
    else:
        current["final_status"] = "BATCH_IN_PROGRESS"
    return current


@contextmanager
def state_lock(path: Path):
    """Nonblocking OS lock shared by discover, claim and complete.

    Windows msvcrt and POSIX flock release the lock on process termination.
    The lock file itself is intentionally retained; it is not an execution
    receipt and cannot be used as evidence of a completed product.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    if not operator._safe_path(lock_path):
        raise BatchHold("UNSAFE_BATCH_LOCK_PATH")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    locked = False
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\x00")
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise BatchHold("BATCH_SINGLE_FLIGHT_LOCKED") from exc
        yield
    finally:
        if locked:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    with temp.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--ledger", type=Path, required=True)
    d.add_argument("--scheduled-trigger", type=Path, required=True)
    d.add_argument("--state", type=Path, required=True)
    c = sub.add_parser("claim")
    c.add_argument("--state", type=Path, required=True)
    c.add_argument("--job-output", type=Path, required=True)
    f = sub.add_parser("complete")
    f.add_argument("--state", type=Path, required=True)
    f.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with state_lock(args.state):
            if args.mode == "discover":
                proposed = discover(operator.read_json(args.ledger),
                                    operator.read_json(args.scheduled_trigger, 64_000))
                if args.state.exists():
                    existing = operator.read_json(args.state, 256_000)
                    require(existing.get("batch_id") == proposed["batch_id"]
                            and existing.get("central_head_sha") == proposed["central_head_sha"]
                            and existing.get("discovered_count") == TOTAL,
                            "BATCH_EXISTING_STATE_CONFLICT")
                    result = existing  # restart-safe: never reset processed jobs
                else:
                    result = proposed
            elif args.mode == "claim":
                result, job = claim_next(operator.read_json(args.state, 256_000))
                require(not args.job_output.exists(), "BATCH_JOB_OUTPUT_ALREADY_EXISTS")
                atomic_write(args.job_output, job)
            else:
                result = complete_active(operator.read_json(args.state, 256_000),
                                         operator.read_json(args.result, 64_000))
            atomic_write(args.state, result)
        print(json.dumps({k: v for k, v in result.items() if k != "products"},
                         ensure_ascii=False))
        return 0
    except (BatchHold, operator.OperatorHold, OSError) as exc:
        print(json.dumps({"status": "MULTI_PRODUCT_IDENTITY_BATCH_PARTIAL",
                          "reason": str(exc), "store_submission": 0}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
