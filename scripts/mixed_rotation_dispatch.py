"""Read-only, fail-closed dispatch plan for a mixed APP Identity rotation.

Consumes the independently verified live-GitHub mixed rotation audit. It never
opens Partner Center, downloads artifacts, performs CAS, writes the central
ledger, or grants permission to register a local scheduled task. In particular,
a POST_IDENTITY_READY product is never queued for a second product creation.
"""
from __future__ import annotations

from copy import deepcopy

ORDER = (
    "focus-session-desk",
    "file-integrity-ledger",
    "offline-text-diff-desk",
    "offline-image-inventory-desk",
)


class PlanHold(ValueError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise PlanHold(code)


def build_dispatch_plan(ledger: dict, audit: dict) -> dict:
    """Convert independent GitHub evidence into a non-executable queue plan.

    A plan is NOT a local Windows execution receipt, Partner Center proof, CAS
    authorization, or permission to register the 12-hour scheduled task.
    """
    require(isinstance(ledger, dict) and isinstance(audit, dict),
            "HOLD_MIXED_PLAN_SCHEMA")
    require(audit.get("status") == "MIXED_ROTATION_AUDITED"
            and audit.get("discovered_count") == 4
            and audit.get("local_windows_no_llm_pass") is False
            and audit.get("local_partner_center_operator_pass") is False
            and audit.get("local_batch_runner_ready") is False
            and audit.get("store_submission") == "NOT_PERFORMED"
            and audit.get("cas") == "NOT_PERFORMED",
            "HOLD_MIXED_AUDIT_NOT_INDEPENDENT")
    jobs = (ledger.get("rotation_cohorts") or {}).get("app_jobs")
    records = (ledger.get("multi_product_partner_center_batch_4") or {}).get("products")
    evidence = audit.get("products")
    require(all(isinstance(x, list) and len(x) == 4
                for x in (jobs, records, evidence)),
            "HOLD_MIXED_PLAN_DISCOVERY")
    require(all(isinstance(item, dict)
                for collection in (jobs, records, evidence)
                for item in collection),
            "HOLD_MIXED_PLAN_SCHEMA")
    require(tuple(x.get("slug") for x in jobs) == ORDER
            and tuple(x.get("slug") for x in records) == ORDER
            and tuple(x.get("slug") for x in evidence) == ORDER,
            "HOLD_MIXED_PLAN_ORDER")
    require([x.get("batch_index") for x in records] == [1, 2, 3, 4]
            and [x.get("batch_index") for x in evidence] == [1, 2, 3, 4],
            "HOLD_MIXED_PLAN_INDEX")
    all_jobs = list(jobs)
    for collection, lane in (("three_d_jobs", "GAME_3D"), ("game_jobs", "GAME")):
        other = (ledger.get("rotation_cohorts") or {}).get(collection, [])
        require(isinstance(other, list), "HOLD_MIXED_PLAN_LANE")
        for item in other:
            require(isinstance(item, dict) and item.get("product_type") == lane,
                    "HOLD_MIXED_PLAN_LANE")
            all_jobs.append(item)
    for key in ("request_id", "slug", "identity_return_target"):
        values = [item.get(key) for item in all_jobs]
        require(all(isinstance(v, str) and v for v in values)
                and len(set(values)) == len(values),
                "HOLD_MIXED_PLAN_CROSS_PRODUCT")
    tasks, seen_ids, post_count = [], set(), 0
    for index, (job, record, proof) in enumerate(zip(jobs, records, evidence), 1):
        require(all(isinstance(x, dict) for x in (job, record, proof)),
                "HOLD_MIXED_PLAN_SCHEMA")
        slug = ORDER[index - 1]
        require(job.get("product_type") == "APP"
                and job.get("registration_type") == "MSIX_OR_PWA_APP"
                and job.get("partner_center_selection") == "MSIX or PWA app"
                and job.get("source_repository") == "shihuiarenjinba-png/AI-App-Factory"
                and job.get("identity_return_target") ==
                    f"products/{slug}/store/approved-identity.json",
                "HOLD_MIXED_PLAN_ROUTING")
        for key in ("slug", "request_id", "source_repository", "source_branch",
                    "source_sha"):
            require(record.get(key) == job.get(key),
                    "HOLD_MIXED_PLAN_BATCH_BINDING")
        require(proof.get("slug") == slug
                and proof.get("request_id") == job.get("request_id"),
                "HOLD_MIXED_PLAN_AUDIT_BINDING")
        status = job.get("status")
        if status == "POST_IDENTITY_READY":
            require(proof.get("status") == "POST_IDENTITY_GITHUB_VERIFIED"
                    and proof.get("return_commit_sha") ==
                        job.get("identity_return_commit_sha")
                    and proof.get("store_id") == job.get("identity_store_id")
                    and job.get("package_version_gate") == "HOLD"
                    and proof.get("next_gate") == "PACKAGE_VERSION_HOLD",
                    "HOLD_MIXED_PLAN_POST_CONFLICT")
            store_id = proof["store_id"]
            require(isinstance(store_id, str) and store_id
                    and store_id not in seen_ids,
                    "HOLD_MIXED_PLAN_IDENTITY_COLLISION")
            seen_ids.add(store_id)
            post_count += 1
            action = "SKIP_IDENTITY_ALREADY_RETURNED"
            next_gate = "PACKAGE_VERSION_AND_ASSET_APPROVAL_HOLD"
        elif status == "PRE_IDENTITY_READY":
            require(proof.get("status") == "PRE_IDENTITY_GITHUB_VERIFIED"
                    and proof.get("source_sha") == job.get("source_sha")
                    and proof.get("next_gate") == "LOCAL_OPERATOR_REQUIRED",
                    "HOLD_MIXED_PLAN_PRE_CONFLICT")
            action = "LOCAL_OPERATOR_PENDING_REVIEWED_MIXED_RUNNER"
            next_gate = "LOCAL_EXACT_SOURCE_AND_AUTHENTICATED_UI_RECEIPT"
        else:
            raise PlanHold("HOLD_MIXED_PLAN_UNKNOWN_STATUS")
        tasks.append({
            "batch_index": index,
            "slug": slug,
            "request_id": job["request_id"],
            "source_repository": job["source_repository"],
            "source_branch": job["source_branch"],
            "source_sha": job["source_sha"],
            "identity_return_target": job["identity_return_target"],
            "registration_type": job["registration_type"],
            "partner_center_selection": job["partner_center_selection"],
            "observed_identity_state": status,
            "dispatch_action": action,
            "next_gate": next_gate,
            "identity_cas_authorized_by_plan": False,
            "partner_center_creation_authorized_by_plan": False,
        })
    require(audit.get("post_identity_github_verified") == post_count
            and audit.get("pre_identity_github_verified") == 4 - post_count,
            "HOLD_MIXED_PLAN_COUNT_CONFLICT")
    return {
        "status": "MIXED_ROTATION_DISPATCH_PLAN_READY",
        "discovered_count": 4,
        "post_identity_skip_count": post_count,
        "pre_identity_pending_count": 4 - post_count,
        "no_identity_work_in_github_queue": post_count == 4,
        "products": deepcopy(tasks),
        "existing_legacy_runner_ready": False,
        "mixed_state_local_runner_ready": False,
        "task_scheduler_registration_allowed": False,
        "local_windows_no_llm_pass": False,
        "multi_product_identity_batch_pass": False,
        "local_ui_and_replay": "NOT_VERIFIED_BY_THIS_PLAN",
        "store_submission": "NOT_PERFORMED",
        "package_upload": "NOT_PERFORMED",
        "cas": "NOT_PERFORMED",
        "next_action": (
            "REVIEW_AND_TEST_MIXED_STATE_RESUMABLE_LOCAL_RUNNER"
            if post_count < 4 else
            "PACKAGE_VERSION_GATES_AND_INDEPENDENT_LOCAL_RECEIPT_AUDIT"
        ),
    }
