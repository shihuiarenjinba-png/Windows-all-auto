"""Fail-closed rebase after the central single writer reconciles an Identity return.

The four-product mixed queue changes central HEAD when the 36-minute owner
promotes a verified CAS return to POST_IDENTITY_READY. A persisted local PRE
resume state cannot simply be reused with the new plan digest. This module
permits only monotonic PRE -> GitHub-verified POST transitions and requires an
independent verifier for every locally completed return.

Callers MUST obtain the new plan from the live-GitHub audit, hold the existing
Windows single-flight OS lock, and atomically persist the result. This pure
helper never opens a browser, performs CAS, writes the central ledger, or
authorizes Store submission or Task Scheduler registration.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Callable

from scripts import mixed_batch_resume as resume

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
BINDING_KEYS = (
    "batch_index", "slug", "request_id", "source_sha",
    "identity_return_target", "registration_type",
    "partner_center_selection",
)


class RebaseHold(ValueError):
    pass


def require(ok: bool, code: str) -> None:
    if not ok:
        raise RebaseHold(code)


def _verified_return(entry: dict, result: dict) -> None:
    require(isinstance(result, dict), "HOLD_REBASE_RETURN_EVIDENCE")
    for key in ("request_id", "source_sha", "identity_return_target",
                "registration_type", "partner_center_selection",
                "plan_job_digest"):
        require(result.get(key) == entry.get(key),
                "HOLD_REBASE_RETURN_BINDING")
    require(
        result.get("github_return_status") in {"APPLIED", "EXISTING_VERIFIED"}
        and result.get("github_replay_status") == "EXISTING_VERIFIED"
        and result.get("identity_capture_status") ==
            "IDENTITY_CAPTURED__AUTHENTICATED_UI__GITHUB_BOUND"
        and isinstance(result.get("identity_return_commit_sha"), str)
        and SHA40.fullmatch(result["identity_return_commit_sha"]) is not None
        and all(isinstance(result.get(k), str) and result[k]
                for k in ("store_id", "pfn", "package_sid"))
        and result.get("package_version_gate") == "HOLD"
        and result.get("store_submission") == "NOT_PERFORMED"
        and result.get("duplicate_creation") == 0
        and result.get("cross_product_contamination") == 0,
        "HOLD_REBASE_RETURN_EVIDENCE",
    )


def rebase_after_reconciliation(
    previous: dict,
    fresh_plan: dict,
    *,
    new_central_head_sha: str,
    execution_origin: str,
    independent_return_verifier: Callable[[dict, dict, dict], bool] | None,
    independent_name_hold_verifier: Callable[[dict], bool] | None = None,
) -> dict:
    """Rebind a local state to an independently audited newer central plan.

    A previously completed PRE return may become POST only if the fresh plan
    confirms it and the verifier independently rechecks authenticated UI and
    GitHub approved-identity/return commit. Self-asserted JSON is insufficient.
    Other PRE jobs keep their exact plan-job digests; no cross-product reset,
    implicit retry, or backward POST -> PRE transition is permitted.

    The verifier receives (old_entry, old_result, fresh_entry). It must not
    merely trust the persisted receipt or the new plan's status label.
    """
    expected = resume.initialize(
        fresh_plan,
        central_head_sha=new_central_head_sha,
        execution_origin=execution_origin,
    )
    require(
        isinstance(previous, dict)
        and previous.get("schema_version") == 1
        and isinstance(previous.get("central_head_sha"), str)
        and SHA40.fullmatch(previous["central_head_sha"]) is not None
        and isinstance(previous.get("plan_digest"), str)
        and SHA64.fullmatch(previous["plan_digest"]) is not None
        and previous.get("execution_origin") == execution_origin
        and previous.get("discovered_count") == 4
        and previous.get("store_submission") == "NOT_PERFORMED"
        and previous.get("scheduled_trigger_proven") is False,
        "HOLD_REBASE_OLD_STATE_UNTRUSTED",
    )
    old_entries = previous.get("products")
    require(isinstance(old_entries, list) and len(old_entries) == 4
            and all(isinstance(x, dict) for x in old_entries),
            "HOLD_REBASE_OLD_STATE_UNTRUSTED")
    active = []
    store_ids = set()
    rebased = deepcopy(expected)
    for old, fresh in zip(old_entries, rebased["products"]):
        require(all(old.get(key) == fresh.get(key) for key in BINDING_KEYS),
                "HOLD_REBASE_CROSS_PRODUCT_BINDING")
        old_status, fresh_status = old.get("status"), fresh["status"]
        if old_status == "SKIPPED_GITHUB_POST_VERIFIED":
            require(fresh_status == "SKIPPED_GITHUB_POST_VERIFIED"
                    and old.get("result") is None,
                    "HOLD_REBASE_POST_REGRESSION")
        elif old_status == "IDENTITY_RETURN_VERIFIED":
            require(fresh_status == "SKIPPED_GITHUB_POST_VERIFIED",
                    "HOLD_REBASE_RETURN_NOT_RECONCILED")
            result = old.get("result")
            _verified_return(old, result)
            require(callable(independent_return_verifier)
                    and independent_return_verifier(
                        deepcopy(old), deepcopy(result), deepcopy(fresh)
                    ) is True,
                    "HOLD_REBASE_INDEPENDENT_RETURN_EVIDENCE")
            require(result["store_id"] not in store_ids,
                    "HOLD_REBASE_CROSS_PRODUCT_STORE_ID")
            store_ids.add(result["store_id"])
            # The fresh audited GitHub POST record becomes the sole authority.
            # Never carry a local result forward as a second CAS candidate.
        elif old_status in {"PENDING", "ACTIVE"}:
            require(fresh_status == "PENDING"
                    and old.get("plan_job_digest") == fresh["plan_job_digest"]
                    and old.get("result") is None,
                    "HOLD_REBASE_PENDING_CHANGED")
            fresh["status"] = old_status
            if old_status == "ACTIVE":
                active.append(old["request_id"])
        elif old_status == "HOLD_NAME_UNAVAILABLE":
            require(fresh_status == "PENDING"
                    and old.get("plan_job_digest") == fresh["plan_job_digest"]
                    and isinstance(old.get("result"), dict)
                    and old["result"].get("error_code") == "HOLD_NAME_UNAVAILABLE"
                    and old["result"].get("store_submission") == "NOT_PERFORMED"
                    and callable(independent_name_hold_verifier)
                    and independent_name_hold_verifier(deepcopy(old)) is True,
                    "HOLD_REBASE_NAME_HOLD_UNVERIFIED")
            fresh["status"] = "HOLD_NAME_UNAVAILABLE"
            fresh["result"] = deepcopy(old["result"])
        else:
            raise RebaseHold("HOLD_REBASE_UNKNOWN_OLD_STATUS")
    require(len(active) <= 1
            and previous.get("active_request_id") ==
                (active[0] if active else None),
            "HOLD_REBASE_CONCURRENT_ACTIVE")
    rebased["active_request_id"] = active[0] if active else None
    # Rebased state contains no locally asserted success. The existing replay
    # validator can now check its full immutable binding without a verifier.
    resume.validate_replay(rebased, expected)
    return rebased
