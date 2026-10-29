"""Regression tests for central-HEAD drift after an exact Identity CAS return."""
from copy import deepcopy

import unittest

from scripts import mixed_batch_resume as resume
from scripts import mixed_resume_rebase as rebase

ORDER = resume.EXPECTED_ORDER
SOURCE = {
    "focus-session-desk": "8b00bc4e90828c4282463826873aa8dfd2eb93f4",
    "file-integrity-ledger": "d1108d12f7d1697af30400f97c7db39cba5e6791",
    "offline-text-diff-desk": "a7d37280089893a9ea4b9ac3336020a920e73e0c",
    "offline-image-inventory-desk": "16b6a772952ca0988f2ae2f8b5f4db2e59ec5877",
}
OLD_HEAD = "a" * 40
NEW_HEAD = "b" * 40
ORIGIN = "MANUAL_WINDOWS_TERMINAL"


def plan(post=()):
    products = []
    for index, slug in enumerate(ORDER, 1):
        is_post = slug in post
        products.append({
            "batch_index": index,
            "slug": slug,
            "request_id": "app-" + slug + "-" + SOURCE[slug][:12],
            "source_repository": "shihuiarenjinba-png/AI-App-Factory",
            "source_branch": "codex/app-" + slug + "-20261028",
            "source_sha": SOURCE[slug],
            "identity_return_target":
                "products/" + slug + "/store/approved-identity.json",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "observed_identity_state":
                "POST_IDENTITY_READY" if is_post else "PRE_IDENTITY_READY",
            "dispatch_action":
                resume.POST_ACTION if is_post else resume.PRE_ACTION,
            "identity_cas_authorized_by_plan": False,
            "partner_center_creation_authorized_by_plan": False,
        })
    return {
        "status": "MIXED_ROTATION_DISPATCH_PLAN_READY",
        "discovered_count": 4,
        "post_identity_skip_count": len(post),
        "pre_identity_pending_count": 4 - len(post),
        "local_windows_no_llm_pass": False,
        "task_scheduler_registration_allowed": False,
        "store_submission": "NOT_PERFORMED",
        "cas": "NOT_PERFORMED",
        "products": products,
    }


def old_state(post=()):
    return resume.initialize(
        plan(post), central_head_sha=OLD_HEAD, execution_origin=ORIGIN
    )


def finish_first(state):
    claimed_state, entry = resume.claim_next(state)
    assert entry["slug"] == "focus-session-desk"
    result = {
        **{key: entry[key] for key in (
            "request_id", "source_sha", "identity_return_target",
            "registration_type", "partner_center_selection",
            "plan_job_digest",
        )},
        "github_return_status": "APPLIED",
        "github_replay_status": "EXISTING_VERIFIED",
        "identity_capture_status":
            "IDENTITY_CAPTURED__AUTHENTICATED_UI__GITHUB_BOUND",
        "identity_return_commit_sha": "c" * 40,
        "store_id": "9P6452C61N7B",
        "pfn": "OkinawaDesktopTools.FocusSessionDesk_j8yefg9jgfh58",
        "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
        "package_version_gate": "HOLD",
        "store_submission": "NOT_PERFORMED",
        "duplicate_creation": 0,
        "cross_product_contamination": 0,
    }
    return resume.complete_active(
        claimed_state, result,
        independent_evidence_verifier=lambda entry, result: True,
    )


def migrate(old, new, verifier=lambda old, result, fresh: True):
    return rebase.rebase_after_reconciliation(
        old, new, new_central_head_sha=NEW_HEAD,
        execution_origin=ORIGIN, independent_return_verifier=verifier,
    )


class RebaseTests(unittest.TestCase):
    def test_verified_cas_becomes_immutable_post_skip_after_central_update(self):
        previous = finish_first(old_state())
        updated = migrate(previous, plan({"focus-session-desk"}))
        assert updated["central_head_sha"] == NEW_HEAD
        assert updated["products"][0]["status"] == "SKIPPED_GITHUB_POST_VERIFIED"
        assert updated["products"][0]["result"] is None
        assert [x["status"] for x in updated["products"][1:]] == ["PENDING"] * 3
        assert updated["active_request_id"] is None
        assert resume.summary(updated)["next_resume_index"] == 2
        resume.validate_replay(
            updated,
            resume.initialize(plan({"focus-session-desk"}),
                              central_head_sha=NEW_HEAD, execution_origin=ORIGIN),
        )
    
    
    def test_post_cannot_be_claimed_without_previous_verified_return(self):
        with self.assertRaisesRegex(rebase.RebaseHold, "HOLD_REBASE_PENDING_CHANGED"):
            migrate(old_state(), plan({"focus-session-desk"}))
    
    
    def test_return_must_be_independently_reverified_not_receipt_only(self):
        with self.assertRaisesRegex(rebase.RebaseHold, "HOLD_REBASE_INDEPENDENT_RETURN_EVIDENCE"):
            migrate(finish_first(old_state()), plan({"focus-session-desk"}),
                    verifier=lambda old, result, fresh: False)
    
    
    def test_missing_verifier_never_promotes_a_local_result(self):
        with self.assertRaisesRegex(rebase.RebaseHold, "HOLD_REBASE_INDEPENDENT_RETURN_EVIDENCE"):
            migrate(finish_first(old_state()), plan({"focus-session-desk"}),
                    verifier=None)
    
    
    def test_tampered_result_binding_is_rejected_before_callback(self):
        old = finish_first(old_state())
        old["products"][0]["result"]["source_sha"] = "d" * 40
        with self.assertRaisesRegex(rebase.RebaseHold, "HOLD_REBASE_RETURN_BINDING"):
            migrate(old, plan({"focus-session-desk"}))
    
    
    def test_unreconciled_local_success_does_not_reenter_pre_queue(self):
        with self.assertRaisesRegex(rebase.RebaseHold, "HOLD_REBASE_RETURN_NOT_RECONCILED"):
            migrate(finish_first(old_state()), plan())
    
    
    def test_post_to_pre_downgrade_is_rejected(self):
        old = old_state({"focus-session-desk"})
        with self.assertRaisesRegex(rebase.RebaseHold, "HOLD_REBASE_POST_REGRESSION"):
            migrate(old, plan())
    
    
    def test_pending_metadata_drift_fails_closed(self):
        old = old_state()
        fresh = plan()
        fresh["products"][2]["source_branch"] = "codex/changed-source-branch"
        with self.assertRaisesRegex(rebase.RebaseHold, "HOLD_REBASE_PENDING_CHANGED"):
            migrate(old, fresh)
    
    
    def test_active_job_survives_unrelated_central_reconciliation(self):
        old = old_state({"focus-session-desk"})
        old, active = resume.claim_next(old)
        assert active["batch_index"] == 2
        new = migrate(old, plan({"focus-session-desk"}))
        assert new["active_request_id"] == active["request_id"]
        assert new["products"][1]["status"] == "ACTIVE"
        assert resume.claim_next(new)[1]["request_id"] == active["request_id"]
    
    
    def test_multiple_active_requests_rejected(self):
        old = old_state()
        old["products"][0]["status"] = "ACTIVE"
        old["products"][1]["status"] = "ACTIVE"
        old["active_request_id"] = old["products"][0]["request_id"]
        with self.assertRaisesRegex(rebase.RebaseHold, "HOLD_REBASE_CONCURRENT_ACTIVE"):
            migrate(old, plan())
    
    
    def test_name_hold_needs_independent_evidence(self):
        old = old_state()
        old["products"][0]["status"] = "HOLD_NAME_UNAVAILABLE"
        old["products"][0]["result"] = {
            "error_code": "HOLD_NAME_UNAVAILABLE",
            "store_submission": "NOT_PERFORMED",
        }
        with self.assertRaisesRegex(rebase.RebaseHold, "HOLD_REBASE_NAME_HOLD_UNVERIFIED"):
            migrate(old, plan())
        new = rebase.rebase_after_reconciliation(
            old, plan(), new_central_head_sha=NEW_HEAD,
            execution_origin=ORIGIN, independent_return_verifier=None,
            independent_name_hold_verifier=lambda old: True,
        )
        assert new["products"][0]["status"] == "HOLD_NAME_UNAVAILABLE"
    
    
    def test_same_plan_idempotent_pending_rebase_does_not_grant_pass(self):
        new = migrate(old_state(), plan())
        assert new["products"][0]["status"] == "PENDING"
        assert resume.summary(new)["local_windows_no_llm_pass"] is False
        assert resume.summary(new)["task_scheduler_registration_allowed"] is False
    