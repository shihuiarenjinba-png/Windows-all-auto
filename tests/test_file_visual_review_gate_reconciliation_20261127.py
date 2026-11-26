import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TS = "2026-11-26T16:39:37Z"
PR165_HEAD = "84f9a3480e2df93f0d75bddc29fb8de47e4ec941"
PR192_HEAD = "792a6ab7bc1a5847c03ebf59e07354edb3d3afb0"
PR193_HEAD = "4dcebd43db89da144ac0cd1a3bf3506b5d366426"


class FileVisualReviewGateReconciliation20261127Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = json.loads((ROOT / "ops/completion_rush_queue_20261116.json").read_text(encoding="utf-8"))
        cls.overlay = json.loads((ROOT / "ops/active_e2e_handoff_overlay_20261126_163937.json").read_text(encoding="utf-8"))
        cls.file_product = next(x for x in cls.queue["priority"] if x["product"] == "File Integrity Ledger")

    def test_completed_visual_review_is_not_an_outstanding_package_blocker(self):
        f = self.file_product
        self.assertEqual(self.queue["generated_at"], TS)
        self.assertEqual(f["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(f["human_visual_review_status"], "PASS")
        self.assertEqual(f["human_visual_review_observed_at_utc"], "2026-11-26T13:30:25Z")
        self.assertIs(f["human_visual_review_required"], False)
        self.assertIs(f["immutable_receipt_visual_review_required"], True)
        self.assertNotIn("human_visual_review", [x["field"] for x in f["package_blockers"]])
        self.assertEqual(
            f["source_selection_status"],
            "INTEGRATED_CANDIDATE_PR115__AWAITING_CURRENT_SOURCE_IDENTITY_AND_AUTHORITATIVE_VERSION",
        )
        original_receipt = f["store_assets_evidence"]["native_exe_gui"]
        self.assertIs(original_receipt["visual_review_required"], True)

    def test_clearing_visual_review_does_not_clear_identity_version_or_msix_gates(self):
        f = self.file_product
        self.assertEqual(f["current_source_identity_binding_status"], "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
        self.assertIs(f["approved_identity_file_present_on_current_pr115_head"], False)
        self.assertIsNone(f["package_version"])
        self.assertIs(f["real_msix"], False)
        blockers = {x["field"]: x["status"] for x in f["package_blockers"]}
        self.assertEqual(blockers["current_source_identity_binding"], "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
        self.assertEqual(blockers["package_version"], "AUTHORITATIVE_VALUE_REQUIRED")
        self.assertEqual(blockers["real_msix_transport"], "NOT_VERIFIED")

    def test_exact_heads_and_ci_are_recorded_without_promoting_product_e2e(self):
        o = self.overlay
        self.assertEqual(o["observed_at_utc"], TS)
        self.assertEqual(o["pr165"]["head_sha"], PR165_HEAD)
        self.assertTrue(all(x["head_sha"] == PR165_HEAD and x["conclusion"] == "success" for x in o["pr165"]["exact_head_ci"]))
        self.assertEqual(o["pr192_local_pull_transport"]["head_sha"], PR192_HEAD)
        self.assertTrue(all(x["head_sha"] == PR192_HEAD and x["conclusion"] == "success" for x in o["pr192_local_pull_transport"]["exact_head_ci"]))
        self.assertEqual(o["pr193_ledger_reconciliation"]["head_sha"], PR193_HEAD)
        self.assertEqual(o["pr193_ledger_reconciliation"]["exact_head_ci"][0]["run_id"], 45858443725)
        self.assertEqual(o["e2e_status"], "HOLD")
        self.assertIs(o["e2e_pass"], False)
        self.assertIs(o["real_msix"], False)
        self.assertIs(o["local_pull_receipt"], False)
        self.assertIs(o["local_checker_receipt"], False)
        self.assertIs(o["local_gui_install_receipt"], False)

    def test_store_upload_bridge_remains_in_pr171_but_has_no_eligible_candidate(self):
        o = self.overlay
        self.assertTrue(o["pr171"]["bridge_present"])
        self.assertEqual(o["pr171"]["eligible_fresh_unsold_products"], 0)
        self.assertIs(o["pr171"]["dry_run_started"], False)
        self.assertEqual(o["windows_automator_pin"]["commit_sha"], "d3b8ed4ae7762a69d3fe2a90b64aa86ee938259b")
        self.assertEqual(o["windows_automator_pin"]["ci_conclusion"], "success")
        self.assertEqual(o["store_upload_test_eligibility_current"]["eligible_fresh_unsold_products"], 0)
        self.assertIs(o["store_upload_test_eligibility_current"]["dry_run_started"], False)
        self.assertIs(o["safety"]["store_submission_allowed"], False)
        self.assertIs(o["safety"]["certification_allowed"], False)
        self.assertIs(o["safety"]["publish_allowed"], False)


if __name__ == "__main__":
    unittest.main()
