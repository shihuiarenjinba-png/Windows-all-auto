"""Fail-closed APP (up to five) and one 3D PRE-IDENTITY rotation queue.

Reads only the central handoff ledger. No Partner Center access, CAS, package
download, Identity materialization, or local GUI/install actions. Jobs remain
one-at-a-time in the existing local scheduler; queue storage may be multi-job.
"""
from __future__ import annotations

import re

from scripts import local_identity_scheduler as scheduler
from scripts import pre_identity_queue
from scripts import registration_router

TARGET = "%LOCALAPPDATA%/FactoryIdentityWorker/secure/<request_id>/official-identity.json"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
READY = "PRE_IDENTITY_READY"
IDENTITY_STATES = {"WAITING_USER_IDENTITY", "USER_IDENTITY_RECEIVED"}
APP_REPO = scheduler.OWNER + "/AI-App-Factory"
THREE_D_REPO = scheduler.OWNER + "/3d-game-factory"


def require(ok: bool, reason: str):
    if not ok:
        raise pre_identity_queue.QueueHold(reason)


def _items(ledger: dict, lane: str) -> list[dict]:
    cohort = ledger.get("rotation_cohorts") or {}
    values = cohort.get(lane, [])
    require(isinstance(values, list), "ROTATION_LIST_INVALID")
    require(len(values) <= (5 if lane == "app_jobs" else 1), "ROTATION_CAP_EXCEEDED")
    require(all(isinstance(x, dict) for x in values), "ROTATION_JOB_INVALID")
    return values


def _rotation_job(item: dict, requests: list[dict], head_reader) -> dict:
    lane = item.get("product_type")
    require(lane in {"APP", "GAME_3D"}, "ROTATION_LANE_INVALID")
    repo = APP_REPO if lane == "APP" else THREE_D_REPO
    kind = "APP_CANARY" if lane == "APP" else "GAME_3D_CANARY"
    rid, sha = item.get("request_id"), item.get("source_sha")
    branch, slug = item.get("source_branch"), item.get("slug")
    build_branch, build_sha = item.get("factory_build_branch"), item.get("factory_build_head")
    digest = item.get("expected_exe_sha256")
    require(item.get("source_repository") == repo
            and isinstance(rid, str) and scheduler.REQUEST.fullmatch(rid) is not None
            and isinstance(sha, str) and scheduler.SHA.fullmatch(sha) is not None
            and isinstance(branch, str) and scheduler.BRANCH.fullmatch(branch) is not None
            and isinstance(slug, str) and SLUG.fullmatch(slug) is not None
            and isinstance(build_branch, str) and scheduler.BRANCH.fullmatch(build_branch) is not None
            and isinstance(build_sha, str) and scheduler.SHA.fullmatch(build_sha) is not None
            and isinstance(digest, str) and scheduler.HASH.fullmatch(digest) is not None,
            "ROTATION_PROVENANCE_INCOMPLETE")
    require(item.get("artifact_provenance") == "REAL_WINDOWS_EXPORT_VERIFIED",
            "ROTATION_ARTIFACT_NOT_VERIFIED")
    require(head_reader(repo, branch) == sha, "ROTATION_SOURCE_HEAD_CONFLICT")
    require(head_reader(repo, build_branch) == build_sha, "ROTATION_BUILD_HEAD_CONFLICT")
    if lane == "GAME_3D":
        require(item.get("packaging_strategy") == "GODOT_WINDOWS_EXE_PCK_MAKEAPPX_MSIX",
                "THREE_D_PACKAGING_EVIDENCE_MISSING")
        require(item.get("registration_type") == "MSIX_OR_PWA_GAME",
                "THREE_D_REGISTRATION_CONFLICT")
    registration, selection = registration_router.resolve(
        "APP" if lane == "APP" else "GAME", slug,
        item.get("packaging_family"), item.get("registration_type"))
    require(item.get("partner_center_selection") == selection,
            "ROTATION_SELECTION_CONFLICT")
    matched = [x for x in requests if x.get("request_id") == rid]
    require(len(matched) == 1, "ROTATION_IDENTITY_REQUEST_MISSING_OR_DUPLICATE")
    request = matched[0]
    require(request.get("status") in IDENTITY_STATES
            and request.get("repo") == repo
            and request.get("source_branch") == branch
            and request.get("source_sha") == sha
            and request.get("slug") == slug
            and request.get("product_type") == lane
            and request.get("identity_target") == TARGET,
            "ROTATION_IDENTITY_CROSS_PRODUCT_CONFLICT")
    return {
        "kind": kind, "request_id": rid, "repository": repo, "branch": branch,
        "source_sha": sha, "slug": slug, "product_type": lane,
        "factory_build_branch": build_branch, "factory_build_head": build_sha,
        "package_path": None, "package_sha256": digest,
        "identity_target": TARGET, "registration_type": registration,
        "partner_center_selection": selection,
        "identity_status": request["status"],
    }


def project(ledger: dict, head_reader=scheduler.head) -> dict:
    """Return the base Signal Sprint queue plus independently bound rotation jobs.

    A partial or conflicting READY job fails the *whole draft*, never silently
    routes Identity to a different product. Not-ready jobs remain deferred.
    """
    result = pre_identity_queue.project(ledger, head_reader)
    requests = (ledger.get("user_id_requests") or {}).get("items") or []
    require(isinstance(requests, list), "ROTATION_IDENTITY_REQUESTS_INVALID")
    app_items = _items(ledger, "app_jobs")
    base_apps = [job for job in result["jobs"] if job["kind"] == "APP_CANARY"]
    require(len(app_items) + len(base_apps) <= 5, "ROTATION_CAP_EXCEEDED")
    three_d_items = _items(ledger, "three_d_jobs")
    jobs = list(result["jobs"])
    deferred = list(result["deferred"])
    metrics = {
        "total_jobs": len(app_items) + len(base_apps),
        "pre_identity_pass": len(base_apps),
        "waiting_user_identity": sum(1 for j in base_apps if any(
            r.get("request_id") == j["request_id"] and r.get("status") == "WAITING_USER_IDENTITY"
            for r in requests)),
        "identity_received": sum(1 for j in base_apps if any(
            r.get("request_id") == j["request_id"] and r.get("status") == "USER_IDENTITY_RECEIVED"
            for r in requests)),
        "conflicts": 0, "retries": 0, "artifact_mismatch": 0,
        "schema_conflict": 0, "cross_product_rejection": 0,
        "3d_total_jobs": len(three_d_items), "3d_pre_identity_pass": 0,
        "3d_waiting_identity": 0, "3d_conflicts": 0,
        "3d_artifact_mismatch": 0,
    }
    seen = {(j["request_id"], j["repository"], j["branch"], j["source_sha"], j.get("slug"))
            for j in jobs}
    seen_ids = {j["request_id"] for j in jobs}
    for lane, items in (("APP", app_items), ("GAME_3D", three_d_items)):
        for item in items:
            if item.get("status") != READY:
                require(item.get("status") in {"CANDIDATE", "BUILD", "EXPORT_PENDING"},
                        "ROTATION_STATUS_INVALID")
                deferred.append({"product_name": item.get("display_name"),
                                 "registration_type": item.get("registration_type"),
                                 "status": "NOT_YET_REQUIRED",
                                 "reason": "PRE_IDENTITY_EVIDENCE_PENDING"})
                continue
            job = _rotation_job(item, requests, head_reader)
            key = (job["request_id"], job["repository"], job["branch"],
                   job["source_sha"], job["slug"])
            require(key not in seen and job["request_id"] not in seen_ids,
                    "ROTATION_DUPLICATE_OR_CROSS_PRODUCT_REQUEST")
            seen.add(key)
            seen_ids.add(job["request_id"])
            jobs.append(job)
            if lane == "APP":
                metrics["pre_identity_pass"] += 1
                metrics["waiting_user_identity"] += job["identity_status"] == "WAITING_USER_IDENTITY"
                metrics["identity_received"] += job["identity_status"] == "USER_IDENTITY_RECEIVED"
            else:
                metrics["3d_pre_identity_pass"] += 1
                metrics["3d_waiting_identity"] += job["identity_status"] == "WAITING_USER_IDENTITY"
    scheduler.validate_jobs({"jobs": jobs})
    for job in jobs:
        registration_router.validate_handoff_job(job)
    result["jobs"], result["deferred"] = jobs, deferred
    result["rotation_metrics"] = metrics
    result["ready_for_cas"] = False
    return result


def main(argv=None) -> int:
    """Build a create-only private rotation draft; check-only has no writes."""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Multi-APP and 3D PRE-IDENTITY rotation")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.check_only and args.output is None:
        parser.error("--output required unless --check-only")
    try:
        central_sha = scheduler.head(scheduler.CENTRAL_REPO, scheduler.CENTRAL_BRANCH)
        ledger, _ = scheduler.remote_json(scheduler.CENTRAL_REPO,
                                          scheduler.CENTRAL_PATH, central_sha)
        draft = project(ledger)
        require(scheduler.head(scheduler.CENTRAL_REPO, scheduler.CENTRAL_BRANCH)
                == central_sha, "CENTRAL_LEDGER_HEAD_CHANGED")
        if not args.check_only:
            pre_identity_queue.write_new_private_file(args.output, draft)
        response = {"status": "PRE_IDENTITY_ROTATION_DRAFT",
                    "jobs": len(draft["jobs"]),
                    "deferred": len(draft["deferred"]),
                    "rotation_metrics": draft["rotation_metrics"],
                    "identity_acquisition": "USER_ONLY", "cas": "NOT_APPLIED"}
        code = 0
    except (pre_identity_queue.QueueHold, scheduler.Hold,
            registration_router.RegistrationHold) as exc:
        response = {"status": "HOLD", "reason": str(exc), "cas": "NOT_APPLIED"}
        code = 2
    except (OSError, ValueError, TypeError):
        response = {"status": "HOLD", "reason": "INPUT_OR_REMOTE_ERROR",
                    "cas": "NOT_APPLIED"}
        code = 2
    print(json.dumps(response, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
