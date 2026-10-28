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
JOB_BINDING = BINDING + ("product_type", "identity_return_target")
IDENTITY = (
    "store_id", "reserved_display_name", "identity_name", "publisher",
    "publisher_display_name", "package_family_name", "package_sid",
)
EVIDENCE = ("creation_status", "overview_exact_match_count", "identity_details_observed")
CAPTURE_KEYS = set(JOB_BINDING + IDENTITY + EVIDENCE)
LEGACY_CAPTURE_KEYS = set(BINDING + IDENTITY + EVIDENCE)
BATCH_FIELDS = {
    "batch_id", "batch_index", "batch_total", "trigger_origin", "automation_id",
    "dispatch_origin", "execution_origin",
}


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


def canonical_digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def expected_job(ledger: dict, slug: str) -> dict:
    operator = ledger.get("partner_center_local_operator")
    if not isinstance(operator, dict):
        raise OperatorHold("LOCAL_OPERATOR_NOT_AUTHORIZED")
    if operator.get("mode", "").split("__")[0] != "LOCAL_OPERATOR_ACTIVE":
        raise OperatorHold("LOCAL_OPERATOR_NOT_ACTIVE")
    cohorts = ledger.get("rotation_cohorts", {})
    candidates = []
    for field, inferred_type in (("app_jobs", "APP"), ("three_d_jobs", "GAME_3D"),
                                 ("game_jobs", "GAME")):
        lane = cohorts.get(field, [])
        if not isinstance(lane, list):
            raise OperatorHold("ROTATION_COHORT_INVALID")
        candidates.extend({**x, "_inferred_product_type": inferred_type}
                          for x in lane if isinstance(x, dict))
    matches = [x for x in candidates if isinstance(x, dict) and x.get("slug") == slug]
    if len(matches) != 1 or matches[0].get("status") != "PRE_IDENTITY_READY":
        raise OperatorHold("PRE_IDENTITY_JOB_NOT_UNIQUE")
    source = matches[0]
    target = f"products/{slug}/store/approved-identity.json"
    # A valid slug is insufficient: all lanes must reserve distinct request IDs
    # and return paths. Otherwise a second product could claim this receipt.
    if sum(x.get("request_id") == source.get("request_id") for x in candidates) != 1:
        raise OperatorHold("CROSS_LANE_REQUEST_ID_CONFLICT")
    if sum(x.get("identity_return_target") == target for x in candidates) != 1:
        raise OperatorHold("CROSS_LANE_IDENTITY_TARGET_CONFLICT")
    job = {k: source.get(k) for k in BINDING}
    job["product_type"] = source.get("product_type", source["_inferred_product_type"])
    if job["product_type"] != source["_inferred_product_type"]:
        raise OperatorHold("CROSS_LANE_PRODUCT_TYPE_CONFLICT")
    requests = (ledger.get("user_id_requests") or {}).get("items", [])
    request_matches = [x for x in requests if isinstance(x, dict)
                       and x.get("request_id") == source.get("request_id")]
    if len(request_matches) != 1:
        raise OperatorHold("IDENTITY_REQUEST_NOT_UNIQUE")
    request = request_matches[0]
    # The queue job owns the return target. A matching user request is an
    # independent cross-check, never the authority to fill a missing target.
    job["identity_return_target"] = source.get("identity_return_target")
    if not all(_text(x) for x in job.values()):
        raise OperatorHold("INCOMPLETE_JOB_BINDING")
    if job["registration_type"] not in REGISTRATIONS:
        raise OperatorHold("HOLD_REGISTRATION_TYPE_UNRESOLVED")
    _equal(job["partner_center_selection"], REGISTRATIONS[job["registration_type"]])
    if job["product_type"] == "APP":
        if (job["source_repository"] != "shihuiarenjinba-png/AI-App-Factory"
                or job["registration_type"] not in {"MSIX_OR_PWA_APP", "EXE_OR_MSI_APP"}):
            raise OperatorHold("APP_JOB_ROUTING_CONFLICT")
    elif job["product_type"] == "GAME_3D":
        if (job["source_repository"] != "shihuiarenjinba-png/3d-game-factory"
                or job["registration_type"] not in {"MSIX_OR_PWA_GAME", "GDK_GAME"}):
            raise OperatorHold("GAME_3D_JOB_ROUTING_CONFLICT")
    elif job["product_type"] == "GAME":
        if (job["source_repository"] != "shihuiarenjinba-png/AI-Game-Factory"
                or job["registration_type"] not in {"GDK_GAME", "MSIX_OR_PWA_GAME"}):
            raise OperatorHold("GAME_JOB_ROUTING_CONFLICT")
    else:
        raise OperatorHold("UNSUPPORTED_PRODUCT_TYPE")
    if job["identity_return_target"] != target:
        raise OperatorHold("IDENTITY_RETURN_TARGET_CONFLICT")
    request_binding = {
        "request_id": job["request_id"], "slug": job["slug"],
        "source_sha": job["source_sha"], "registration_type": job["registration_type"],
        "partner_center_selection": job["partner_center_selection"],
        "identity_return_target": target,
    }
    if any(request.get(key) != value for key, value in request_binding.items()):
        raise OperatorHold("CROSS_PRODUCT_IDENTITY_REQUEST_BINDING_CONFLICT")
    if (request.get("repo", request.get("source_repository")) != job["source_repository"]
            or request.get("source_branch") != job["source_branch"]):
        raise OperatorHold("CROSS_PRODUCT_IDENTITY_REQUEST_BINDING_CONFLICT")
    if (request.get("status") is not None
            and request.get("status") != "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE"):
        raise OperatorHold("LOCAL_OPERATOR_NOT_AUTHORIZED")
    # Creation permission is per-product, never inherited from a global
    # operator flag. Missing or malformed consent fails closed.
    allow = request.get("allow_local_product_creation")
    if type(allow) is not bool:
        raise OperatorHold("LOCAL_OPERATOR_NOT_AUTHORIZED")
    job["allow_local_product_creation"] = allow
    job["queue_job_digest"] = canonical_digest(source)
    sync._normalize_job({
        "repository": job["source_repository"], "branch": job["source_branch"],
        "source_sha": job["source_sha"], "slug": job["slug"],
        "request_id": job["request_id"],
    })
    return job


def prepare(ledger: dict, receipt: dict, root: Path, slug: str | None = None, *,
            central_repository: str | None = None, central_branch: str | None = None,
            central_head_sha: str | None = None, batch: dict | None = None) -> dict:
    if slug is None:
        ready = [x for field in ("app_jobs", "three_d_jobs", "game_jobs")
                 for x in ledger.get("rotation_cohorts", {}).get(field, [])
                 if isinstance(x, dict) and x.get("status") == "PRE_IDENTITY_READY"]
        if len(ready) != 1 or not _text(ready[0].get("slug")):
            raise OperatorHold("PRE_IDENTITY_JOB_NOT_UNIQUE")
        slug = ready[0]["slug"]
    job = expected_job(ledger, slug)
    if batch is not None:
        if (set(batch) != BATCH_FIELDS
                or batch.get("trigger_origin") != "SCHEDULED_36_MIN_LOOP"
                or batch.get("dispatch_origin") != "CHATGPT_36_MIN_LOOP"
                or batch.get("execution_origin") not in {
                    "MANUAL_WINDOWS_TERMINAL", "WINDOWS_TASK_SCHEDULER",
                    "WINDOWS_TASK_SCHEDULER_MANUAL_START",
                }
                or batch.get("automation_id") != "6adf4b1e7654819193b997fb4fb83c85"
                or batch.get("batch_total") != 4
                or type(batch.get("batch_index")) is not int
                or not 1 <= batch["batch_index"] <= 4
                or not _text(batch.get("batch_id"))):
            raise OperatorHold("BATCH_METADATA_INVALID")
    if any(value is not None for value in
           (central_repository, central_branch, central_head_sha)):
        if (central_repository != "shihuiarenjinba-png/Windows-all-auto"
                or central_branch != "codex/e2e-belt-connection-20261027"
                or not re.fullmatch(r"[0-9a-f]{40}", str(central_head_sha))):
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
        sync._verify_existing(expected, {
            "repository": job["source_repository"], "branch": job["source_branch"],
            "source_sha": job["source_sha"],
        })
    except (sync.SyncHold, OSError) as exc:
        raise OperatorHold("LOCAL_CODE_SYNC_REVALIDATION_FAILED") from exc
    return {
        "schema_version": 1, **job,
        "status": "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY",
        "job_origin": "GITHUB_PRE_IDENTITY_QUEUE",
        "central_repository": central_repository,
        "central_branch": central_branch,
        "central_head_sha": central_head_sha,
        "snapshot_path": str(expected),
        "source_snapshot_head": job["source_sha"],
        "source_snapshot_status": item["status"],
        "partner_center_product_status": ("EXISTING_PRODUCT_REUSE_ONLY"
                                          if job["allow_local_product_creation"] is False
                                          else "UNVERIFIED_SEARCH_REQUIRED"),
        "create_only_after_exact_zero_results": True,
        "required_identity_fields": list(IDENTITY),
        "browser_action_performed": False,
        "cas_applied": False,
        "store_submitted": False,
        **(batch or {}),
    }


def validate_capture(job: dict, captured: dict) -> dict:
    if job.get("status") != "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY":
        raise OperatorHold("LOCAL_CODE_SYNC_GATE_NOT_READY")
    legacy = set(captured) == LEGACY_CAPTURE_KEYS
    if not legacy and set(captured) != CAPTURE_KEYS:
        raise OperatorHold("INCOMPLETE_OR_UNEXPECTED_CAPTURE_FIELDS_POSSIBLE_SECRET")
    for key in BINDING:
        _equal(job.get(key), captured[key])
    if not legacy:
        for key in ("product_type", "identity_return_target"):
            _equal(job.get(key), captured[key])
    if (captured["creation_status"] not in ("CREATED", "REUSED_EXISTING")
            or type(captured["overview_exact_match_count"]) is not int
            or captured["overview_exact_match_count"] != 1
            or captured["identity_details_observed"] is not True):
        raise OperatorHold("PRODUCT_CREATION_EVIDENCE_INCOMPLETE")
    if (job.get("allow_local_product_creation") is False
            and captured["creation_status"] != "REUSED_EXISTING"):
        raise OperatorHold("HOLD_DUPLICATE_PRODUCT_CREATE_FORBIDDEN")
    if not all(_text(captured[key]) for key in IDENTITY):
        raise OperatorHold("IDENTITY_FIELD_INVALID")
    if (not re.fullmatch(r"[A-Za-z0-9]{8,32}", captured["store_id"])
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,100}", captured["identity_name"])
            or not re.fullmatch(r"[A-Za-z0-9._-]+_[a-z0-9]{13}", captured["package_family_name"])
            or not re.fullmatch(r"S-1-15-2(?:-\d+){7}", captured["package_sid"])):
        raise OperatorHold("IDENTITY_SCHEMA_INVALID")
    _equal(captured["reserved_display_name"], job["display_name"])
    if legacy:
        return {
            "schema_version": 1,
            "status": "IDENTITY_CAPTURED__LOCAL_OPERATOR_ATTESTED__SCHEMA_VALIDATED",
            "authenticated_partner_center_pass": False,
            "request_id": job["request_id"],
            "source_sha": job["source_sha"],
            "registration_type": job["registration_type"],
            "identity": {k: captured[k] for k in IDENTITY},
            "existing_scheduler_routing_pending": True,
            "cas_applied": False,
            "store_submitted": False,
        }
    return {
        "schema_version": 1,
        # This module validates a supplied JSON payload; it never controls
        # or independently observes an authenticated browser. An input field
        # such as identity_details_observed=True is an operator assertion,
        # not proof of a Partner Center session. Keep the authentication gate
        # closed until a separate trusted local UI receipt is verified.
        "status": "IDENTITY_CAPTURED__OPERATOR_ATTESTED__GITHUB_BOUND",
        "authenticated_partner_center_pass": False,
        "capture_source": "LOCAL_OPERATOR_SUPPLIED_JSON_UNVERIFIED_UI",
        "authenticated_ui_evidence_status": "HOLD_INDEPENDENT_UI_ATTESTATION",
        "job_origin": job["job_origin"],
        "central_repository": job["central_repository"],
        "central_branch": job["central_branch"],
        "central_head_sha": job["central_head_sha"],
        "queue_job_digest": job["queue_job_digest"],
        "request_id": job["request_id"],
        "slug": job["slug"],
        "product_type": job["product_type"],
        "display_name": job["display_name"],
        "source_repository": job["source_repository"],
        "source_branch": job["source_branch"],
        "source_sha": job["source_sha"],
        "source_snapshot_path": job["snapshot_path"],
        "source_snapshot_head": job["source_snapshot_head"],
        "registration_type": job["registration_type"],
        "partner_center_selection": job["partner_center_selection"],
        "identity_return_target": job["identity_return_target"],
        **{k: captured[k] for k in IDENTITY},
        "captured_at": _utc_now(),
        "creation_status": captured["creation_status"],
        "overview_exact_match_count": captured["overview_exact_match_count"],
        "identity_details_observed": captured["identity_details_observed"],
        "package_version_gate": "HOLD",
        "existing_scheduler_routing_pending": True,
        "cas_applied": False,
        "store_submitted": False,
        **{key: job[key] for key in (
            "batch_id", "batch_index", "batch_total", "trigger_origin", "automation_id"
            , "dispatch_origin", "execution_origin"
        ) if key in job},
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
    p.add_argument("--slug", required=True)
    p.add_argument("--central-repository", default="shihuiarenjinba-png/Windows-all-auto")
    p.add_argument("--central-branch", default="codex/e2e-belt-connection-20261027")
    p.add_argument("--central-head-sha", required=True)
    p.add_argument("--batch-metadata", type=Path)
    p.add_argument("--output", type=Path)
    v = sub.add_parser("validate")
    v.add_argument("--job", type=Path, required=True)
    v.add_argument("--capture", type=Path, required=True)
    v.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "prepare":
            result = prepare(
                read_json(args.ledger), read_json(args.sync_receipt), args.snapshot_root,
                args.slug, central_repository=args.central_repository,
                central_branch=args.central_branch, central_head_sha=args.central_head_sha,
                batch=read_json(args.batch_metadata, 32_768) if args.batch_metadata else None,
            )
        else:
            result = validate_capture(read_json(args.job), read_json(args.capture, 64_000))
        if args.output:
            write_private_once(args.output, result)
        # Identity values and private paths must not appear in CI/terminal logs.
        print(json.dumps({k: v for k, v in result.items()
                          if k not in ("identity", "snapshot_path")}, ensure_ascii=False))
        return 0
    except (OperatorHold, sync.SyncHold, OSError) as exc:
        print(json.dumps({"status": "LOCAL_PARTNER_CENTER_OPERATOR_HOLD",
                          "reason": str(exc)[:100], "cas_applied": False,
                          "store_submitted": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
