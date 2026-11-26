"""Append-only Focus QA reconciliation; never promote CI to product E2E."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ops" / "active_e2e_handoff.json"
OVERLAY = ROOT / "ops/active_e2e_handoff_overlay_20261126_183935.json"


class LiveFocusErrorRecoveryReconciliation20261126Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.key = "latest_live_execution_reconciliation_20261126_183935"
        cls.recon = cls.ledger[cls.key]

    def test_focus_error_recovery_qa_is_exact_source_bound_and_visual_signoff_only(self):
        focus = self.recon["focus_session_desk"]
        qa = focus["error_recovery_qa"]
        self.assertEqual(qa["source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(qa["request_id"], "app-focus-session-desk-fb6293839bc7")
        self.assertEqual(qa["qa_pr"], 130)
        self.assertEqual(qa["qa_head_sha"], "e1ab2e09bc12ef7b07b82f0cd1d1ef43b5d42034")
        self.assertEqual(qa["windows_error_recovery_run_id"], 45866054492)
        self.assertEqual(qa["windows_error_recovery_conclusion"], "success")
        self.assertEqual(qa["evidence_artifact_id"], 15140077746)
        self.assertEqual(qa["evidence_artifact_zip_sha256"], "88ee51ee28ca735cfbd396277504515d23957107c57f0d71306b1efdf67f7164")
        self.assertEqual(qa["scenarios"]["corrupt_primary_with_valid_backup"], "PASS")
        self.assertEqual(qa["scenarios"]["invalid_duration_zero_controlled_error"], "PASS")
        self.assertEqual(qa["visual_qa_signoff"], "00_VISUAL_QA_SIGNOFF_PASS")
        self.assertEqual(qa["human_owner_acknowledgment"], "NOT_CLAIMED__EVIDENCE_ATTACHED_FOR_OWNER_REVIEW")
        self.assertEqual(focus["visual_review"]["qa_lane_signoff_status"], "PASS")
        self.assertEqual(focus["visual_review"]["owner_signoff_status"], "PENDING")
        self.assertEqual(focus["identity"]["current_source_identity_status"], "NOT_COLLECTED")
        self.assertEqual(focus["identity"]["historical_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertIs(focus["identity"]["current_source_reuse_allowed"], False)
        self.assertIsNone(focus["package_version"])
        self.assertIs(focus["real_msix"], False)
        self.assertEqual(focus["store_assets"]["owner"], "00")
        self.assertIs(focus["store_assets"]["regeneration_or_modification_by_36"], False)

    def test_file_integrity_visual_review_pass_does_not_clear_identity_or_version_gates(self):
        product = self.recon["file_integrity_ledger"]
        self.assertEqual(product["source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(product["request"]["request_id"], "app-file-integrity-ledger-33d612be2774")
        self.assertEqual(product["request"]["status"], "DRY_RUN")
        self.assertIs(product["identity"]["current_source_approved_identity_present"], False)
        self.assertEqual(product["identity"]["official_identity_status"], "UNVERIFIED")
        self.assertEqual(product["visual_review"]["status"], "HUMAN_OWNER_VISUAL_REVIEW_PASS")
        self.assertIs(product["visual_review"]["immutable_receipt_flag_remains_true"], True)
        self.assertIsNone(product["package_version"])
        self.assertIs(product["real_msix"], False)

    def test_current_pr165_and_pr189_ci_are_repository_evidence_only(self):
        self.assertEqual(self.recon["pr165_head_sha"], "84f9a3480e2df93f0d75bddc29fb8de47e4ec941")
        self.assertEqual(self.recon["pr165_exact_head_ci_run_ids"], [45833181013, 45833181073, 45833180930])
        self.assertIs(self.recon["e2e_pass"], False)
        self.assertEqual(self.recon["pr189_pre_update_head"]["head_sha"], "65b0664466c1a384c550e90ae75ea790032af3ef")
        self.assertEqual(self.recon["pr189_pre_update_head"]["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(self.recon["local_pull_contract"]["receipt_status"], "CUSTODY_VERIFIED_ONLY")
        self.assertIs(self.recon["local_pull_contract"]["e2e_pass"], False)
        self.assertIs(self.recon["local_pull_contract"]["local_pull_receipt"], False)
        self.assertIs(self.recon["local_pull_contract"]["local_checker_receipt"], False)
        self.assertIs(self.recon["local_pull_contract"]["local_gui_install_receipt"], False)

    def test_browser_and_physical_windows_unavailability_keep_hold(self):
        self.assertEqual(self.recon["partner_center"]["authenticated_readback_status"],
                         "NOT_PERFORMED__ORIGINATING_BROWSER_CONTEXT_UNAVAILABLE")
        self.assertIsNone(self.recon["partner_center"]["authoritative_package_version"])
        self.assertIs(self.recon["partner_center"]["version_inferred"], False)
        self.assertIs(self.recon["partner_center"]["partner_center_write_performed"], False)
        self.assertIs(self.recon["local_windows_execution"]["physical_user_windows_session_available"], False)
        self.assertIs(self.recon["local_windows_execution"]["local_pull_receipt"], False)
        self.assertEqual(self.recon["first_unconnected_interval"]["status"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")

    def test_store_and_repository_safety_gates_remain_false(self):
        self.assertEqual(self.recon["store_upload_test"]["eligible_fresh_unsold_products"], 0)
        self.assertIs(self.recon["store_upload_test"]["dry_run_started"], False)
        self.assertEqual(self.recon["store_upload_test"]["hold"], 2)
        for key in ("store_submission_allowed", "certification_allowed", "publish_allowed",
                    "live_partner_center_write_allowed", "merge_allowed", "force_push_allowed"):
            self.assertIs(self.ledger[key], False)
        self.assertIs(self.ledger["e2e_pass"], False)
        self.assertEqual(self.ledger["latest_live_execution_reconciliation_key"], self.key)

    def test_overlay_matches_ledger_and_preserves_product_e2e_hold(self):
        self.assertEqual(self.overlay["pr165"]["head_sha"], "84f9a3480e2df93f0d75bddc29fb8de47e4ec941")
        self.assertEqual(self.overlay["products"]["focus_session_desk"]["error_recovery_qa"]["qa_head_sha"],
                         "e1ab2e09bc12ef7b07b82f0cd1d1ef43b5d42034")
        self.assertEqual(self.overlay["products"]["file_integrity_ledger"]["visual_review_status"],
                         "HUMAN_OWNER_VISUAL_REVIEW_PASS")
        self.assertEqual(self.overlay["central_ledger_reconciliation"]["active_ledger_blob_sha_after_update"],
                         "27e96895bf1e752547e3e58eccf96444883b4228")
        self.assertIs(self.overlay["e2e_pass"], False)
        self.assertIs(self.overlay["safety"]["version_inferred"], False)
        self.assertIs(self.overlay["safety"]["store_submission_allowed"], False)


if __name__ == "__main__":
    unittest.main()
