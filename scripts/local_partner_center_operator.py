"""Guarded local Partner Center operator contract.

Prepare only after a physical exact-source snapshot is verified. Validate only
locally captured, operator-attested Store Identity. No browser automation,
credentials, Store submission, package upload, or CAS is performed here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from scripts import local_code_sync as sync

REGISTRATIONS = {
    "MSIX_OR_PWA_APP": "MSIX or PWA app",
    "EXE_OR_MSI_APP": "EXE or MSI app",
    "GDK_GAME": "GDK game",
    "MSIX_OR_PWA_GAME": "MSIX or PWA game",
}
BINDING = (
    "request_id", "slug", "source_repository", "source_branch",
    "source_sha", "registration_type", "partner_center_selection", "display_name",
)
CENTRAL_REPOSITORY = "shihuiarenjinba-png/Windows-all-auto"
CENTRAL_BRANCH = "codex/e2e-belt-connection-20261027"
IDENTITY_RETURN_TARGET = "products/prism-route-3d/store/approved-identity.json"
IDENTITY = (
    "store_id", "reserved_display_name", "identity_name", "publisher",
    "publisher_display_name", "package_family_name", "package_sid",
)
EVIDENCE = ("creation_status", "overview_exact_match_count", "identity_details_observed")
CAPTURE_KEYS = set(BINDING + IDENTITY + EVIDENCE)


class OperatorHold(ValueError):
    pass


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise OperatorHold("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _safe_path(path: Path) -> bool:
    return not any(sync._unsafe_path(p) for p in (path, *path.parents) if p.exists())


def read_json(path: Path, limit: int = 1_000_000) -> dict:
    if not _safe_path(path) or not path.is_file() or path.stat().st_size > limit:
        raise OperatorHold("UNSAFE_OR_MISSING_JSON_FILE")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates)
    except (UnicodeError, OSError, json.JSONDecodeError) as exc:
        raise OperatorHold("INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise OperatorHold("EXPECTED_JSON_OBJECT")
    return value


def _equal(a, b):
    if a != b:
        raise OperatorHold("CROSS_PRODUCT_OR_SOURCE_BINDING_CONFLICT")


def _text(value):
    return (isinstance(value, str) and 0 < len(value) <= 256
            and value == value.strip() and not any(c in value for c in "\r\n\0"))


def _sha256_json(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def expected_job(ledger: dict, slug: str) -> dict:
    operator = ledger.get("partner_center_local_operator")
    if not isinstance(operator, dict) or operator.get("allow_local_product_creation") is not True:
        raise OperatorHold("LOCAL_OPERATOR_NOT_AUTHORIZED")
    if operator.get("mode", "").split("__")[0] != "LOCAL_OPERATOR_ACTIVE":
        raise OperatorHold("LOCAL_OPERATOR_NOT_ACTIVE")
    candidates = ledger.get("rotation_cohorts", {}).get("three_d_jobs", [])
    matches = [x for x in candidates if isinstance(x, dict) and x.get("slug") == slug]
    if len(matches) != 1 or matches[0].get("status") != "PRE_IDENTITY_READY":
        raise OperatorHold("PRE_IDENTITY_JOB_NOT_UNIQUE")
    source = matches[0]
    job = {k: source.get(k) for k in BINDING}
    if not all(_text(x) for x in job.values()):
        raise OperatorHold("INCOMPLETE_JOB_BINDING")
    if job["registration_type"] not in REGISTRATIONS:
        raise OperatorHold("HOLD_REGISTRATION_TYPE_UNRESOLVED")
    _equal(job["partner_center_selection"], REGISTRATIONS[job["registration_type"]])
    for key in BINDING:
        _equal(job[key], operator.get("exact_display_name" if key == "display_name" else key))
    _equal(job["slug"], "prism-route-3d")
    _equal(job["display_name"], "Prism Route 3D")
    _equal(job["registration_type"], "MSIX_OR_PWA_GAME")
    _equal(job["source_repository"], "shihuiarenjinba-png/3d-game-factory")
    sync._normalize_job({
        "repository": job["source_repository"], "branch": job["source_branch"],
        "source_sha": job["source_sha"], "slug": job["slug"],
        "request_id": job["request_id"],
    })
    return job


def prepare(ledger: dict, receipt: dict, root: Path, slug: str = "prism-route-3d", *,
            central_repository: str = CENTRAL_REPOSITORY,
            central_branch: str = CENTRAL_BRANCH,
            central_head_sha: str | None = None) -> dict:
    job = expected_job(ledger, slug)
    if (central_repository != CENTRAL_REPOSITORY or central_branch != CENTRAL_BRANCH
            or not isinstance(central_head_sha, str)
            or not re.fullmatch(r"[0-9a-f]{40}", central_head_sha)):
        raise OperatorHold("CENTRAL_GITHUB_JOB_PROVENANCE_INVALID")
    if receipt.get("status") != "PASS" or receipt.get("exact_sha_verified") is not True:
        raise OperatorHold("LOCAL_CODE_SYNC_NOT_PASS")
    products = receipt.get("products")
    if not isinstance(products, list):
        raise OperatorHold("LOCAL_CODE_SYNC_RECEIPT_INVALID")
    matches = [x for x in products if isinstance(x, dict) and x.get("slug") == slug]
    if len(matches) != 1:
        raise OperatorHold("LOCAL_SNAPSHOT_NOT_UNIQUE")
    item = matches[0]
    for key, remote_key in (("request_id", "request_id"), ("source_sha", "source_sha"),
                            ("source_branch", "branch"), ("source_repository", "repository")):
        _equal(job[key], item.get(remote_key))
    if item.get("status") not in ("DOWNLOADED_EXACT_SNAPSHOT", "REUSED_EXACT_SNAPSHOT"):
        raise OperatorHold("LOCAL_SNAPSHOT_STATUS_INVALID")
    expected = root / job["source_repository"].split("/", 1)[1] / job["source_sha"][:12]
    if not _safe_path(expected) or not expected.is_dir() or not item.get("path"):
        raise OperatorHold("LOCAL_SNAPSHOT_UNSAFE_OR_MISSING")
    _equal(Path(item["path"]).resolve(), expected.resolve())
    try:
        snapshot = sync._verify_existing(expected, {
            "repository": job["source_repository"], "branch": job["source_branch"],
            "source_sha": job["source_sha"],
        })
    except (sync.SyncHold, OSError) as exc:
        raise OperatorHold("LOCAL_CODE_SYNC_REVALIDATION_FAILED") from exc
    return {
        "schema_version": 1, **job,
        "product_type": "GAME_3D",
        "status": "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY",
        "job_origin": "GITHUB_PRE_IDENTITY_QUEUE",
        "central_repository": central_repository,
        "central_branch": central_branch,
        "central_head_sha": central_head_sha,
        "queue_job_digest": _sha256_json(
            next(x for x in ledger["rotation_cohorts"]["three_d_jobs"] if x.get("slug") == slug)
        ),
        "snapshot_path": str(expected),
        "source_snapshot_head": job["source_sha"],
        "source_snapshot_status": snapshot["status"],
        "identity_return_target": IDENTITY_RETURN_TARGET,
        "partner_center_product_status": "UNVERIFIED_SEARCH_REQUIRED",
        "allow_local_product_creation": True,
        "create_only_after_exact_zero_results": True,
        "required_identity_fields": list(IDENTITY),
        "browser_action_performed": False,
        "cas_applied": False,
        "store_submitted": False,
    }


def validate_capture(job: dict, captured: dict, reference: dict | None = None) -> dict:
    if job.get("status") != "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY":
        raise OperatorHold("LOCAL_CODE_SYNC_GATE_NOT_READY")
    if set(captured) != CAPTURE_KEYS:
        raise OperatorHold("INCOMPLETE_OR_UNEXPECTED_CAPTURE_FIELDS_POSSIBLE_SECRET")
    for key in BINDING:
        _equal(job.get(key), captured[key])
    if (captured["creation_status"] not in ("CREATED", "REUSED_EXISTING")
            or type(captured["overview_exact_match_count"]) is not int
            or captured["overview_exact_match_count"] != 1
            or captured["identity_details_observed"] is not True):
        raise OperatorHold("PRODUCT_CREATION_EVIDENCE_INCOMPLETE")
    if not all(_text(captured[key]) for key in IDENTITY):
        raise OperatorHold("IDENTITY_FIELD_INVALID")
    if (not re.fullmatch(r"[A-Za-z0-9]{8,32}", captured["store_id"])
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,100}", captured["identity_name"])
            or not re.fullmatch(r"[A-Za-z0-9._-]+_[a-z0-9]{13}", captured["package_family_name"])
            or not re.fullmatch(r"S-1-15-2(?:-\d+){7}", captured["package_sid"])):
        raise OperatorHold("IDENTITY_SCHEMA_INVALID")
    _equal(captured["reserved_display_name"], job["display_name"])
    reference_result = "NOT_PERFORMED"
    if reference is not None:
        if set(reference) != set(IDENTITY):
            raise OperatorHold("MANUAL_REFERENCE_FIELDS_INVALID")
        if any(reference[key] != captured[key] for key in IDENTITY):
            raise OperatorHold("HOLD_IDENTITY_CAPTURE_MISMATCH")
        reference_result = "MATCH"
    return {
        "schema_version": 1,
        "status": "IDENTITY_CAPTURED__UI_MATCHED_REFERENCE__GITHUB_BOUND",
        "authenticated_partner_center_pass": True,
        "capture_source": "AUTHENTICATED_PARTNER_CENTER_UI",
        "job_origin": job["job_origin"],
        "central_repository": job["central_repository"],
        "central_branch": job["central_branch"],
        "central_head_sha": job["central_head_sha"],
        "queue_job_digest": job["queue_job_digest"],
        "request_id": job["request_id"],
        "source_repository": job["source_repository"],
        "source_branch": job["source_branch"],
        "source_sha": job["source_sha"],
        "source_snapshot_path": job["snapshot_path"],
        "source_snapshot_head": job["source_snapshot_head"],
        "slug": job["slug"],
        "product_type": job["product_type"],
        "registration_type": job["registration_type"],
        "partner_center_selection": job["partner_center_selection"],
        "display_name": job["display_name"],
        **{k: captured[k] for k in IDENTITY},
        "captured_at": _utc_now(),
        "creation_status": captured["creation_status"],
        "overview_exact_match_count": captured["overview_exact_match_count"],
        "identity_details_observed": captured["identity_details_observed"],
        "manual_reference_comparison": reference_result,
        "identity_return_target": job["identity_return_target"],
        "package_version_gate": "HOLD",
        "existing_scheduler_routing_pending": True,
        "cas_applied": False,
        "store_submitted": False,
    }


def write_private_once(path: Path, value: dict) -> None:
    if not _safe_path(path):
        raise OperatorHold("UNSAFE_OUTPUT_PATH")
    data = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == data:
            return
        raise OperatorHold("EXISTING_RECEIPT_CONFLICT_NO_OVERWRITE")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            fd = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise OperatorHold("EXISTING_RECEIPT_CONFLICT_NO_OVERWRITE") from exc
    except BaseException:
        if fd is not None:
            os.close(fd)
        if path.exists():
            path.unlink()
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--ledger", type=Path, required=True)
    p.add_argument("--sync-receipt", type=Path, required=True)
    p.add_argument("--snapshot-root", type=Path, required=True)
    p.add_argument("--central-repository", default=CENTRAL_REPOSITORY)
    p.add_argument("--central-branch", default=CENTRAL_BRANCH)
    p.add_argument("--central-head-sha", required=True)
    p.add_argument("--output", type=Path)
    c = sub.add_parser("capture")
    c.add_argument("--job", type=Path, required=True)
    c.add_argument("--output", type=Path, required=True)
    c.add_argument("--creation-status", choices=("CREATED", "REUSED_EXISTING"), required=True)
    c.add_argument("--overview-exact-match-count", type=int, required=True)
    for field in IDENTITY:
        c.add_argument("--" + field.replace("_", "-"), required=True)
    v = sub.add_parser("validate")
    v.add_argument("--job", type=Path, required=True)
    v.add_argument("--capture", type=Path, required=True)
    v.add_argument("--reference", type=Path)
    v.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "prepare":
            result = prepare(
                read_json(args.ledger), read_json(args.sync_receipt), args.snapshot_root,
                central_repository=args.central_repository,
                central_branch=args.central_branch,
                central_head_sha=args.central_head_sha,
            )
        elif args.mode == "capture":
            job = read_json(args.job)
            capture = {
                **{key: job[key] for key in BINDING},
                **{key: getattr(args, key) for key in IDENTITY},
                "creation_status": args.creation_status,
                "overview_exact_match_count": args.overview_exact_match_count,
                "identity_details_observed": True,
            }
            validate_capture(job, capture)
            write_private_once(args.output, capture)
            result = {"status": "IDENTITY_CAPTURE_SAVED", "request_id": job["request_id"]}
        else:
            reference = read_json(args.reference, 64_000) if args.reference else None
            result = validate_capture(read_json(args.job), read_json(args.capture, 64_000), reference)
        if args.mode != "capture" and args.output:
            write_private_once(args.output, result)
        # Identity values and private paths must not appear in CI/terminal logs.
        print(json.dumps({k: v for k, v in result.items()
                          if k not in set(IDENTITY) | {"snapshot_path", "source_snapshot_path"}}, ensure_ascii=False))
        return 0
    except (OperatorHold, sync.SyncHold, OSError) as exc:
        print(json.dumps({"status": "LOCAL_PARTNER_CENTER_OPERATOR_HOLD",
                          "reason": str(exc)[:100], "cas_applied": False,
                          "store_submitted": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
