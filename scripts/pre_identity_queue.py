"""Build a secret-free PRE-IDENTITY job queue from the live central E2E ledger.

This never obtains Identity, downloads packages, performs CAS or changes a
Factory branch. The output is a draft: local package_path must be supplied
and checked independently before the handoff scheduler can process it.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts import local_identity_scheduler as scheduler
from scripts import registration_router


class QueueHold(Exception):
    pass


def require(condition: bool, reason: str):
    if not condition:
        raise QueueHold(reason)


def project(ledger: dict, head_reader=scheduler.head) -> dict:
    require(ledger.get("e2e_pass") is False and ledger.get("new_product_allowed") is False,
            "CENTRAL_LEDGER_SAFETY_GATE")
    product = ledger.get("active_product")
    require(isinstance(product, dict), "GAME_ACTIVE_PRODUCT_MISSING")
    sha = product.get("source_sha")
    rid = product.get("request_id")
    require(isinstance(sha, str) and scheduler.SHA.fullmatch(sha) is not None,
            "GAME_SOURCE_SHA_INVALID")
    require(rid == "game-signal-sprint-" + sha, "GAME_REQUEST_ID_MISMATCH")
    require(product.get("product_type") == "GAME"
            and product.get("slug") == "signal-sprint"
            and product.get("source_repository") == scheduler.OWNER + "/AI-Game-Factory"
            and product.get("source_branch") == "codex/game-signal-sprint-undo-20261027"
            and product.get("expected_head_sha") == sha,
            "GAME_SOURCE_BINDING_MISMATCH")
    require(head_reader(product["source_repository"], product["source_branch"]) == sha,
            "GAME_SOURCE_HEAD_CONFLICT")
    exe = product.get("local_execution_result") or {}
    exe_sha = exe.get("package_sha256")
    require(exe.get("package_kind") == "exe"
            and exe.get("package_status") == "INSPECTED"
            and isinstance(exe_sha, str)
            and scheduler.HASH.fullmatch(exe_sha) is not None
            and product.get("factory_exe_artifact_kind") == "EXE_QA_UNSIGNED_NOT_MSIX",
            "GAME_EXE_PROVENANCE_NOT_READY")
    provisioner = product.get("provisioner_repository")
    provisioner_branch = product.get("provisioner_branch")
    provisioner_sha = product.get("provisioner_head_observed")
    require(provisioner == scheduler.OWNER + "/Repository-Provisioner-game"
            and isinstance(provisioner_branch, str)
            and scheduler.BRANCH.fullmatch(provisioner_branch) is not None
            and isinstance(provisioner_sha, str)
            and scheduler.SHA.fullmatch(provisioner_sha) is not None,
            "GAME_PROVISIONER_BINDING_INVALID")
    require(head_reader(provisioner, provisioner_branch) == provisioner_sha,
            "GAME_PROVISIONER_HEAD_CONFLICT")
    requests = ledger.get("user_id_requests") or {}
    items = requests.get("items") or []
    matching = [item for item in items if item.get("request_id") == rid]
    require(len(matching) == 1
            and matching[0].get("status") in {"WAITING_USER_IDENTITY", "USER_IDENTITY_RECEIVED"},
            "USER_ID_REQUEST_NOT_CORRELATED")
    identity_request = matching[0]
    require(identity_request.get("repo") == product["source_repository"]
            and identity_request.get("source_branch") == product["source_branch"]
            and identity_request.get("source_sha") == sha
            and identity_request.get("identity_target")
                == "%LOCALAPPDATA%/FactoryIdentityWorker/secure/<request_id>/official-identity.json",
            "USER_ID_REQUEST_BINDING_MISMATCH")
    game_registration, game_selection = registration_router.resolve(
        "GAME", "signal-sprint", product.get("packaging_family"),
        product.get("registration_type"))
    game = {
        "kind": "GAME_SIGNAL_SPRINT",
        "registration_type": game_registration,
        "partner_center_selection": game_selection,
        "request_id": rid,
        "repository": product["source_repository"],
        "branch": product["source_branch"],
        "source_sha": sha,
        "package_path": None,
        "package_sha256": exe_sha,
        "identity_target": matching[0]["identity_target"],
        "provisioner_repository": provisioner,
        "provisioner_branch": provisioner_branch,
        "provisioner_head_sha": provisioner_sha,
    }
    jobs = [game]
    app = (ledger.get("other_lanes") or {}).get("APP") or {}
    candidate = app.get("canary_proposal") or {}
    deferred = []
    if candidate.get("source_sha") is None or candidate.get("request_id") is None:
        app_registration, app_selection = registration_router.resolve(
            "APP", "offline-notes-canary", candidate.get("packaging_family"),
            candidate.get("registration_type"))
        deferred.append({"product_name": "Offline Notes Canary",
                         "registration_type": app_registration,
                         "partner_center_selection": app_selection,
                         "status": "NOT_YET_REQUIRED",
                         "reason": "APP_NOT_FORMALLY_PROMOTED_WITH_EXE"})
    else:
        app_sha, app_rid = candidate["source_sha"], candidate["request_id"]
        app_exe = candidate.get("exe_sha256")
        require(candidate.get("slug") == "offline-notes-canary"
                and candidate.get("status") == "PROMOTED"
                and isinstance(app_sha, str) and scheduler.SHA.fullmatch(app_sha) is not None
                and isinstance(app_rid, str) and scheduler.REQUEST.fullmatch(app_rid) is not None
                and isinstance(app_exe, str) and scheduler.HASH.fullmatch(app_exe) is not None,
                "APP_PROMOTION_BINDING_INCOMPLETE")
        app_repo = scheduler.OWNER + "/AI-App-Factory"
        app_branch = candidate.get("branch")
        require(isinstance(app_branch, str)
                and scheduler.BRANCH.fullmatch(app_branch) is not None
                and head_reader(app_repo, app_branch) == app_sha,
                "APP_SOURCE_HEAD_CONFLICT")
        app_requests = [item for item in items if item.get("request_id") == app_rid]
        require(len(app_requests) == 1
                and app_requests[0].get("status") in {"WAITING_USER_IDENTITY", "USER_IDENTITY_RECEIVED"},
                "APP_USER_ID_REQUEST_NOT_CORRELATED")
        app_request = app_requests[0]
        require(app_request.get("repo") == app_repo
                and app_request.get("source_branch") == app_branch
                and app_request.get("source_sha") == app_sha
                and app_request.get("identity_target")
                    == "%LOCALAPPDATA%/FactoryIdentityWorker/secure/<request_id>/official-identity.json",
                "APP_USER_ID_REQUEST_BINDING_MISMATCH")
        app_registration, app_selection = registration_router.resolve(
            "APP", "offline-notes-canary", candidate.get("packaging_family"),
            candidate.get("registration_type"))
        jobs.append({"kind": "APP_CANARY", "request_id": app_rid,
                     "registration_type": app_registration,
                     "partner_center_selection": app_selection,
                     "repository": app_repo, "branch": app_branch,
                     "source_sha": app_sha, "package_path": None,
                     "package_sha256": app_exe,
                     "identity_target": app_request["identity_target"]})
    for job in jobs:
        registration_router.validate_handoff_job(job)
    scheduler.validate_jobs({"jobs": jobs})
    return {"schema_version": 1, "jobs": jobs, "deferred": deferred,
            "identity_acquisition": "USER_ONLY",
            "cas": "DELEGATED_TO_EXISTING_PROVISIONER",
            "ready_for_cas": False}


def write_new_private_file(path: Path, data: dict):
    path = scheduler.safe_local(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never overwrite a local operator's existing/unpushed queue.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise QueueHold("OUTPUT_EXISTS_NO_OVERWRITE") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Secret-free PRE-IDENTITY queue draft")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.check_only and args.output is None:
        parser.error("--output required unless --check-only")
    try:
        ledger_sha = scheduler.head(scheduler.CENTRAL_REPO, scheduler.CENTRAL_BRANCH)
        ledger, _ = scheduler.remote_json(scheduler.CENTRAL_REPO,
                                          scheduler.CENTRAL_PATH, ledger_sha)
        queue = project(ledger)
        require(scheduler.head(scheduler.CENTRAL_REPO, scheduler.CENTRAL_BRANCH) == ledger_sha,
                "CENTRAL_LEDGER_HEAD_CHANGED")
        if not args.check_only:
            write_new_private_file(args.output, queue)
        result = {"status": "PRE_IDENTITY_QUEUE_DRAFT",
                  "jobs": len(queue["jobs"]),
                  "deferred": queue["deferred"],
                  "local_exe_verification": "PENDING",
                  "identity": "WAITING_USER_IDENTITY",
                  "cas": "NOT_APPLIED"}
    except (QueueHold, scheduler.Hold, registration_router.RegistrationHold) as exc:
        result = {"status": "HOLD", "reason": str(exc), "cas": "NOT_APPLIED"}
    except (OSError, ValueError, TypeError):
        result = {"status": "HOLD", "reason": "LOCAL_OR_REMOTE_INPUT_ERROR",
                  "cas": "NOT_APPLIED"}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PRE_IDENTITY_QUEUE_DRAFT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
