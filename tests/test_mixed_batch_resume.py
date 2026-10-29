"""Offline regression tests for the mixed PRE/POST serial resume contract."""
from __future__ import annotations

import unittest

from scripts import mixed_batch_resume as resume


HEAD = "a" * 40
SOURCE = ("1" * 40, "2" * 40, "3" * 40, "4" * 40)


def plan(post=1):
    items = []
    for i, slug in enumerate(resume.EXPECTED_ORDER):
        is_post = i < post
        items.append({
            "batch_index": i + 1,
            "slug": slug,
            "request_id": f"app-{slug}-{SOURCE[i][:12]}",
            "source_repository": "shihuiarenjinba-png/AI-App-Factory",
            "source_branch": f"codex/test-{slug}",
            "source_sha": SOURCE[i],
            "identity_return_target": f"products/{slug}/store/approved-identity.json",
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
        "post_identity_skip_count": post,
        "pre_identity_pending_count": 4 - post,
        "products": items,
        "local_windows_no_llm_pass": False,
        "task_scheduler_registration_allowed": False,
        "store_submission": "NOT_PERFORMED",
        "cas": "NOT_PERFORMED",
    }


def state(post=1):
    return resume.initialize(plan(post), central_head_sha=HEAD,
                             execution_origin="MANUAL_WINDOWS_TERMINAL")


def evidence(entry, i=2):
    return {
        "request_id": entry["request_id"],
        "source_sha": entry["source_sha"],
        "identity_return_target": entry["identity_return_target"],
        "registration_type": entry["registration_type"],
        "partner_center_selection": entry["partner_center_selection"],
        "plan_job_digest": entry["plan_job_digest"],
        "github_return_status": "APPLIED",
        "github_replay_status": "EXISTING_VERIFIED",
        "identity_capture_status":
            "IDENTITY_CAPTURED__AUTHENTICATED_UI__GITHUB_BOUND",
        "identity_return_commit_sha": "f" * 40,
        "store_id": f"9PTEST{i}12345",
        "pfn": f"Publisher.Test{i}_j8yefg9jgfh58",
        "package_sid": "S-1-15-2-" + "-".join(["12345"] * 7),
        "store_submission": "NOT_PERFORMED",
        "package_version_gate": "HOLD",
        "duplicate_creation": 0,
        "cross_product_contamination": 0,
    }


class MixedResumeTests(unittest.TestCase):
    def test_post_is_skipped_and_first_pre_claimed(self):
        current, job = resume.claim_next(state())
        self.assertEqual(job["batch_index"], 2)
        self.assertEqual(current["products"][0]["status"],
                         "SKIPPED_GITHUB_POST_VERIFIED")
        self.assertEqual(current["active_request_id"], job["request_id"])

    def test_active_replay_is_idempotent(self):
        current, job = resume.claim_next(state())
        replay, again = resume.claim_next(current)
        self.assertEqual(replay, current)
        self.assertEqual(again, job)
        resume.validate_replay(replay, state())

    def test_no_verifier_never_completes(self):
        current, job = resume.claim_next(state())
        with self.assertRaisesRegex(resume.MixedResumeHold, "NO_VERIFIER"):
            resume.complete_active(current, evidence(job),
                                   independent_evidence_verifier=None)

    def test_self_asserted_result_is_rejected(self):
        current, job = resume.claim_next(state())
        with self.assertRaisesRegex(resume.MixedResumeHold,
                                    "INDEPENDENT_EVIDENCE"):
            resume.complete_active(current, evidence(job),
                                   independent_evidence_verifier=lambda *_: False)

    def test_verified_completion_moves_to_next_product(self):
        current, job = resume.claim_next(state())
        current = resume.complete_active(
            current, evidence(job),
            independent_evidence_verifier=lambda *_: True)
        self.assertEqual(current["products"][1]["status"],
                         "IDENTITY_RETURN_VERIFIED")
        resume.validate_replay(current, state())
        current, next_job = resume.claim_next(current)
        self.assertEqual(next_job["batch_index"], 3)

    def test_cross_product_result_rejected(self):
        current, job = resume.claim_next(state())
        value = evidence(job)
        value["request_id"] = "other-product"
        with self.assertRaisesRegex(resume.MixedResumeHold, "RESULT_BINDING"):
            resume.complete_active(current, value,
                                   independent_evidence_verifier=lambda *_: True)

    def test_duplicate_store_id_rejected(self):
        current, job = resume.claim_next(state())
        current = resume.complete_active(
            current, evidence(job, 2),
            independent_evidence_verifier=lambda *_: True)
        current, job = resume.claim_next(current)
        with self.assertRaisesRegex(resume.MixedResumeHold,
                                    "CROSS_PRODUCT_IDENTITY"):
            resume.complete_active(
                current, evidence(job, 2),
                independent_evidence_verifier=lambda *_: True)

    def test_pre_reserve_name_unavailable_only(self):
        current, job = resume.claim_next(state())
        with self.assertRaisesRegex(resume.MixedResumeHold,
                                    "UNTRUSTED_NAME_CONFLICT"):
            resume.hold_name_unavailable(current, request_id=job["request_id"],
                                         verified_name_unavailable=False)
        held = resume.hold_name_unavailable(
            current, request_id=job["request_id"],
            verified_name_unavailable=True)
        self.assertEqual(resume.summary(held)["hold_count"], 1)
        held, next_job = resume.claim_next(held)
        self.assertEqual(next_job["batch_index"], 3)

    def test_replay_rejects_head_drift_and_post_mutation(self):
        expected = state()
        changed = state()
        changed["central_head_sha"] = "b" * 40
        with self.assertRaisesRegex(resume.MixedResumeHold, "REPLAY_CONFLICT"):
            resume.validate_replay(changed, expected)
        changed = state()
        changed["products"][0]["result"] = {"fake": "PASS"}
        with self.assertRaisesRegex(resume.MixedResumeHold, "POST_MUTATION"):
            resume.validate_replay(changed, expected)

    def test_all_post_no_work_not_false_host_pass(self):
        current = state(post=4)
        current, claimed = resume.claim_next(current)
        self.assertIsNone(claimed)
        report = resume.summary(current)
        self.assertEqual(report["status"],
                         "MIXED_LOCAL_COMPLETE_AWAITING_HOST_ATTESTATION")
        self.assertEqual(report["new_local_identity_returns"], 0)
        self.assertFalse(report["multi_product_identity_batch_pass"])
        self.assertFalse(report["task_scheduler_registration_allowed"])

    def test_unknown_plan_action_and_cas_authorization_rejected(self):
        modified = plan()
        modified["products"][1]["dispatch_action"] = "RUN_CAS_NOW"
        with self.assertRaisesRegex(resume.MixedResumeHold, "ACTION"):
            resume.initialize(modified, central_head_sha=HEAD,
                              execution_origin="MANUAL_WINDOWS_TERMINAL")
        modified = plan()
        modified["products"][1]["identity_cas_authorized_by_plan"] = True
        with self.assertRaisesRegex(resume.MixedResumeHold, "BINDING"):
            resume.initialize(modified, central_head_sha=HEAD,
                              execution_origin="MANUAL_WINDOWS_TERMINAL")

    def test_summary_remains_partial_without_host_proof(self):
        current = state()
        self.assertEqual(resume.summary(current)["status"],
                         "MULTI_PRODUCT_IDENTITY_BATCH_PARTIAL")
        self.assertFalse(resume.summary(current)["scheduled_trigger_proven"])


if __name__ == "__main__":
    unittest.main()
