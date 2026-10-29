"""Read-only exact-GitHub audit of a mixed PRE/POST Identity APP batch.

This module NEVER drives Partner Center, performs CAS, opens submission drafts,
changes the central ledger, or declares a local Windows/Store E2E PASS.
A POST Identity product must not be sent to the PRE Identity creation runner.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re

from scripts.reconcile_post_identity import ReconcileHold, reconcile_approved_return

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
PFN = re.compile(r"[A-Za-z0-9._-]+_[a-z0-9]{13}\Z")
SID = re.compile(r"S-1-15-2(?:-\d+){7}\Z")
ORDER = ("focus-session-desk", "file-integrity-ledger",
         "offline-text-diff-desk", "offline-image-inventory-desk")
SELECTION = "MSIX or PWA app"


class AuditHold(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise AuditHold(code)


def unique_json(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "HOLD_APPROVED_IDENTITY_DUPLICATE_KEY")
        value[key] = item
    return value


def _approved(raw):
    require(isinstance(raw, str) and 0 < len(raw) <= 65536,
            "HOLD_APPROVED_IDENTITY_FILE_INVALID")
    try:
        value = json.loads(raw, object_pairs_hook=unique_json)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, AuditHold):
            raise
        raise AuditHold("HOLD_APPROVED_IDENTITY_JSON_INVALID") from exc
    require(isinstance(value, dict), "HOLD_APPROVED_IDENTITY_JSON_INVALID")
    return value


def audit_rotation(ledger, *, fetch_head, fetch_approved, fetch_artifact,
                   now_utc=None):
    """Audit four exact jobs using live GitHub readers, with no writes.

    fetch_approved(repository, path, branch) returns UTF-8 text or None for
    an exact 404; all other API errors must propagate as HOLD, not as 404.
    """
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    require(isinstance(now, datetime) and now.tzinfo is not None,
            "HOLD_CLOCK_UNTRUSTED")
    now = now.astimezone(timezone.utc)
    cohorts = ledger.get("rotation_cohorts") or {}
    jobs = cohorts.get("app_jobs")
    batch = (ledger.get("multi_product_partner_center_batch_4") or {}).get("products")
    require(isinstance(jobs, list) and isinstance(batch, list)
            and len(jobs) == len(batch) == 4, "HOLD_BATCH_DISCOVERY_INCOMPLETE")
    require(tuple(x.get("slug") for x in jobs) == ORDER
            and tuple(x.get("slug") for x in batch) == ORDER
            and [x.get("batch_index") for x in batch] == [1, 2, 3, 4],
            "HOLD_BATCH_ORDER_OR_SCOPE")
    all_jobs = list(jobs)
    for collection, lane in (("three_d_jobs", "GAME_3D"), ("game_jobs", "GAME")):
        other = cohorts.get(collection, [])
        require(isinstance(other, list), "HOLD_ROTATION_SCHEMA")
        for item in other:
            require(isinstance(item, dict) and item.get("product_type") == lane,
                    "HOLD_CROSS_LANE_PRODUCT_TYPE")
            all_jobs.append(item)
    for key in ("request_id", "slug", "identity_return_target"):
        values = [x.get(key) for x in all_jobs]
        require(all(isinstance(x, str) and x for x in values)
                and len(set(values)) == len(values),
                "HOLD_CROSS_LANE_BINDING")
    for key in ("request_id", "slug", "source_sha", "identity_return_target"):
        values = [x.get(key) for x in jobs]
        require(all(isinstance(x, str) and x for x in values)
                and len(set(values)) == 4, "HOLD_CROSS_PRODUCT_BINDING")
    output, seen_ids, seen_pfns = [], set(), set()
    for index, (job, record) in enumerate(zip(jobs, batch), 1):
        slug = job["slug"]
        target = f"products/{slug}/store/approved-identity.json"
        require(job.get("product_type") == "APP"
                and job.get("source_repository") == "shihuiarenjinba-png/AI-App-Factory"
                and job.get("registration_type") == "MSIX_OR_PWA_APP"
                and job.get("partner_center_selection") == SELECTION
                and job.get("identity_return_target") == target,
                "HOLD_APP_ROUTING_CONFLICT")
        for key in ("request_id", "source_repository", "source_branch", "source_sha"):
            require(record.get(key) == job.get(key),
                    "HOLD_BATCH_SOURCE_BINDING_CONFLICT")
        require(SHA40.fullmatch(job["source_sha"]) is not None
                and SHA64.fullmatch(str(job.get("expected_exe_sha256", ""))) is not None,
                "HOLD_SOURCE_OR_EXE_SHA_INVALID")
        head = fetch_head(job["source_repository"], job["source_branch"])
        require(isinstance(head, str) and SHA40.fullmatch(head) is not None,
                "HOLD_FACTORY_HEAD_UNVERIFIED")
        raw = fetch_approved(job["source_repository"], target, job["source_branch"])
        if job.get("status") == "POST_IDENTITY_READY":
            require(head == job.get("identity_return_commit_sha")
                    and head != job["source_sha"],
                    "HOLD_RETURN_COMMIT_DRIFT")
            approved = _approved(raw)
            binding = {
                "request_id": job["request_id"], "product_type": "APP",
                "source_repository": job["source_repository"],
                "source_branch": job["source_branch"],
                "source_sha": job["source_sha"],
                "expected_head_sha": job["source_sha"],
                "package_sha256": job["expected_exe_sha256"],
                "package_version_gate": "HOLD",
                "reviewed": True, "source": "partner_center",
            }
            require(all(approved.get(k) == v for k, v in binding.items()),
                    "HOLD_APPROVED_IDENTITY_BINDING_CONFLICT")
            for key in ("store_id", "name", "publisher",
                        "package_family_name", "package_sid"):
                require(isinstance(approved.get(key), str)
                        and bool(approved[key].strip()),
                        "HOLD_APPROVED_IDENTITY_SCHEMA")
            require(re.fullmatch(r"[A-Za-z0-9]{8,32}", approved["store_id"]) is not None
                    and PFN.fullmatch(approved["package_family_name"]) is not None
                    and SID.fullmatch(approved["package_sid"]) is not None,
                    "HOLD_APPROVED_IDENTITY_SCHEMA")
            require(approved["store_id"] not in seen_ids
                    and approved["package_family_name"] not in seen_pfns,
                    "HOLD_CROSS_PRODUCT_IDENTITY_COLLISION")
            seen_ids.add(approved["store_id"])
            seen_pfns.add(approved["package_family_name"])
            require(job.get("identity_store_id") == approved["store_id"],
                    "HOLD_CENTRAL_IDENTITY_CONFLICT")
            # The same exact-GitHub evidence must also satisfy the canonical
            # single-writer POST_IDENTITY reconciler. No ledger write here.
            try:
                _, transition = reconcile_approved_return(
                    ledger, slug,
                    fetch_branch_head=lambda _repo, _branch: head,
                    fetch_approved_file=lambda _repo, _target, _branch: raw,
                )
            except ReconcileHold as exc:
                raise AuditHold(str(exc)) from exc
            require(transition == "EXISTING_VERIFIED",
                    "HOLD_POST_IDENTITY_RECONCILIATION_CONFLICT")
            output.append({
                "batch_index": index, "slug": slug, "request_id": job["request_id"],
                "status": "POST_IDENTITY_GITHUB_VERIFIED",
                "return_commit_sha": head, "store_id": approved["store_id"],
                "next_gate": "PACKAGE_VERSION_HOLD",
                "local_ui_and_replay": "NOT_VERIFIED_BY_THIS_AUDIT",
            })
        elif job.get("status") == "PRE_IDENTITY_READY":
            require(head == job["source_sha"], "HOLD_PRE_IDENTITY_HEAD_DRIFT")
            require(raw is None, "HOLD_LEDGER_STALE_APPROVED_FILE_PRESENT")
            require(job.get("factory_build_head") == job["source_sha"]
                    and job.get("artifact_metadata_verified") is True,
                    "HOLD_PRE_IDENTITY_ARTIFACT_BINDING")
            expiry = job.get("factory_artifact_expiry_utc")
            require(isinstance(expiry, str) and expiry.endswith("Z"),
                    "HOLD_ARTIFACT_EXPIRY_INVALID")
            try:
                deadline = datetime.fromisoformat(expiry[:-1] + "+00:00")
            except ValueError as exc:
                raise AuditHold("HOLD_ARTIFACT_EXPIRY_INVALID") from exc
            require(deadline > now, "HOLD_ARTIFACT_EXPIRED")
            artifact = fetch_artifact(job["source_repository"], job["factory_artifact_id"])
            require(isinstance(artifact, dict)
                    and artifact.get("expired") is False
                    and artifact.get("name") == job.get("factory_artifact_name")
                    and artifact.get("digest") ==
                    "sha256:" + str(job.get("factory_artifact_zip_sha256", "")),
                    "HOLD_ARTIFACT_MISMATCH")
            output.append({
                "batch_index": index, "slug": slug, "request_id": job["request_id"],
                "status": "PRE_IDENTITY_GITHUB_VERIFIED",
                "source_sha": head, "next_gate": "LOCAL_OPERATOR_REQUIRED",
            })
        else:
            raise AuditHold("HOLD_UNRECOGNIZED_ROTATION_STATUS")
    post = sum(x["status"] == "POST_IDENTITY_GITHUB_VERIFIED" for x in output)
    return {
        "status": "MIXED_ROTATION_AUDITED",
        "discovered_count": 4,
        "post_identity_github_verified": post,
        "pre_identity_github_verified": 4 - post,
        "products": output,
        "local_windows_no_llm_pass": False,
        "local_partner_center_operator_pass": False,
        "local_batch_runner_ready": False,
        "reason": "MIXED_STATE_RUNNER_RECONCILIATION_NOT_YET_INTEGRATED",
        "store_submission": "NOT_PERFORMED",
        "package_upload": "NOT_PERFORMED",
        "cas": "NOT_PERFORMED",
        "submission_draft": "NOT_OPENED_BY_AUDIT",
    }
