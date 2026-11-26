import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "ops/completion_rush_queue_20261127_0731.json"
HISTORICAL_OVERLAY = ROOT / "ops/active_e2e_handoff_overlay_20261126_163937.json"


class FileVisualReviewGateReconciliation20261127Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        cls.overlay = json.loads(HISTORICAL_OVERLAY.read_text(encoding="utf-8"))
        cls.file_item = next(x for x in cls.queue["priority"] if x["product"] == "File Integrity Ledger")

    def test_human_visual_review_and_asset_mapping_pass_are_recorded(self):
        self.assertEqual(self.file_item["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(self.file_item["human_visual_review_status"], "PASS")
        self.assertEqual(self.file_item["human_visual_review_observed_at_utc"], "2026-11-26T13:30:25Z")
        self.assertFalse(self.file_item["human_visual_review_required"])
        self.assertTrue(self.file_item["immutable_receipt_visual_review_required"])
        self.assertEqual(self.file_item["asset_mapping_qa_head_sha"], "d245b5b0541a09af2de46d092e5525023456f843")
        self.assertEqual(self.file_item["asset_mapping_qa_run_id"], 45747686529)
        self.assertEqual(self.file_item["state"], "WAITING_USER_IDENTITY")

    def test_visual_and_asset_pass_do_not_promote_identity_version_or_package(self):
        self.assertEqual(self.file_item["current_source_identity_binding_status"], "NO_CURRENT_SOURCE_APPROVED_IDENTITY")
        self.assertFalse(self.file_item["approved_identity_file_present_on_current_pr115_head"])
        self.assertEqual(self.file_item["current_source_request"]["status"], "DRY_RUN")
        self.assertEqual(self.file_item["current_source_request"]["official_identity_status"], "UNVERIFIED")
        self.assertIsNone(self.file_item["package_version"])
        self.assertFalse(self.file_item["real_msix"])
        self.assertFalse(self.file_item["product_e2e_pass"])
        self.assertEqual(self.overlay["products"]["file_integrity_ledger"]["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(self.overlay["status"], "HOLD")


if __name__ == "__main__":
    unittest.main()
