"""Convert validated APP/3D PRE_IDENTITY rotation into safe local code-sync targets.

Read-only with respect to the central ledger, Factory, Store, Identity and CAS.
The generated manifest is input to scripts.local_code_sync; it is NOT a
GitHub queue attestation or a physical-Windows sync receipt.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile

from scripts.rotation_pre_identity_intake import IntakeHold, project, read_ledger


class PlanHold(ValueError):
    pass


def build_plan(ledger: dict) -> dict:
    projection = project(ledger)  # Reject cross-product and schema conflicts first.
    jobs = []
    holds = []
    bindings = []
    for item in projection["jobs"]:
        identity = {
            "request_id": item["request_id"],
            "slug": item["slug"],
            "lane": item["lane"],
            "source_repository": item["source_repository"],
            "source_branch": item["source_branch"],
            "source_sha": item["source_sha"],
            "registration_type": item["registration_type"],
            "identity_return_target": item["identity_return_target"],
            "rotation_intake_digest": item["rotation_intake_digest"],
        }
        bindings.append(identity)
        if item["source_head_status"] == "HOLD_SOURCE_BRANCH_HEAD_DRIFT":
            holds.append({
                **identity,
                "status": "HOLD_SOURCE_BRANCH_HEAD_DRIFT",
                "observed_branch_head": item["observed_branch_head"],
            })
            continue
        if item["source_head_status"] != "REMOTE_HEAD_RECHECK_REQUIRED":
            raise PlanHold("SOURCE_HEAD_STATE_UNRECOGNIZED")
        jobs.append({
            "request_id": item["request_id"],
            "slug": item["slug"],
            "repository": item["source_repository"],
            "branch": item["source_branch"],
            "source_sha": item["source_sha"],
        })
    return {
        "schema_version": 1,
        "status": ("LOCAL_SOURCE_SYNC_TARGETS_READY__REMOTE_HEAD_UNVERIFIED"
                   if jobs else "HOLD_NO_ELIGIBLE_LOCAL_SOURCE_SYNC_TARGETS"),
        "sync_manifest": {"schema_version": 1, "jobs": jobs},
        "bindings": bindings,
        "holds": holds,
        "metrics": {
            "eligible_jobs": len(jobs),
            "source_head_drift_holds": len(holds),
            "app_total_jobs": projection["metrics"]["app_total_jobs"],
            "3d_total_jobs": projection["metrics"]["3d_total_jobs"],
        },
        "remote_head_verified": False,
        "physical_local_sync_pass": False,
        "github_queue_origin_verified": False,
        "historical_queue_job_digest_verified": False,
        "identity_capture_pass": False,
        "cas_return_pass": False,
        "real_msix_pass": False,
        "e2e_pass": False,
        "store_submission": "NOT_AUTHORIZED",
    }


def _safe_destination(path: Path) -> None:
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise PlanHold("MANIFEST_DESTINATION_UNSAFE")
    parent = path.parent
    if not parent.is_dir():
        raise PlanHold("MANIFEST_PARENT_MISSING")
    for ancestor in (parent, *parent.parents):
        if ancestor.is_symlink():
            raise PlanHold("MANIFEST_PARENT_LINKED")


def write_manifest_once(path: Path, plan: dict) -> str:
    """Idempotent for identical jobs; never overwrite a different local plan."""
    jobs = plan["sync_manifest"]["jobs"]
    if not jobs:
        raise PlanHold("NO_ELIGIBLE_JOBS_MANIFEST_NOT_WRITTEN")
    _safe_destination(path)
    payload = (json.dumps(plan["sync_manifest"], sort_keys=True, indent=2)
               + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() == payload:
            return "REUSED_IDENTICAL_MANIFEST"
        raise PlanHold("MANIFEST_CONFLICT_REFUSE_OVERWRITE")
    fd, temp_name = tempfile.mkstemp(prefix=".rotation-sync-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Exclusive creation: never replace another scheduler's manifest.
        with open(path, "xb") as destination:
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        return "CREATED_NEW_MANIFEST"
    except FileExistsError:
        if path.is_file() and not path.is_symlink() and path.read_bytes() == payload:
            return "REUSED_IDENTICAL_MANIFEST"
        raise PlanHold("MANIFEST_RACE_OR_CONFLICT") from None
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = build_plan(read_ledger(args.ledger))
        if args.manifest and not args.check_only and result["sync_manifest"]["jobs"]:
            result["manifest_write"] = write_manifest_once(args.manifest, result)
        else:
            result["manifest_write"] = "NOT_WRITTEN"
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (PlanHold, IntakeHold, OSError, ValueError) as exc:
        print(json.dumps({
            "status": "HOLD_ROTATION_SOURCE_SYNC_PLAN",
            "reason": str(exc)[:200],
            "physical_local_sync_pass": False,
            "cas_return_pass": False,
            "store_submission": "NOT_AUTHORIZED",
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
