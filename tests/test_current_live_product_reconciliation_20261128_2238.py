import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261128_2238.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261128_2238.json"
LEDGER = ROOT / "ops" / "active_e2e_handoff.json"


class CurrentLiveProductReconciliation20261128_2238Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_pr165_exact_head_ci_is_green_but_product_e2e_is_held(self):
        pr = self.overlay["pr165"]
        self.assertEqual(pr["head_sha_at_observation"], "d048c192cb56843ca7648cd4e723313eb587825c")
        self.assertEqual(pr["parent_sha"], "335f2472dc1354b26158ab5667423ca2136aed88")
        self.assertEqual(pr["head_compare"]["ahead_by"], 1)
        self.assertEqual(pr["head_compare"]["behind_by"], 0)
        self.assertEqual(pr["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in pr["exact_head_ci"]], [46149739195, 46149739205, 46149739252])
        self.assertEqual(pr["product_e2e_status"], "HOLD")
        self.assertFalse(pr["real_msix"])
        self.assertFalse(pr["github_backlog_receipt"])
        self.assertFalse(pr["local_pull_receipt"])
        self.assertFalse(pr["local_checker_receipt"])
        self.assertFalse(pr["local_gui_install_receipt"])

    def test_pr161_and_pr171_pins_are_current_and_not_product_e2e(self):
        self.assertEqual(self.overlay["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(self.overlay["pr161"]["exact_head_ci"][0]["run_id"], 42712757936)
        self.assertEqual(self.overlay["pr171"]["head_sha"], "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(self.overlay["pr171"]["exact_head_ci"][0]["run_id"], 44437197470)
        self.assertEqual(self.overlay["pr171"]["eligible_fresh_unsold_products"], 0)

    def test_focus_current_source_request_is_matched_but_identity_and_version_remain_held(self):
        focus = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(focus["current_source_request"]["request_id"], "app-focus-session-desk-b6b69464a9c7")
        self.assertTrue(focus["current_source_request"]["source_matches_current_pr_head"])
        self.assertEqual(focus["current_source_request"]["artifact_id"], 15166202971)
        self.assertEqual(focus["current_source_request"]["artifact_sha256"], "8f1862039297711a68bc33e8e25bea8cfc85f9926b269f0b2136bfa9986b503a")
        self.assertEqual(focus["identity"]["current_source_binding_status"], "STALE_HISTORICAL_SOURCE_MISMATCH")
        self.assertFalse(focus["identity"]["current_source_reuse_allowed"])
        self.assertIsNone(focus["package_version"])
        self.assertFalse(focus["real_msix"])

    def test_file_integrity_has_no_current_approved_identity_and_no_msix(self):
        product = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(product["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertFalse(product["identity"]["current_source_approved_identity_present"])
        self.assertEqual(product["current_source_request"]["status"], "DRY_RUN")
        self.assertTrue(product["current_source_request"]["source_matches_current_pr_head"])
        self.assertEqual(product["asset_staging_map_qa"]["status"], "PASS_MAPPING_ONLY")
        self.assertFalse(product["asset_staging_map_qa"]["real_msix_created"])
        self.assertIsNone(product["package_version"])
        self.assertFalse(product["real_msix"])

    def test_canonical_ledger_points_to_this_reconciliation_and_keeps_hold(self):
        self.assertEqual(self.ledger["latest_execution_reconciliation_key_20261128_2238"], "latest_execution_reconciliation_20261128_2238")
        self.assertEqual(self.ledger["latest_execution_reconciliation_key"], "latest_execution_reconciliation_20261126_133835")
        self.assertEqual(self.ledger["current_priority_products"][0]["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(self.ledger["current_priority_products_live_20261128_2238"][0]["source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(self.ledger["pr165_current_head_reconciled_as_of_20261128_2238"], "d048c192cb56843ca7648cd4e723313eb587825c")
        self.assertEqual(self.ledger["pr165_current_head_reconciled_ci_status_20261128_2238"], "PASS_EXACT_HEAD_CI")
        self.assertFalse(self.ledger["e2e_pass"])
        self.assertEqual(self.ledger["e2e_status"], "HOLD")

    def test_local_and_store_gates_never_promote_from_cloud_ci(self):
        self.assertEqual(self.overlay["local_code_sync_receipt_status"], "NOT_OBSERVED__NO_USER_PC_RECEIPT_IN_CURRENT_RUN")
        self.assertEqual(self.overlay["store_upload_test"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.overlay["store_upload_test"]["dry_run_started"])
        self.assertFalse(self.overlay["safety"]["store_submission_allowed"])
        self.assertFalse(self.overlay["safety"]["certification_allowed"])
        self.assertFalse(self.overlay["safety"]["publish_allowed"])
        self.assertFalse(self.queue["new_product_generation_allowed"])
        self.assertEqual(self.queue["status"], "HOLD")


if __name__ == "__main__":
    unittest.main()
