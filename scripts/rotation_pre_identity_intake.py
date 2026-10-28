"""Project independent APP and real 3D PRE_IDENTITY jobs from the central ledger.

This is a secret-free, read-only intake contract. It is NOT a scheduler CAS
receipt, a GitHub-origin attestation, or a local/remote HEAD verification.
No Partner Center calls, Identity materialization, package build or Store writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

SHA = re.compile(r"^[0-9a-f]{40}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
REQUEST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,159}$")
SLUG = re.compile(r"^[a-z][a-z0-9-]{2,49}$")
BRANCH = re.compile(r"^codex/[A-Za-z0-9._/-]+$")
REGISTRATIONS = {
    "MSIX_OR_PWA_APP": "MSIX or PWA app",
    "EXE_OR_MSI_APP": "EXE or MSI app",
    "GDK_GAME": "GDK game",
    "MSIX_OR_PWA_GAME": "MSIX or PWA game",
}
IDENTITY_TARGET = "%LOCALAPPDATA%/FactoryIdentityWorker/secure/<request_id>/official-identity.json"
LANES = {
    "APP": ("app_jobs", 5, "shihuiarenjinba-png/AI-App-Factory"),
    "GAME_3D": ("three_d_jobs", 1, "shihuiarenjinba-png/3d-game-factory"),
}
REQUIRED = ("request_id", "slug", "source_repository", "source_branch",
            "source_sha", "factory_build_head", "expected_exe_sha256",
            "registration_type", "partner_center_selection")


class IntakeHold(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise IntakeHold(code)


def unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        require(key not in obj, "DUPLICATE_JSON_KEY")
        obj[key] = value
    return obj


def read_ledger(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink(), "LEDGER_MISSING_OR_UNSAFE")
    require(path.stat().st_size <= 2_000_000, "LEDGER_TOO_LARGE")
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntakeHold("LEDGER_JSON_INVALID") from exc
    require(isinstance(data, dict), "LEDGER_NOT_OBJECT")
    return data


def _safe_branch(value: object) -> bool:
    return (isinstance(value, str) and BRANCH.fullmatch(value) is not None
            and ".." not in value and "//" not in value
            and not value.endswith(("/", ".")) and "@{" not in value
            and all(part and not part.startswith(".") and not part.endswith(".lock")
                    for part in value.split("/")))


def _validate(job: dict, request: dict, lane: str, repository: str) -> dict:
    require(job.get("status") == "PRE_IDENTITY_READY", "JOB_NOT_PRE_IDENTITY_READY")
    require(job.get("product_type") == lane, "LANE_PRODUCT_TYPE_CONFLICT")
    require(all(isinstance(job.get(k), str) and job[k] for k in REQUIRED),
            "JOB_BINDING_INCOMPLETE")
    rid, slug, sha = job["request_id"], job["slug"], job["source_sha"]
    require(REQUEST.fullmatch(rid) is not None and SLUG.fullmatch(slug) is not None,
            "REQUEST_OR_SLUG_INVALID")
    require(job["source_repository"] == repository and _safe_branch(job["source_branch"]),
            "SOURCE_REPOSITORY_OR_BRANCH_INVALID")
    require(SHA.fullmatch(sha) is not None and SHA.fullmatch(job["factory_build_head"]) is not None,
            "SOURCE_OR_BUILD_SHA_INVALID")
    require(HASH.fullmatch(job["expected_exe_sha256"]) is not None,
            "EXPECTED_EXE_SHA_INVALID")
    registration = job["registration_type"]
    require(registration in REGISTRATIONS
            and job["partner_center_selection"] == REGISTRATIONS[registration],
            "REGISTRATION_SELECTION_CONFLICT")
    if lane == "APP":
        require(registration in {"MSIX_OR_PWA_APP", "EXE_OR_MSI_APP"},
                "APP_REGISTRATION_FAMILY_CONFLICT")
    else:
        require(registration in {"MSIX_OR_PWA_GAME", "GDK_GAME"},
                "3D_REGISTRATION_FAMILY_CONFLICT")
        if registration == "MSIX_OR_PWA_GAME":
            require(job.get("packaging_strategy") == "GODOT_WINDOWS_EXE_PCK_MAKEAPPX_MSIX"
                    and job.get("packaging_family") == "MSIX",
                    "3D_MSIX_PACKAGING_EVIDENCE_MISSING")
        else:
            require(job.get("packaging_family") == "GDK"
                    and job.get("packaging_strategy") in ("GDK_MSIXVC", "GDK_GAME"),
                    "3D_GDK_PACKAGING_EVIDENCE_MISSING")
    require(request.get("request_id") == rid and request.get("slug") == slug
            and request.get("repo") == repository
            and request.get("source_branch") == job["source_branch"]
            and request.get("source_sha") == sha
            and request.get("registration_type") == registration
            and request.get("partner_center_selection") == job["partner_center_selection"],
            "USER_ID_REQUEST_CROSS_PRODUCT_CONFLICT")
    require(request.get("identity_target") == IDENTITY_TARGET,
            "PRIVATE_IDENTITY_TARGET_CONFLICT")
    target = request.get("identity_return_target")
    require(isinstance(target, str) and target == f"products/{slug}/store/approved-identity.json",
            "IDENTITY_RETURN_TARGET_UNRESOLVED")
    status = request.get("status")
    require(status in ("WAITING_USER_IDENTITY", "USER_IDENTITY_RECEIVED",
                       "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE"),
            "IDENTITY_REQUEST_STATUS_UNRESOLVED")
    if status == "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE":
        # An APP can enter the operator lane only with an explicit creation
        # policy. Existing 3D Prism remains reuse-only; never infer approval.
        require(type(request.get("allow_local_product_creation")) is bool,
                "OPERATOR_CREATION_POLICY_MISSING")
        if lane == "GAME_3D":
            require(request["allow_local_product_creation"] is False,
                    "OPERATOR_CREATION_POLICY_UNSAFE")
    observed = job.get("observed_pr_head")
    drift = observed is not None and observed != sha
    if observed is not None:
        require(isinstance(observed, str) and SHA.fullmatch(observed) is not None,
                "OBSERVED_HEAD_INVALID")
    payload = {k: job[k] for k in REQUIRED}
    payload.update({
        "lane": lane, "identity_target": IDENTITY_TARGET,
        "identity_return_target": target, "identity_status": status,
        "source_head_status": ("HOLD_SOURCE_BRANCH_HEAD_DRIFT" if drift
                               else "REMOTE_HEAD_RECHECK_REQUIRED"),
        "observed_branch_head": observed,
        "remote_head_verified": False, "local_snapshot_verified": False,
        "identity_validated": False, "cas_return_pass": False,
        "real_msix_pass": False, "e2e_pass": False,
        "requires_explicit_cas_approval": True,
    })
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=True).encode("utf-8")).hexdigest()
    payload["rotation_intake_digest"] = digest
    # Not a historical GitHub PRE_IDENTITY queue digest; never substitute it.
    return payload


def project(ledger: dict) -> dict:
    require(ledger.get("e2e_pass") is False and ledger.get("new_product_allowed") is False,
            "CENTRAL_LEDGER_SAFETY_GATE")
    cohorts = ledger.get("rotation_cohorts")
    requests = ledger.get("user_id_requests")
    require(isinstance(cohorts, dict) and isinstance(requests, dict)
            and isinstance(requests.get("items"), list),
            "ROTATION_OR_REQUESTS_MISSING")
    items = requests["items"]
    # Preflight duplicate IDs across every lane before per-job correlation.
    # Otherwise the first cross-product request may mask a duplicate ID.
    all_jobs = []
    for field, maximum, _repository in LANES.values():
        cohort = cohorts.get(field, [])
        require(isinstance(cohort, list) and len(cohort) <= maximum,
                "ROTATION_COHORT_CAPACITY_INVALID")
        require(all(isinstance(item, dict) for item in cohort),
                "ROTATION_JOB_NOT_OBJECT")
        all_jobs.extend(cohort)
    request_ids = [item.get("request_id") for item in all_jobs]
    slugs = [item.get("slug") for item in all_jobs]
    require(all(isinstance(x, str) and x for x in request_ids + slugs),
            "ROTATION_JOB_IDENTITY_MISSING")
    require(len(set(request_ids)) == len(request_ids)
            and len(set(slugs)) == len(slugs),
            "CROSS_PRODUCT_DUPLICATE_REQUEST_OR_SLUG")
    seen_requests, seen_slugs = set(), set()
    jobs = []
    counts = {"app_total_jobs": 0, "app_pre_identity_pass": 0,
              "app_waiting_user_identity": 0, "app_identity_received": 0,
              "app_conflicts": 0, "app_retries": 0, "app_artifact_mismatch": 0,
              "app_schema_conflict": 0, "app_cross_product_rejection": 0,
              "3d_total_jobs": 0, "3d_pre_identity_pass": 0,
              "3d_waiting_identity": 0, "3d_conflicts": 0,
              "3d_artifact_mismatch": 0}
    for lane, (field, maximum, repository) in LANES.items():
        lane_jobs = cohorts.get(field, [])
        require(isinstance(lane_jobs, list) and len(lane_jobs) <= maximum,
                "ROTATION_COHORT_CAPACITY_INVALID")
        for job in lane_jobs:
            require(isinstance(job, dict), "ROTATION_JOB_NOT_OBJECT")
            rid, slug = job.get("request_id"), job.get("slug")
            require(isinstance(rid, str) and isinstance(slug, str),
                    "ROTATION_JOB_IDENTITY_MISSING")
            require(rid not in seen_requests and slug not in seen_slugs,
                    "CROSS_PRODUCT_DUPLICATE_REQUEST_OR_SLUG")
            seen_requests.add(rid)
            seen_slugs.add(slug)
            matches = [x for x in items if isinstance(x, dict) and x.get("request_id") == rid]
            require(len(matches) == 1, "USER_ID_REQUEST_NOT_UNIQUE")
            projected = _validate(job, matches[0], lane, repository)
            jobs.append(projected)
            if lane == "APP":
                counts["app_total_jobs"] += 1
                counts["app_pre_identity_pass"] += 1
                counts["app_waiting_user_identity"] += projected["identity_status"] in (
                    "WAITING_USER_IDENTITY", "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE")
                counts["app_identity_received"] += projected["identity_status"] == "USER_IDENTITY_RECEIVED"
            else:
                counts["3d_total_jobs"] += 1
                counts["3d_pre_identity_pass"] += 1
                counts["3d_waiting_identity"] += projected["identity_status"] == "WAITING_USER_IDENTITY"
    return {"schema_version": 1, "status": "PRE_IDENTITY_ROTATION_PROJECTED__HEAD_UNVERIFIED",
            "jobs": jobs, "metrics": counts, "cas": "NOT_APPLIED",
            "local_execution": "NOT_PERFORMED", "store_submission": "NOT_AUTHORIZED"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = project(read_ledger(args.ledger))
        # This tool is read-only. A separate, reviewed scheduler owns private
        # queue writes and local single-job execution.
        print(json.dumps(result if not args.check_only else {
            "status": result["status"], "metrics": result["metrics"],
            "jobs": [{"request_id": x["request_id"],
                      "source_head_status": x["source_head_status"],
                      "identity_status": x["identity_status"]} for x in result["jobs"]],
            "cas": "NOT_APPLIED"}, sort_keys=True))
        return 0
    except (IntakeHold, OSError) as exc:
        print(json.dumps({"status": "HOLD_ROTATION_INTAKE",
                          "reason": str(exc), "cas": "NOT_APPLIED"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
