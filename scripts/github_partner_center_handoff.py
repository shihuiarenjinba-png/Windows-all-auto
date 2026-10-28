"""Fail-closed GitHub PRE_IDENTITY -> physical Windows -> existing Store Identity.

No browser/session access, product creation, CAS, Store submission or package upload.
Identity values and source paths remain in private local receipts only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from scripts import local_code_sync as sync
from scripts import local_partner_center_operator as op

CENTRAL_REPOSITORY = "shihuiarenjinba-png/Windows-all-auto"
CENTRAL_BRANCH = "codex/e2e-belt-connection-20261027"
IDENTITY_TARGET = "products/prism-route-3d/store/approved-identity.json"
GITHUB_ORIGIN_KEYS = (
    "job_origin", "central_repository", "central_branch", "central_head_sha",
    "queue_job_digest", "identity_return_target", "source_snapshot_path",
    "source_snapshot_head",
)
SHA = re.compile(r"^[0-9a-f]{40}$")


def hold(code: str):
    raise op.OperatorHold(code)


def verify_central(checkout: Path) -> str:
    """Verify a clean independent central checkout against live GitHub branch HEAD."""
    if not op._safe_path(checkout) or not checkout.is_dir():
        hold("CENTRAL_CHECKOUT_UNSAFE")
    if not (checkout / ".git").is_dir() or not op._safe_path(checkout / ".git"):
        hold("CENTRAL_GIT_METADATA_UNSAFE")
    ledger_path = checkout / "ops" / "active_e2e_handoff.json"
    if not op._safe_path(ledger_path) or not ledger_path.is_file():
        hold("CENTRAL_LEDGER_UNSAFE")
    try:
        head = sync._run("git", "-C", str(checkout), "rev-parse", "HEAD")
        origin = sync._run("git", "-C", str(checkout), "remote", "get-url", "origin")
        dirty = sync._run("git", "-C", str(checkout), "status", "--porcelain")
        remote = sync._run(
            "git", "ls-remote", "--heads",
            "https://github.com/" + CENTRAL_REPOSITORY + ".git",
            "refs/heads/" + CENTRAL_BRANCH,
        )
    except (sync.SyncHold, OSError) as exc:
        raise op.OperatorHold("CENTRAL_GITHUB_ORIGIN_UNVERIFIED") from exc
    if not SHA.fullmatch(head):
        hold("CENTRAL_HEAD_INVALID")
    if origin != "https://github.com/" + CENTRAL_REPOSITORY + ".git" or dirty:
        hold("CENTRAL_CHECKOUT_ORIGIN_OR_DIRTY_CONFLICT")
    if remote.splitlines() != [head + "\trefs/heads/" + CENTRAL_BRANCH]:
        hold("CENTRAL_REMOTE_HEAD_CONFLICT")
    return head


def queue_payload(ledger: dict) -> dict:
    job = op.expected_job(ledger, "prism-route-3d")
    matches = [
        x for x in ledger.get("rotation_cohorts", {}).get("three_d_jobs", [])
        if isinstance(x, dict) and x.get("request_id") == job["request_id"]
    ]
    if len(matches) != 1:
        hold("QUEUE_JOB_NOT_UNIQUE")
    source = matches[0]
    requests = [
        x for x in ledger.get("user_id_requests", {}).get("items", [])
        if isinstance(x, dict) and x.get("request_id") == job["request_id"]
    ]
    if len(requests) != 1:
        hold("IDENTITY_RETURN_REQUEST_NOT_UNIQUE")
    request = requests[0]
    for key in ("source_repository", "source_branch", "source_sha", "registration_type",
                "partner_center_selection", "slug"):
        if request.get(key) != job[key]:
            hold("CROSS_PRODUCT_IDENTITY_RETURN_CONFLICT")
    target = request.get("identity_return_target")
    if target != IDENTITY_TARGET:
        hold("IDENTITY_RETURN_TARGET_CONFLICT")
    if not re.fullmatch(r"[0-9a-f]{64}", source.get("expected_exe_sha256", "")):
        hold("EXE_SHA_MISSING")
    if not SHA.fullmatch(source.get("factory_build_head", "")):
        hold("FACTORY_BUILD_HEAD_MISSING")
    if ledger.get("partner_center_local_operator", {}).get("allow_local_product_creation") is not False:
        hold("EXISTING_PRODUCT_CREATE_MUST_BE_DISABLED")
    return {
        **job,
        "expected_exe_sha256": source["expected_exe_sha256"],
        "factory_build_head": source["factory_build_head"],
        "identity_return_target": target,
        "allow_local_product_creation": False,
    }


def queue_digest(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def prepare_github(central_checkout: Path, sync_receipt: dict,
                   snapshot_root: Path) -> dict:
    head = verify_central(central_checkout)
    ledger = op.read_json(central_checkout / "ops" / "active_e2e_handoff.json")
    payload = queue_payload(ledger)
    prepared = op.prepare(ledger, sync_receipt, snapshot_root)
    for key in op.BINDING:
        if prepared.get(key) != payload[key]:
            hold("PREPARED_JOB_BINDING_CONFLICT")
    if prepared.get("allow_local_product_creation") is not False:
        hold("DUPLICATE_PRODUCT_CREATE_FORBIDDEN")
    return {
        **prepared,
        "job_origin": "GITHUB_PRE_IDENTITY_QUEUE",
        "central_repository": CENTRAL_REPOSITORY,
        "central_branch": CENTRAL_BRANCH,
        "central_head_sha": head,
        "queue_job_digest": queue_digest(payload),
        "identity_return_target": payload["identity_return_target"],
        "source_snapshot_path": prepared["snapshot_path"],
        "source_snapshot_head": payload["source_sha"],
    }


def validate_github(job: dict, captured: dict, reference: dict,
                    central_checkout: Path, snapshot_root: Path) -> dict:
    head = verify_central(central_checkout)
    ledger = op.read_json(central_checkout / "ops" / "active_e2e_handoff.json")
    payload = queue_payload(ledger)
    expected = {
        "job_origin": "GITHUB_PRE_IDENTITY_QUEUE",
        "central_repository": CENTRAL_REPOSITORY,
        "central_branch": CENTRAL_BRANCH,
        "central_head_sha": head,
        "queue_job_digest": queue_digest(payload),
        "identity_return_target": payload["identity_return_target"],
        "source_snapshot_head": payload["source_sha"],
    }
    for key, value in expected.items():
        if job.get(key) != value:
            hold("GITHUB_QUEUE_PROVENANCE_CONFLICT")
    for key in op.BINDING:
        if job.get(key) != payload[key]:
            hold("CROSS_PRODUCT_OR_SOURCE_BINDING_CONFLICT")
    if job.get("allow_local_product_creation") is not False:
        hold("DUPLICATE_PRODUCT_CREATE_FORBIDDEN")
    expected_snapshot = snapshot_root / payload["source_repository"].split("/", 1)[1] / payload["source_sha"][:12]
    if (not op._safe_path(expected_snapshot) or not expected_snapshot.is_dir()
            or job.get("source_snapshot_path") != str(expected_snapshot)
            or job.get("snapshot_path") != str(expected_snapshot)):
        hold("LOCAL_SNAPSHOT_PATH_CONFLICT")
    try:
        sync._verify_existing(expected_snapshot, {
            "repository": payload["source_repository"],
            "branch": payload["source_branch"],
            "source_sha": payload["source_sha"],
        })
    except (sync.SyncHold, OSError) as exc:
        raise op.OperatorHold("LOCAL_SNAPSHOT_REVALIDATION_FAILED") from exc
    if (set(reference) != {"source", "product", "identity"}
            or reference["source"] != "LOCAL_OPERATOR_MANUAL_REFERENCE"
            or reference["product"] != payload["display_name"]
            or not isinstance(reference["identity"], dict)
            or set(reference["identity"]) != set(op.IDENTITY)):
        hold("MANUAL_REFERENCE_SCHEMA_CONFLICT")
    result = op.validate_capture(job, captured)
    if captured["creation_status"] != "REUSED_EXISTING":
        hold("EXISTING_PRODUCT_MUST_BE_REUSED")
    for key in op.IDENTITY:
        if result["identity"][key] != reference["identity"][key]:
            hold("MANUAL_REFERENCE_IDENTITY_CONFLICT")
    return {
        **result,
        "status": "LOCAL_CAPTURE_SCHEMA_MATCHED_MANUAL_REFERENCE__AUTOMATED_UI_NOT_VERIFIED",
        **expected,
        "source_snapshot_path": str(expected_snapshot),
        "existing_scheduler_routing_pending": True,
        "authenticated_partner_center_pass": False,
        "cas_applied": False,
        "store_submitted": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--central-checkout", type=Path, required=True)
    p.add_argument("--sync-receipt", type=Path, required=True)
    p.add_argument("--snapshot-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    v = sub.add_parser("validate")
    v.add_argument("--central-checkout", type=Path, required=True)
    v.add_argument("--snapshot-root", type=Path, required=True)
    v.add_argument("--job", type=Path, required=True)
    v.add_argument("--capture", type=Path, required=True)
    v.add_argument("--manual-reference", type=Path, required=True)
    v.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "prepare":
            result = prepare_github(args.central_checkout, op.read_json(args.sync_receipt),
                                    args.snapshot_root)
        else:
            result = validate_github(
                op.read_json(args.job), op.read_json(args.capture, 64_000),
                op.read_json(args.manual_reference, 64_000),
                args.central_checkout, args.snapshot_root,
            )
        op.write_private_once(args.output, result)
        # Do not log Identity, publisher, local snapshot paths, or credentials.
        print(json.dumps({
            "status": result["status"], "request_id": result["request_id"],
            "job_origin": result["job_origin"], "central_head_sha": result["central_head_sha"],
            "queue_job_digest": result["queue_job_digest"],
            "cas_applied": False, "store_submitted": False,
        }))
        return 0
    except (op.OperatorHold, sync.SyncHold, OSError) as exc:
        # Only fixed error codes are emitted; no raw browser, git or Identity values.
        code = str(exc)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", code):
            code = "LOCAL_GITHUB_OPERATOR_UNVERIFIED"
        print(json.dumps({"status": "LOCAL_PARTNER_CENTER_OPERATOR_HOLD",
                          "reason": code, "cas_applied": False,
                          "store_submitted": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
