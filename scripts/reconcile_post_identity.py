"""Pure, fail-closed POST_IDENTITY ledger reconciliation.

Only the 36-minute E2E owner may commit the returned ledger. Callers must supply
readers backed by fresh authenticated GitHub API responses, not operator JSON.
This module performs no GitHub writes, Partner Center actions, CAS, or packaging.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Callable

SHA40 = re.compile(r"[0-9a-f]{40}")
SHA64 = re.compile(r"[0-9a-f]{64}")


class ReconcileHold(ValueError):
    pass


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise ReconcileHold(code)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ReconcileHold("HOLD_APPROVED_IDENTITY_DUPLICATE_KEY")
        value[key] = item
    return value


def _all_jobs(ledger: dict) -> list[dict]:
    cohorts = ledger.get("rotation_cohorts", {})
    _require(isinstance(cohorts, dict), "HOLD_ROTATION_SCHEMA")
    jobs = []
    for collection, lane in (("app_jobs", "APP"), ("three_d_jobs", "GAME_3D"),
                             ("game_jobs", "GAME")):
        items = cohorts.get(collection, [])
        _require(isinstance(items, list), "HOLD_ROTATION_SCHEMA")
        for item in items:
            _require(isinstance(item, dict), "HOLD_ROTATION_SCHEMA")
            _require(item.get("product_type") == lane, "HOLD_CROSS_LANE_IDENTITY")
            jobs.append(item)
    for key in ("request_id", "slug", "identity_return_target"):
        values = [x.get(key) for x in jobs]
        _require(all(isinstance(v, str) and v for v in values)
                 and len(values) == len(set(values)), "HOLD_CROSS_PRODUCT_IDENTITY")
    return jobs


def reconcile_approved_return(
    ledger: dict, slug: str, *,
    fetch_branch_head: Callable[[str, str], str],
    fetch_approved_file: Callable[[str, str, str], str],
    verify_source_ancestry: Callable[[str, str, str, str], bool] | None = None,
) -> tuple[dict, str]:
    """Return (updated ledger copy, transition), without performing a write.

    Readers MUST retrieve the exact live Factory branch and raw UTF-8 file via
    authenticated GitHub; never pass a local operator's unverified assertion.
    An approved file is Identity evidence only, not Package Version approval,
    a local GUI PASS, or permission to submit to Store.
    """
    result = deepcopy(ledger)
    jobs = _all_jobs(result)
    matches = [x for x in jobs if x.get("slug") == slug]
    _require(len(matches) == 1, "HOLD_PRODUCT_NOT_UNIQUE")
    job = matches[0]
    _require(job.get("status") in {"PRE_IDENTITY_READY", "POST_IDENTITY_READY"},
             "HOLD_PRODUCT_NOT_READY")
    expected_target = f"products/{slug}/store/approved-identity.json"
    _require(job.get("identity_return_target") == expected_target,
             "HOLD_IDENTITY_RETURN_TARGET")
    for key in ("source_repository", "source_branch", "source_sha", "request_id"):
        _require(isinstance(job.get(key), str) and bool(job[key]),
                 "HOLD_SOURCE_BINDING_INCOMPLETE")
    _require(SHA40.fullmatch(job["source_sha"]) is not None,
             "HOLD_SOURCE_SHA_INVALID")
    head = fetch_branch_head(job["source_repository"], job["source_branch"])
    _require(isinstance(head, str) and SHA40.fullmatch(head) is not None,
             "HOLD_FACTORY_HEAD_UNVERIFIED")
    # A returned branch HEAD must be a descendant of the pinned immutable
    # source commit. An unrelated branch containing a plausible Identity JSON
    # is not evidence of a legitimate Provisioner CAS return.
    _require(callable(verify_source_ancestry),
             "HOLD_SOURCE_ANCESTRY_VERIFIER_MISSING")
    _require(verify_source_ancestry(job["source_repository"],
                                    job["source_sha"], head,
                                    expected_target) is True,
             "HOLD_SOURCE_ANCESTRY_CONFLICT")
    raw = fetch_approved_file(job["source_repository"], expected_target,
                              job["source_branch"])
    _require(isinstance(raw, str) and len(raw) <= 65536,
             "HOLD_APPROVED_IDENTITY_FILE_INVALID")
    try:
        approved = json.loads(raw, object_pairs_hook=_unique_object)
    except ReconcileHold:
        raise
    except (ValueError, TypeError) as exc:
        raise ReconcileHold("HOLD_APPROVED_IDENTITY_JSON_INVALID") from exc
    _require(isinstance(approved, dict), "HOLD_APPROVED_IDENTITY_JSON_INVALID")
    binding = {
        "request_id": job["request_id"],
        "product_type": job["product_type"],
        "source_repository": job["source_repository"],
        "source_branch": job["source_branch"],
        "source_sha": job["source_sha"],
        "expected_head_sha": job["source_sha"],
    }
    _require(all(approved.get(k) == v for k, v in binding.items()),
             "HOLD_APPROVED_IDENTITY_SOURCE_CONFLICT")
    _require(approved.get("reviewed") is True
             and approved.get("source") == "partner_center"
             and approved.get("package_version_gate") == "HOLD",
             "HOLD_IDENTITY_OR_VERSION_GATE")
    for key in ("store_id", "name", "publisher", "package_family_name", "package_sid"):
        _require(isinstance(approved.get(key), str) and bool(approved[key].strip()),
                 "HOLD_APPROVED_IDENTITY_SCHEMA")
    _require(re.fullmatch(r"[A-Za-z0-9]{8,32}", approved["store_id"]) is not None
             and re.fullmatch(r"[A-Za-z0-9._-]+_[a-z0-9]{13}",
                              approved["package_family_name"]) is not None
             and re.fullmatch(r"S-1-15-2(?:-\d+){7}",
                              approved["package_sid"]) is not None,
             "HOLD_APPROVED_IDENTITY_SCHEMA")
    if job.get("expected_exe_sha256") is not None:
        _require(approved.get("package_sha256") == job["expected_exe_sha256"],
                 "HOLD_PREIDENTITY_ARTIFACT_CONFLICT")
    _require(head != job["source_sha"], "HOLD_RETURN_COMMIT_NOT_OBSERVED")
    if job.get("status") == "POST_IDENTITY_READY":
        _require(job.get("identity_return_commit_sha") == head,
                 "HOLD_RETURN_COMMIT_DRIFT")
        # A replay is a verification, never an opportunity to overwrite a
        # previously recorded Store ID/PFN with a different product binding.
        _require(job.get("identity_store_id") == approved["store_id"]
                 and job.get("identity_pfn") == approved["package_family_name"],
                 "HOLD_POST_IDENTITY_BINDING_CONFLICT")
        transition = "EXISTING_VERIFIED"
    else:
        _require(job.get("identity_store_id") in (None, "")
                 and job.get("identity_pfn") in (None, ""),
                 "HOLD_PRE_IDENTITY_STALE_BINDING")
        transition = "POST_IDENTITY_READY"
    for other in jobs:
        if other is job:
            continue
        _require(other.get("identity_store_id") != approved["store_id"]
                 and other.get("identity_pfn") != approved["package_family_name"],
                 "HOLD_CROSS_PRODUCT_IDENTITY")
    job.update({
        "status": "POST_IDENTITY_READY",
        "identity_status": "GITHUB_APPROVED_IDENTITY_RETURN_VERIFIED__PACKAGE_VERSION_HOLD",
        "identity_return_commit_sha": head,
        "identity_store_id": approved["store_id"],
        "identity_pfn": approved["package_family_name"],
        "identity_cas_allowed": False,
        "package_version_gate": "HOLD",
        "next_action": "PACKAGE_VERSION_AND_ASSET_APPROVAL_GATE",
    })
    for request in (result.get("user_id_requests") or {}).get("items", []):
        if request.get("request_id") == job["request_id"]:
            request.update({
                "status": "USER_IDENTITY_RECEIVED",
                "requested_fields": [],
                "next_gate": "POST_IDENTITY_PACKAGE_VERSION_GATE_HOLD",
                "allow_local_product_creation": False,
            })
    for entry in (result.get("registration_router") or {}).get("entries", []):
        if entry.get("product") == job.get("display_name"):
            entry["identity_status"] = "GITHUB_APPROVED_IDENTITY_RETURN_VERIFIED"
            entry["next_action"] = "PACKAGE_VERSION_GATE_HOLD"
    pipeline = result.get("post_identity_pipeline")
    _require(isinstance(pipeline, dict)
             and isinstance(pipeline.get("products"), list),
             "HOLD_POST_IDENTITY_PIPELINE_MISSING")
    matches = [entry for entry in pipeline["products"]
               if isinstance(entry, dict)
               and entry.get("request_id") == job["request_id"]]
    _require(len(matches) >= 1, "HOLD_POST_IDENTITY_PIPELINE_MISSING")
    _require(len(matches) == 1, "HOLD_POST_IDENTITY_PIPELINE_DUPLICATE")
    entry = matches[0]
    # A valid Identity return must have exactly one matching downstream
    # pipeline record. Matching request_id alone does not prove product/lane
    # ownership: never silently rewrite a cross-product pipeline record.
    for field, expected in (
        ("product", job["display_name"]),
        ("lane", job["product_type"]),
        ("source_repository", job["source_repository"]),
        ("source_branch", job["source_branch"]),
        ("source_sha", job["source_sha"]),
        ("identity_return_target", expected_target),
    ):
        _require(entry.get(field) == expected,
                 "HOLD_POST_IDENTITY_PIPELINE_SOURCE_CONFLICT")
    expected_state = ("POST_IDENTITY_READY" if transition == "EXISTING_VERIFIED"
                      else "WAITING_IDENTITY_CAPTURE_AND_CAS")
    _require(entry.get("state") == expected_state,
             "HOLD_POST_IDENTITY_PIPELINE_STATE_CONFLICT")
    for field, expected in (("identity_store_id", approved["store_id"]),
                            ("identity_pfn", approved["package_family_name"])):
        if transition == "EXISTING_VERIFIED":
            _require(entry.get(field) == expected,
                     "HOLD_POST_IDENTITY_PIPELINE_CONFLICT")
        else:
            _require(entry.get(field) in (None, ""),
                     "HOLD_POST_IDENTITY_PIPELINE_CONFLICT")
    entry.update({
        "state": "POST_IDENTITY_READY",
        "identity_status": "CAS_RETURN_COMMIT_GITHUB_VERIFIED",
        "identity_return_commit_sha": head,
        "identity_store_id": approved["store_id"],
        "identity_pfn": approved["package_family_name"],
        "next_action": "PACKAGE_VERSION_AND_ASSET_APPROVAL_GATE",
    })
    return result, transition
