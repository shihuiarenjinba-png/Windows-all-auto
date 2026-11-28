import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261128_2032.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261128_2032.json"


class CurrentLiveProductReconciliation20261128Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_pr165_observation_is_exact_head_and_repository_ci_only(self):
        pr = self.overlay["pr165"]
        self.assertEqual(pr["head_sha_at_observation"], "9a7b8db24f26a4266fbc7d30d16c64edb5edf5fa")
        self.assertEqual(pr["parent_sha"], "cf92e4a1eea96ade6bf9806905dfd53128c18eb2")
        self.assertEqual(pr["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(
            [item["run_id"] for item in pr["exact_head_ci"]],
            [46137250087, 46137250084, 46137250139],
        )
        self.assertTrue(all(item["head_sha"] == pr["head_sha_at_observation"] for item in pr["exact_head_ci"]))
        self.assertTrue(all(item["conclusion"] == "success" for item in pr["exact_head_ci"]))
        self.assertEqual(pr["product_e2e_status"], "HOLD")
        self.assertFalse(pr["real_msix"])
        self.assertFalse(pr["github_backlog_receipt"])
        self.assertFalse(pr["local_pull_receipt"])
        self.assertFalse(pr["local_checker_receipt"])
        self.assertFalse(pr["local_gui_install_receipt"])

    def test_focus_historical_identity_and_request_are_not_reused(self):
        f = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(f["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(f["identity"]["historical_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(f["identity"]["expected_head_sha"], f["identity"]["historical_source_sha"])
        self.assertEqual(f["identity"]["current_source_binding_status"], "STALE_HISTORICAL_SOURCE_MISMATCH")
        self.assertFalse(f["identity"]["current_source_reuse_allowed"])
        self.assertEqual(f["current_source_request"]["source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertFalse(f["current_source_request"]["source_matches_current_pr_head"])
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])
        self.assertEqual(f["store_assets"]["owner"], "00")
        self.assertTrue(f["store_assets"]["raw_sha256_independently_recomputed"])

    def test_file_current_source_has_no_approved_identity(self):
        f = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(f["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertFalse(f["identity"]["current_source_approved_identity_present"])
        self.assertEqual(f["identity"]["historical_identity_source_sha"], "d1108d12f7d1697af30400f97c7db39cba5e6791")
        self.assertEqual(f["current_source_request"]["source_sha"], f["current_source_sha"])
        self.assertEqual(f["current_source_request"]["status"], "DRY_RUN")
        self.assertEqual(f["msix_export"]["status"], "SKIPPED_NO_ARTIFACT")
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])
        self.assertTrue(f["store_assets"]["raw_sha256_independently_recomputed"])

    def test_transport_is_implemented_but_no_real_product_package_exists(self):
        transport = self.overlay["transport_contract"]
        self.assertEqual(transport["status"], "IMPLEMENTED_FAIL_CLOSED__EXACT_HEAD_CI_PASS")
        self.assertIn("all_auto/bridge_poll.py", transport["code_paths"])
        self.assertIn("scripts/local_handoff_pull.py", transport["code_paths"])
        self.assertIn("scripts/local_checker_queue.py", transport["code_paths"])
        self.assertFalse(transport["real_product_msix_received"])
        self.assertEqual(self.overlay["first_unconnected_interval"]["status"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")

    def test_store_and_product_e2e_gates_remain_closed(self):
        self.assertEqual(self.overlay["status"], "HOLD")
        self.assertFalse(self.overlay["e2e_pass"])
        self.assertFalse(self.overlay["safety"]["store_submission_allowed"])
        self.assertFalse(self.overlay["safety"]["certification_allowed"])
        self.assertFalse(self.overlay["safety"]["publish_allowed"])
        self.assertFalse(self.overlay["safety"]["merge_allowed"])
        self.assertFalse(self.overlay["safety"]["force_push_allowed"])
        self.assertFalse(self.overlay["safety"]["repositories_12_24_touched"])
        self.assertEqual(self.overlay["store_upload_test"]["eligible_fresh_unsold_products"], 0)

    def test_queue_preserves_existing_product_priority_and_no_new_products(self):
        self.assertFalse(self.queue["new_product_generation_allowed"])
        self.assertEqual(
            [item["product"] for item in self.queue["priority"]],
            ["Focus Session Desk", "File Integrity Ledger", "Prism Route 3D", "Signal Sprint"],
        )
        self.assertEqual(self.queue["priority"][0]["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(self.queue["priority"][1]["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(self.queue["status"], "HOLD")
        self.assertFalse(self.queue["e2e_pass"])
        self.assertFalse(self.queue["store_submission_allowed"])
        self.assertFalse(self.queue["certification_allowed"])
        self.assertFalse(self.queue["publish_allowed"])


if __name__ == "__main__":
    unittest.main()
