import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "ops" / "completion_rush_queue_20261116.json"


class CompletionRushQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_new_products_are_disabled_during_completion_rush(self):
        self.assertFalse(self.data["new_product_generation_allowed"])

    def test_focus_and_file_integrity_are_delivery_only(self):
        items = {x["product"]: x for x in self.data["priority"]}
        for name in ("Focus Session Desk", "File Integrity Ledger"):
            row = items[name]
            self.assertEqual(row["state"], "POST_IDENTITY_UPGRADE")
            self.assertEqual(row["hold_class"], "DELIVERY_HOLD")
            self.assertFalse(row["functional_hold"])
            self.assertTrue(row["product_frozen_for_package"])
            self.assertEqual(row["identity_return"], "VERIFIED")
            self.assertIsNone(row["package_version"])
            self.assertEqual(row["package_version_status"], "AUTHORITATIVE_VALUE_REQUIRED")
            self.assertFalse(row["real_msix"])

    def test_file_integrity_current_gui_candidate_is_pinned_and_not_visually_promoted(self):
        row = next(x for x in self.data["priority"] if x["product"] == "File Integrity Ledger")
        evidence = row["store_assets_evidence"]
        gui = evidence["native_exe_gui"]
        self.assertEqual(gui["run_id"], 45166383111)
        self.assertEqual(gui["tested_head_sha"], "d09973e33daa374dd5a3ba9b4f7a0fabd06987a3")
        self.assertEqual(gui["artifact_id"], 14813448795)
        self.assertEqual(gui["artifact_sha256"], "b6ef57614e6cdf8efdf8314f43f5302dd526fd8c57a5baaef6f2b6de33e0e4a9")
        self.assertTrue(gui["artifact_metadata_verified_by_github_api"])
        self.assertTrue(gui["visual_review_required"])
        self.assertEqual(gui["visual_review_status"], "NOT_INDEPENDENTLY_REVIEWED_FOR_THIS_EXACT_HEAD")
        self.assertEqual(evidence["previous_pre_stack_gui_evidence"]["artifact_id"], 14806249226)

    def test_no_version_is_invented(self):
        for row in self.data["priority"]:
            if "package_version" in row and not row.get("real_msix"):
                self.assertIsNone(row["package_version"])

    def test_priority_is_unique_and_ordered(self):
        ranks = [row["rank"] for row in self.data["priority"]]
        products = [row["product"] for row in self.data["priority"]]
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))
        self.assertEqual(len(products), len(set(products)))


if __name__ == "__main__":
    unittest.main()
