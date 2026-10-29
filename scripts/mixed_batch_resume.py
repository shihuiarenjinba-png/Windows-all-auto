"""Pure restart-safe state contract for a mixed PRE/POST APP Identity rotation.

This module is deliberately NOT an executable Partner Center worker. It makes
POST Identity jobs immutable SKIP entries and serializes the remaining PRE
jobs. The caller must hold the existing OS single-flight lock and persist
state through the existing atomic writer. No browser, GitHub, CAS, or Store
side effects occur here. Neither an injected verifier nor a receipt is a
substitute for a real Windows host or scheduled-trigger attestation.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Callable

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
EXPECTED_ORDER = (
    "focus-session-desk", "file-integrity-ledger",
    "offline-text-diff-desk", "offline-image-inventory-desk",
)
EXECUTION_ORIGINS = {
    "MANUAL_WINDOWS_TERMINAL", "WINDOWS_TASK_SCHEDULER",
    "WINDOWS_TASK_SCHEDULER_MANUAL_START",
}
POST_ACTION = "SKIP_IDENTITY_ALREADY_RETURNED"
PRE_ACTION = "LOCAL_OPERATOR_PENDING_REVIEWED_MIXED_RUNNER"


class MixedResumeHold(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise MixedResumeHold(code)


def _digest(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")).hexdigest()


def initialize(plan: dict, *, central_head_sha: str,
               execution_origin: str) -> dict:
    """Create a deterministic state; POST entries cannot be claimed for UI.

    The caller MUST first obtain a fresh independently audited GitHub plan.
    No trust is granted to a user-edited local plan by this pure function.
    """
    _require(isinstance(plan, dict)
             and plan.get("status") == "MIXED_ROTATION_DISPATCH_PLAN_READY"
             and plan.get("discovered_count") == 4
             and plan.get("local_windows_no_llm_pass") is False
             and plan.get("task_scheduler_registration_allowed") is False
             and plan.get("store_submission") == "NOT_PERFORMED"
             and plan.get("cas") == "NOT_PERFORMED",
             "HOLD_MIXED_RESUME_PLAN_UNTRUSTED")
    _require(isinstance(central_head_sha, str)
             and SHA40.fullmatch(central_head_sha) is not None,
             "HOLD_MIXED_RESUME_CENTRAL_HEAD")
    _require(execution_origin in EXECUTION_ORIGINS,
             "HOLD_MIXED_RESUME_ORIGIN")
    products = plan.get("products")
    _require(isinstance(products, list) and len(products) == 4
             and all(isinstance(x, dict) for x in products),
             "HOLD_MIXED_RESUME_DISCOVERY")
    _require(tuple(x.get("slug") for x in products) == EXPECTED_ORDER
             and [x.get("batch_index") for x in products] == [1, 2, 3, 4],
             "HOLD_MIXED_RESUME_ORDER")
    for key in ("request_id", "slug", "source_sha", "identity_return_target"):
        values = [x.get(key) for x in products]
        _require(all(isinstance(v, str) and bool(v) for v in values)
                 and len(set(values)) == 4, "HOLD_MIXED_RESUME_COLLISION")
    post = 0
    entries = []
    for item in products:
        slug = item["slug"]
        action = item.get("dispatch_action")
        _require(item.get("registration_type") == "MSIX_OR_PWA_APP"
                 and item.get("partner_center_selection") == "MSIX or PWA app"
                 and item.get("source_repository") ==
                     "shihuiarenjinba-png/AI-App-Factory"
                 and isinstance(item.get("source_branch"), str)
                 and item["source_branch"].startswith("codex/")
                 and SHA40.fullmatch(str(item.get("source_sha", ""))) is not None
                 and item.get("identity_return_target") ==
                     f"products/{slug}/store/approved-identity.json"
                 and item.get("identity_cas_authorized_by_plan") is False
                 and item.get("partner_center_creation_authorized_by_plan") is False,
                 "HOLD_MIXED_RESUME_BINDING")
        if action == POST_ACTION:
            _require(item.get("observed_identity_state") == "POST_IDENTITY_READY",
                     "HOLD_MIXED_RESUME_POST_CONFLICT")
            status = "SKIPPED_GITHUB_POST_VERIFIED"
            post += 1
        elif action == PRE_ACTION:
            _require(item.get("observed_identity_state") == "PRE_IDENTITY_READY",
                     "HOLD_MIXED_RESUME_PRE_CONFLICT")
            status = "PENDING"
        else:
            raise MixedResumeHold("HOLD_MIXED_RESUME_ACTION")
        entries.append({
            "batch_index": item["batch_index"],
            "slug": slug,
            "request_id": item["request_id"],
            "source_sha": item["source_sha"],
            "identity_return_target": item["identity_return_target"],
            "registration_type": item["registration_type"],
            "partner_center_selection": item["partner_center_selection"],
            "plan_job_digest": _digest(item),
            "status": status,
            "result": None,
        })
    _require(plan.get("post_identity_skip_count") == post
             and plan.get("pre_identity_pending_count") == 4 - post,
             "HOLD_MIXED_RESUME_COUNTS")
    return {
        "schema_version": 1,
        "central_head_sha": central_head_sha,
        "execution_origin": execution_origin,
        "plan_digest": _digest(plan),
        "discovered_count": 4,
        "active_request_id": None,
        "products": entries,
        "store_submission": "NOT_PERFORMED",
        "scheduled_trigger_proven": False,
    }


def validate_replay(state: dict, expected: dict) -> None:
    """Fail closed on changed central HEAD, plan, or persisted local state."""
    _require(isinstance(state, dict) and isinstance(expected, dict)
             and state.get("schema_version") == 1
             and state.get("central_head_sha") == expected.get("central_head_sha")
             and state.get("execution_origin") == expected.get("execution_origin")
             and state.get("plan_digest") == expected.get("plan_digest")
             and state.get("discovered_count") == 4
             and state.get("store_submission") == "NOT_PERFORMED"
             and state.get("scheduled_trigger_proven") is False,
             "HOLD_MIXED_RESUME_REPLAY_CONFLICT")
    actual, reference = state.get("products"), expected["products"]
    _require(isinstance(actual, list) and len(actual) == 4,
             "HOLD_MIXED_RESUME_REPLAY_CONFLICT")
    active = []
    for old, fresh in zip(actual, reference):
        _require(isinstance(old, dict)
                 and all(old.get(k) == fresh.get(k) for k in (
                     "batch_index", "slug", "request_id", "source_sha",
                     "identity_return_target", "registration_type",
                     "partner_center_selection", "plan_job_digest")),
                 "HOLD_MIXED_RESUME_REPLAY_CONFLICT")
        allowed = ({"SKIPPED_GITHUB_POST_VERIFIED"} if
                   fresh["status"] == "SKIPPED_GITHUB_POST_VERIFIED" else
                   {"PENDING", "ACTIVE", "IDENTITY_RETURN_VERIFIED",
                    "HOLD_NAME_UNAVAILABLE"})
        _require(old.get("status") in allowed,
                 "HOLD_MIXED_RESUME_REPLAY_CONFLICT")
        if old["status"] == "ACTIVE":
            active.append(old["request_id"])
        if old["status"] == "SKIPPED_GITHUB_POST_VERIFIED":
            _require(old.get("result") is None,
                     "HOLD_MIXED_RESUME_POST_MUTATION")
        if old["status"] == "IDENTITY_RETURN_VERIFIED":
            _require(isinstance(old.get("result"), dict)
                     and old["result"].get("request_id") == old["request_id"]
                     and old["result"].get("source_sha") == old["source_sha"]
                     and old["result"].get("store_submission") == "NOT_PERFORMED",
                     "HOLD_MIXED_RESUME_REPLAY_CONFLICT")
    _require(len(active) <= 1
             and state.get("active_request_id") ==
                 (active[0] if active else None),
             "HOLD_MIXED_RESUME_CONCURRENT_ACTIVE")


def claim_next(state: dict) -> tuple[dict, dict | None]:
    """Resume an ACTIVE job or claim the first pending PRE job, never POST."""
    updated = deepcopy(state)
    active = [x for x in updated["products"] if x["status"] == "ACTIVE"]
    _require(len(active) <= 1
             and updated.get("active_request_id") ==
                 (active[0]["request_id"] if active else None),
             "HOLD_MIXED_RESUME_CONCURRENT_ACTIVE")
    if active:
        return updated, deepcopy(active[0])
    for entry in updated["products"]:
        if entry["status"] == "PENDING":
            entry["status"] = "ACTIVE"
            updated["active_request_id"] = entry["request_id"]
            return updated, deepcopy(entry)
    return updated, None


def complete_active(state: dict, result: dict, *,
                    independent_evidence_verifier: Callable[[dict, dict], bool]
                    | None) -> dict:
    """Accept an exact CAS+replay only after an independent local verifier.

    The verifier must check actual authenticated UI and fresh GitHub return
    against the exact queue job. No receipt-provided self-assertion suffices.
    """
    updated = deepcopy(state)
    _require(callable(independent_evidence_verifier)
             and isinstance(result, dict), "HOLD_MIXED_RESUME_NO_VERIFIER")
    matches = [x for x in updated["products"]
               if x["status"] == "ACTIVE"
               and x["request_id"] == updated.get("active_request_id")]
    _require(len(matches) == 1, "HOLD_MIXED_RESUME_NO_ACTIVE_JOB")
    entry = matches[0]
    for key in ("request_id", "source_sha", "identity_return_target",
                "registration_type", "partner_center_selection",
                "plan_job_digest"):
        _require(result.get(key) == entry[key],
                 "HOLD_MIXED_RESUME_RESULT_BINDING")
    _require(result.get("github_return_status") in
             {"APPLIED", "EXISTING_VERIFIED"}
             and result.get("github_replay_status") == "EXISTING_VERIFIED"
             and result.get("identity_capture_status") ==
                 "IDENTITY_CAPTURED__AUTHENTICATED_UI__GITHUB_BOUND"
             and SHA40.fullmatch(str(result.get("identity_return_commit_sha", "")))
                 is not None
             and isinstance(result.get("store_id"), str)
             and bool(result["store_id"])
             and isinstance(result.get("pfn"), str) and bool(result["pfn"])
             and isinstance(result.get("package_sid"), str)
             and bool(result["package_sid"])
             and result.get("store_submission") == "NOT_PERFORMED"
             and result.get("package_version_gate") == "HOLD"
             and result.get("duplicate_creation") == 0
             and result.get("cross_product_contamination") == 0,
             "HOLD_MIXED_RESUME_RESULT_UNVERIFIED")
    for other in updated["products"]:
        if other is entry or other.get("result") is None:
            continue
        _require(other["result"].get("store_id") != result["store_id"]
                 and other["result"].get("pfn") != result["pfn"],
                 "HOLD_MIXED_RESUME_CROSS_PRODUCT_IDENTITY")
    _require(independent_evidence_verifier(deepcopy(entry), deepcopy(result)) is True,
             "HOLD_MIXED_RESUME_INDEPENDENT_EVIDENCE")
    entry["status"] = "IDENTITY_RETURN_VERIFIED"
    entry["result"] = deepcopy(result)
    updated["active_request_id"] = None
    return updated


def hold_name_unavailable(state: dict, *, request_id: str,
                          verified_name_unavailable: bool) -> dict:
    """Only an independently confirmed pre-Reserve name conflict may skip."""
    updated = deepcopy(state)
    _require(verified_name_unavailable is True,
             "HOLD_MIXED_RESUME_UNTRUSTED_NAME_CONFLICT")
    active = [x for x in updated["products"]
              if x["status"] == "ACTIVE"
              and x["request_id"] == request_id
              and x["request_id"] == updated.get("active_request_id")]
    _require(len(active) == 1, "HOLD_MIXED_RESUME_NO_ACTIVE_JOB")
    active[0]["status"] = "HOLD_NAME_UNAVAILABLE"
    active[0]["result"] = {"error_code": "HOLD_NAME_UNAVAILABLE",
                           "store_submission": "NOT_PERFORMED"}
    updated["active_request_id"] = None
    return updated


def summary(state: dict) -> dict:
    """Return PARTIAL/READY_FOR_HOST_ATTESTATION, never a fake batch PASS."""
    statuses = [x["status"] for x in state["products"]]
    success = sum(x in {"SKIPPED_GITHUB_POST_VERIFIED",
                        "IDENTITY_RETURN_VERIFIED"} for x in statuses)
    holds = sum(x == "HOLD_NAME_UNAVAILABLE" for x in statuses)
    pending = sum(x in {"PENDING", "ACTIVE"} for x in statuses)
    _require(success + holds + pending == 4,
             "HOLD_MIXED_RESUME_STATUS")
    return {
        "status": ("MIXED_LOCAL_COMPLETE_AWAITING_HOST_ATTESTATION"
                   if success == 4 else "MULTI_PRODUCT_IDENTITY_BATCH_PARTIAL"),
        "discovered_count": 4,
        "github_post_identity_skipped": statuses.count("SKIPPED_GITHUB_POST_VERIFIED"),
        "new_local_identity_returns": statuses.count("IDENTITY_RETURN_VERIFIED"),
        "success_count": success,
        "hold_count": holds,
        "pending_count": pending,
        "next_resume_index": next(
            (x["batch_index"] for x in state["products"]
             if x["status"] in {"PENDING", "ACTIVE"}), None),
        "local_windows_no_llm_pass": False,
        "multi_product_identity_batch_pass": False,
        "scheduled_trigger_proven": False,
        "task_scheduler_registration_allowed": False,
        "store_submission": "NOT_PERFORMED",
    }
