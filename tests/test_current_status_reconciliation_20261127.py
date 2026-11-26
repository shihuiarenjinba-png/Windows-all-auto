import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops/active_e2e_handoff_overlay_20261126_203204.json"
QUEUE = ROOT / "ops/completion_rush_queue_20261116.json"


class CurrentStatusReconciliation20261127Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        cls.focus = cls.overlay["source_identity_version_reconciliation"]["focus_session_desk"]
        cls.file = cls.overlay["source_identity_version_reconciliation"]["file_integrity_ledger"]

    def test_focus_waits_for_user_identity_only_after_all_other_gates_pass(self):
        f = self.focus
        self.assertEqual(f["state"], "WAITING_USER_IDENTITY")
        self.assertEqual(f["non_identity_prerequisites_status"], "PASS")
        self.assertEqual(f["current_source"]["source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(f["historical_identity"]["source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertFalse(f["historical_identity"]["current_source_reuse_allowed"])
        self.assertEqual(f["current_source_request"]["artifact_id"], 15049692591)
        self.assertEqual(f["current_source_request"]["source_branch_head_check"], "PASS")
        self.assertEqual(f["current_source_exe"]["artifact_id"], 15083856249)
        self.assertEqual(f["native_windows_qa"]["windows_gui_run_id"], 45866054492)
        self.assertEqual(f["native_windows_qa"]["scenarios"]["corrupt_primary_valid_backup_restore_and_notice"], "PASS")
        self.assertEqual(f["native_windows_qa"]["scenarios"]["invalid_duration_zero_controlled_error_and_state_unchanged"], "PASS")
        self.assertTrue(f["store_assets"]["current_git_blob_sha_readback_matches"])
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])

    def test_file_integrity_waits_for_user_identity_after_visual_and_asset_map_pass(self):
        f = self.file
        self.assertEqual(f["state"], "WAITING_USER_IDENTITY")
        self.assertEqual(f["non_identity_prerequisites_status"], "PASS")
        self.assertEqual(f["current_source"]["source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertFalse(f["historical_identity"]["current_source_reuse_allowed"])
        self.assertEqual(f["current_source_request"]["artifact_id"], 14934034365)
        self.assertEqual(f["current_source_gui_artifact"]["artifact_id"], 14934752145)
        self.assertEqual(f["current_source_gui_artifact"]["human_visual_review"], "PASS")
        self.assertEqual(f["asset_mapping_qa"]["mapping_run_id"], 45747686529)
        self.assertTrue(f["store_assets"]["current_git_blob_sha_readback_matches"])
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])

    def test_transport_ci_is_exact_head_but_not_product_e2e(self):
        t = self.overlay["transport"]
        self.assertEqual(t["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(t["pr165"]["head_sha"], "84f9a3480e2df93f0d75bddc29fb8de47e4ec941")
        self.assertEqual(t["pr192"]["head_sha"], "792a6ab7bc1a5847c03ebf59e07354edb3d3afb0")
        self.assertEqual(t["pr195"]["head_sha"], "e2851d5e755c439667faa5587eafdc7e4edac7ea")
        self.assertEqual(t["pr195"]["exact_head_offline_qa_run_id"], 45870733361)
        self.assertEqual(self.overlay["e2e_status"], "HOLD")
        self.assertFalse(self.overlay["e2e_pass"])
        self.assertFalse(self.overlay["downstream_receipts"]["real_msix"])
        self.assertFalse(self.overlay["downstream_receipts"]["github_backlog_receipt"])
        self.assertFalse(self.overlay["downstream_receipts"]["local_pull_receipt"])
        self.assertFalse(self.overlay["downstream_receipts"]["local_checker_receipt"])
        self.assertFalse(self.overlay["downstream_receipts"]["local_gui_install_receipt"])

    def test_queue_points_to_current_overlay_and_keeps_store_gates_false(self):
        self.assertEqual(self.queue["current_status_reconciliation_file"], "ops/active_e2e_handoff_overlay_20261126_203204.json")
        self.assertEqual(self.queue["current_status_reconciliation_20261127_0532"]["focus_state"], "WAITING_USER_IDENTITY")
        self.assertEqual(self.queue["current_status_reconciliation_20261127_0532"]["file_integrity_state"], "WAITING_USER_IDENTITY")
        self.assertFalse(self.queue["e2e_pass"])
        self.assertFalse(self.queue["store_submission_allowed"])
        self.assertFalse(self.queue["certification_allowed"])
        self.assertFalse(self.queue["publish_allowed"])
        self.assertEqual(self.queue["store_upload_test_eligibility_current_20261127_0532"]["eligible_fresh_unsold_products"], 0)

    def test_user_owned_identity_return_is_the_resume_trigger(self):
        self.assertEqual(self.overlay["resume_trigger"]["owner"], "USER")
        self.assertIn("authoritative Package Version", self.overlay["resume_trigger"]["required_return"])
        self.assertFalse(self.overlay["safety"]["live_partner_center_write_allowed"])
        self.assertFalse(self.overlay["safety"]["identity_write_allowed"])
        self.assertFalse(self.overlay["safety"]["version_inference_allowed"])
        self.assertFalse(self.overlay["safety"]["merge_allowed"])
        self.assertFalse(self.overlay["safety"]["force_push_allowed"])


if __name__ == "__main__":
    unittest.main()
