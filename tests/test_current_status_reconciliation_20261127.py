import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL = ROOT / "ops/active_e2e_handoff_overlay_20261126_203204.json"
CURRENT = ROOT / "ops/active_e2e_handoff_overlay_20261127_0731.json"
QUEUE = ROOT / "ops/completion_rush_queue_20261127_0731.json"


class CurrentStatusReconciliation20261127Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.historical = json.loads(HISTORICAL.read_text(encoding="utf-8"))
        cls.current = json.loads(CURRENT.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_previous_observation_is_preserved_as_history(self):
        self.assertEqual(self.historical["observed_at_utc"], "2026-11-26T20:32:04Z")
        self.assertEqual(self.historical["status"], "HOLD")
        self.assertFalse(self.historical["e2e_pass"])

    def test_current_pr165_head_and_exact_ci_are_directly_reconciled(self):
        pr = self.current["pr165"]
        self.assertEqual(pr["head_sha"], "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertEqual(pr["parent_sha"], "6afe5ec89a440880066bee43a61f596a5939761d")
        self.assertEqual(pr["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in pr["exact_head_ci"]], [45899687528,45899687437,45899687545])
        self.assertTrue(all(x["head_sha"] == pr["head_sha"] and x["conclusion"] == "success" for x in pr["exact_head_ci"]))
        self.assertEqual(pr["product_e2e_status"], "HOLD")
        self.assertFalse(pr["real_msix"])

    def test_focus_and_file_are_bound_to_their_current_factory_heads(self):
        focus = self.current["products"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(focus["state"], "POST_IDENTITY_UPGRADE")
        self.assertEqual(focus["current_source_request_status"], "STALE_SOURCE_MISMATCH__REGENERATION_REQUIRED")
        self.assertEqual(focus["stale_source_request"]["source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["identity"]["historical_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertFalse(focus["identity"]["current_source_reuse_allowed"])
        self.assertIsNone(focus["package_version"])
        self.assertFalse(focus["real_msix"])

        file_item = self.current["products"]["file_integrity_ledger"]
        self.assertEqual(file_item["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(file_item["state"], "WAITING_USER_IDENTITY")
        self.assertEqual(file_item["current_source_request"]["request_id"], "app-file-integrity-ledger-33d612be2774")
        self.assertFalse(file_item["identity"]["current_source_approved_identity_present"])
        self.assertEqual(file_item["identity"]["historical_identity_source_sha"], "d1108d12f7d1697af30400f97c7db39cba5e6791")
        self.assertIsNone(file_item["package_version"])
        self.assertFalse(file_item["real_msix"])

    def test_canonical_ledger_stale_pointer_is_explicit_and_not_rewritten(self):
        ledger = self.current["canonical_ledger_reconciliation"]
        self.assertEqual(ledger["blob_sha"], "5e764d88bcc7d5f101557dfb547cfab48d7d5145")
        self.assertEqual(ledger["recorded_pr165_current_branch_head_sha"], "86b6aa06205010c8ad90f16a3de52dbe6dc9fe23")
        self.assertEqual(ledger["actual_pr165_head_sha"], "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertTrue(ledger["mismatch"])
        self.assertIn("intentionally not rewritten", ledger["resolution"])

    def test_current_queue_points_to_current_overlay_and_restack_chain_is_green(self):
        self.assertEqual(self.queue["current_status_reconciliation_file"], "ops/active_e2e_handoff_overlay_20261127_0731.json")
        self.assertEqual(self.queue["generated_at"], "2026-11-26T22:31:21Z")
        self.assertEqual([x["pr"] for x in self.queue["restack_chain_current_20261127_0731"]], [197,198,202,203,204])
        self.assertTrue(all(x["ci_status"] == "PASS_EXACT_HEAD_CI" for x in self.queue["restack_chain_current_20261127_0731"]))
        self.assertEqual(self.queue["status"], "HOLD")
        self.assertFalse(self.queue["e2e_pass"])

    def test_all_downstream_and_store_authority_gates_remain_false(self):
        for value in self.current["downstream_receipts"].values():
            self.assertFalse(value)
        self.assertEqual(self.current["store_upload_test_eligibility_current"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.current["store_upload_test_eligibility_current"]["dry_run_started"])
        self.assertFalse(self.current["store_upload_test_eligibility_current"]["live_started"])
        self.assertFalse(self.current["safety"]["live_partner_center_write_allowed"])
        self.assertFalse(self.current["safety"]["store_submission_allowed"])
        self.assertFalse(self.current["safety"]["certification_allowed"])
        self.assertFalse(self.current["safety"]["publish_allowed"])
        self.assertEqual(self.current["local_code_sync_receipt_status"], "NOT_OBSERVED__CLOUD_PASS_ONLY")


if __name__ == "__main__":
    unittest.main()
