"""Fail-closed review HEAD reconciliation: live code is not a new product source.

The CI fixture checks ledger consistency. It does not independently re-fetch
GitHub refs, run user Windows, or validate a Store package.
"""
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"


class ReviewHeadReconciliation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.revision = cls.ledger["revision_review_reconciliation"]
        cls.obs = cls.revision["observations"]
        cls.proof = cls.revision["review_head_recheck"]

    def test_jp_candidate_latest_head_does_not_promote(self):
        jp = self.obs["jp-bookkeeping-desk"]
        proof = self.proof["jp_bookkeeping"]
        self.assertEqual(jp["current_review_head_sha"], "32c5976971d1494e205156b8ad27c89598cb2f46")
        self.assertEqual(jp["previous_review_head_sha"], "24e8beade64177cafd0d545d84392304b53dfe51")
        self.assertEqual((proof["ahead"], proof["behind"]), (14, 0))
        self.assertEqual(proof["ci_run_id"], 41375747240)
        self.assertEqual(jp["promotion_status"], "CANDIDATE_ONLY")
        self.assertIsNone(jp["immutable_promoted_source_sha"])
        self.assertIsNone(jp["immutable_request_id"])
        intake = next(p for p in self.ledger["accounting_candidate_intake"]["products"]
                      if p["slug"] == "jp-bookkeeping-desk")
        self.assertEqual(intake["observed_factory_pr_head"], jp["current_review_head_sha"])
        self.assertIsNone(intake["source_sha"])
        self.assertIsNone(intake["request_id"])
        self.assertEqual(jp["identity_status"], "NOT_YET_REQUIRED")
        self.assertEqual(jp["package_gate"], "HOLD")
        self.assertEqual(jp["physical_windows_gui"], "NOT_VERIFIED")

    def test_3d_qa_latest_head_not_sentinel_cas(self):
        sentinel = self.obs["prism-route-3d-sentinel"]
        qa = sentinel["independent_3d_qa_pr6"]
        proof = self.proof["three_d_qa"]
        self.assertEqual(qa["review_head_sha"], "4b58f9d3c2ff75be9627f3e8a4dd20194460111d")
        self.assertEqual((proof["ahead"], proof["behind"]), (5, 0))
        self.assertEqual(qa["ci_run_id"], 41377481988)
        self.assertIn("NOT_FRESH_GITHUB_DOWNLOAD", qa["receipt_evidence_scope"])
        self.assertEqual(sentinel["immutable_sentinel_source_sha"],
                         "e432d94ed0db22878f61f1a8af140d7d7de2288f")
        self.assertFalse(sentinel["new_sentinel_cas_applied"])
        self.assertFalse(qa["new_sentinel_cas_applied"])
        self.assertEqual(qa["real_signed_msix"], "NOT_BUILT")

    def test_game_review_head_distinct_from_artifact_run_and_source(self):
        game = self.obs["signal-sprint-new-lineage"]
        proof = self.proof["game_factory"]
        self.assertEqual(game["current_review_head_sha"], "308749083173e9bc580d1b8eb8485e0077e7c68f")
        self.assertEqual(game["run_head_sha"], "a1af3448cd2edeae5bd54cbaca486a53fd991944")
        self.assertEqual(game["immutable_source_sha"],
                         "c058cbf7fe38e02d929c67d047d717ff74bd522e")
        self.assertEqual((proof["ahead"], proof["behind"]), (3, 0))
        self.assertTrue(game["run_head_is_immutable_artifact_provenance"])
        self.assertFalse(game["current_review_head_is_run_head"])
        self.assertEqual(game["new_artifact_id"], 13105352227)
        self.assertFalse(game["new_lineage_cas_applied"])
        self.assertFalse(game["gdk_msixvc_built"])
        self.assertIn("EXPIRED_404", game["old_artifact_status"])

    def test_no_cloud_to_local_or_sales_promotion(self):
        batch = self.ledger["multi_product_partner_center_batch_4"]
        p = self.proof["batch4"]
        self.assertEqual((p["github_identity_returns"], p["pre_identity_pending"],
                          p["physical_local_processed"]), (2, 2, 0))
        self.assertEqual(batch["processed_count"], 0)
        self.assertEqual(batch["next_resume_index"], 3)
        self.assertFalse(p["scheduled_trigger_proven"])
        self.assertFalse(self.proof["local_code_sync"]["physical_three_sha_reuse_scheduler_receipt"])
        for k in ("real_msix", "backlog", "local_pull", "checker", "gui_qa", "e2e"):
            self.assertFalse(self.proof["sales"][k], k)
        self.assertEqual(self.revision["artifact_byte_preservation_20261102"]["zip_archives_sha256_readback_verified"], 3)
        self.assertEqual(self.obs["offline-image-inventory-desk"]["score"], 64)
        self.assertEqual(self.obs["offline-image-inventory-desk"]["independent_buyers_completed"], 0)
        self.assertFalse(self.ledger["e2e_pass"])


    def test_sale_ready_windows_ux_requires_physical_consumer_journey(self):
        ux = self.ledger["sale_ready_windows_ux_gate"]
        self.assertEqual(ux["gate"], "HOLD_PHYSICAL_WINDOWS_CONSUMER_QA_NOT_OBSERVED")
        self.assertFalse(ux["sale_ready"])
        self.assertEqual(ux["verdict"], "NO")
        self.assertFalse(self.ledger["quality_gates"]["sale_ready_windows_ux_pass"])
        self.assertEqual(self.ledger["quality_gates"]["consumer_would_buy_at_current_price"], "NO")
        self.assertEqual(ux["required_physical_environment"]["min_resolution"], "1024x768")
        self.assertEqual(ux["required_physical_environment"]["dpi_percent"], [125, 150])
        self.assertEqual(ux["required_physical_environment"]["languages"], ["ja-JP", "en-US"])
        for required in ("first_launch", "complete_primary_task", "verify_output_and_location",
                         "restart_and_persistence", "error_recovery_and_retry"):
            self.assertIn(required, ux["required_journey"])
        for required in ("empty_data", "large_data", "read_permission_denied",
                         "corrupt_input", "save_failure"):
            self.assertIn(required, ux["required_negative_inputs"])
        for key in ("physical_windows_receipt_verified", "gui_screenshots_verified",
                    "install_uninstall_verified", "price_approved",
                    "store_listing_image_match_verified"):
            self.assertFalse(ux[key], key)
        self.assertTrue(ux["product_verdicts"])
        for product in ux["product_verdicts"]:
            self.assertEqual(product["consumer_would_buy_at_current_price"], "NO")
            self.assertEqual(product["physical_windows_gui"], "NOT_OBSERVED")
            self.assertFalse(product["sale_ready"])
        self.assertFalse(self.ledger["e2e_pass"])


if __name__ == "__main__":
    unittest.main()
