import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261128_2205.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261128_2205.json"


class CurrentLiveProductReconciliation20261128_2205Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_pr165_exact_head_ci_is_green_but_product_e2e_is_held(self):
        pr = self.overlay["pr165"]
        self.assertEqual(pr["head_sha_at_observation"], "335f2472dc1354b26158ab5667423ca2136aed88")
        self.assertEqual(pr["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in pr["exact_head_ci"]], [46147241542, 46147241552, 46147241546])
        self.assertEqual(pr["exact_head_ci"][2]["tests_run"], 600)
        self.assertEqual(pr["exact_head_ci"][2]["windows_skipped"], 2)
        self.assertEqual(pr["product_e2e_status"], "HOLD")
        self.assertFalse(pr["real_msix"])

    def test_focus_current_source_request_does_not_rebind_historical_identity(self):
        focus = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(focus["current_source_request"]["request_id"], "app-focus-session-desk-b6b69464a9c7")
        self.assertTrue(focus["current_source_request"]["source_matches_current_pr_head"])
        self.assertEqual(focus["current_source_request"]["artifact_id"], 15166202971)
        self.assertFalse(focus["identity"]["current_source_reuse_allowed"])
        self.assertIsNone(focus["package_version"])
        self.assertFalse(focus["real_msix"])

    def test_file_integrity_request_and_staging_map_are_not_a_product_msix(self):
        file_product = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(file_product["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertFalse(file_product["identity"]["current_source_approved_identity_present"])
        self.assertEqual(file_product["asset_staging_map_qa"]["status"], "PASS_MAPPING_ONLY")
        self.assertFalse(file_product["asset_staging_map_qa"]["real_msix_created"])
        self.assertIsNone(file_product["package_version"])
        self.assertFalse(file_product["real_msix"])

    def test_no_local_or_store_success_is_inferred(self):
        self.assertEqual(self.overlay["local_code_sync_receipt_status"], "NOT_OBSERVED__NO_USER_PC_RECEIPT_IN_CURRENT_RUN")
        self.assertEqual(self.overlay["store_upload_test"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.overlay["store_upload_test"]["dry_run_started"])
        self.assertFalse(self.overlay["safety"]["store_submission_allowed"])
        self.assertFalse(self.overlay["safety"]["certification_allowed"])
        self.assertFalse(self.overlay["safety"]["publish_allowed"])
        self.assertEqual(self.queue["status"], "HOLD")
        self.assertFalse(self.queue["new_product_generation_allowed"])
        self.assertEqual([x["product"] for x in self.queue["priority"]], ["Focus Session Desk", "File Integrity Ledger", "Prism Route 3D", "Signal Sprint"])


if __name__ == "__main__":
    unittest.main()
