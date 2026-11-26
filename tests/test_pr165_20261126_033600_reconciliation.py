import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ops" / "active_e2e_handoff.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261116.json"
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261126_033600.json"
RECON = ROOT / "ops" / "focus_file_transport_reconciliation_20261126_033600.json"

class PR165CurrentHeadReconciliation20261126(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.recon = json.loads(RECON.read_text(encoding="utf-8"))

    def test_pr165_exact_head_ci_is_separate_from_product_e2e(self):
        observation = self.ledger["pr165_live_head_observation_20261126_025000"]
        self.assertEqual(observation["head_sha"], "f2a8d5b3f96b395ff248f42125daa26295f94c78")
        self.assertEqual(observation["parent_sha"], "13f8ed4f44e7c7e1ffaa3e64f9de73ba931e64d1")
        self.assertEqual([x["run_id"] for x in observation["exact_head_ci"]],
                         [45744533119, 45744533062, 45744533258])
        self.assertTrue(all(x["head_sha"] == observation["head_sha"]
                            and x["conclusion"] == "success" for x in observation["exact_head_ci"]))
        self.assertEqual(observation["product_e2e_status"], "HOLD")
        self.assertIs(observation["e2e_pass"], False)
        self.assertIs(self.ledger["e2e_pass"], False)

    def test_focus_and_file_keep_distinct_delivery_blockers(self):
        products = self.ledger["current_delivery_blockers_20261126_033600"]["products"]
        focus = products["Focus Session Desk"]
        file = products["File Integrity Ledger"]
        self.assertEqual(focus["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["current_source_request_id"], "app-focus-session-desk-fb6293839bc7")
        self.assertFalse(focus["current_source_exe_artifact"]["actual_exe_bytes_present"])
        self.assertIsNone(focus["authoritative_package_version"])
        self.assertEqual(focus["current_source_identity_status"], "NOT_COLLECTED")
        self.assertEqual(file["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertTrue(file["preidentity_exe_artifact"]["actual_exe_bytes_present"])
        self.assertEqual(file["preidentity_exe_artifact"]["exe_bytes"], 11494118)
        self.assertTrue(file["preidentity_exe_artifact"]["exe_sha_independently_rehashed_by_owner_00"])
        self.assertTrue(file["human_visual_review_required"])
        self.assertIsNone(file["authoritative_package_version"])
        self.assertFalse(file["real_msix"])

    def test_historical_signal_record_is_not_current_delivery_pointer(self):
        self.assertTrue(self.ledger["active_product_is_historical"])
        self.assertIsNone(self.ledger["current_active_product"])
        self.assertEqual(self.ledger["active_product"]["source_sha"],
                         "c058cbf7fe38e02d929c67d047d717ff74bd522e")
        self.assertEqual(self.ledger["current_signal_sprint_source_pointer_20261126_033600"]
                         ["current_frozen_candidate_source_sha"],
                         "1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertEqual(self.ledger["current_completion_priority"]["product"], "Focus Session Desk")

    def test_pr184_was_selectively_ported_without_merge(self):
        port = self.ledger["local_pull_custody_port_20261126_033600"]
        self.assertEqual(port["base_pr165_head_sha"], "f2a8d5b3f96b395ff248f42125daa26295f94c78")
        self.assertEqual(port["source_pr184"]["head_sha"], "4a5255940141a8f90b284674649f37b2cb74bb78")
        self.assertEqual(port["source_pr184"]["compare_status"], "diverged")
        self.assertEqual(port["source_pr184"]["ahead_by"], 17)
        self.assertEqual(port["source_pr184"]["behind_by"], 42)
        self.assertEqual(port["status"], "CODE_PORTED__EXACT_HEAD_CI_PENDING")
        self.assertFalse(port["merge_allowed"])
        self.assertFalse(port["force_push_allowed"])

    def test_queue_and_overlay_keep_all_store_and_e2e_gates_closed(self):
        self.assertEqual(self.queue["pr165_latest_live_head_sha"],
                         "f2a8d5b3f96b395ff248f42125daa26295f94c78")
        self.assertEqual(self.queue["priority"][0]["product"], "Focus Session Desk")
        self.assertEqual(self.queue["priority"][1]["product"], "File Integrity Ledger")
        self.assertEqual(self.overlay["status"], "HOLD")
        self.assertIs(self.overlay["e2e_pass"], False)
        self.assertFalse(self.overlay["safety"]["store_submission_allowed"])
        self.assertFalse(self.overlay["safety"]["certification_allowed"])
        self.assertFalse(self.overlay["safety"]["publish_allowed"])
        self.assertEqual(self.recon["status"], "HOLD")
        self.assertEqual(self.recon["store_upload_test_eligible_products"], 0)

if __name__ == "__main__":
    unittest.main()
