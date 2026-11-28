"""PR165 live-head reconciliation and fail-closed delivery state for 2026-11-29 01:39 JST."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ops" / "active_e2e_handoff.json"
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261129_0139.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261129_0139.json"

EXPECTED_BLOB_SHA = "5ce564c93ce5f4b9ab403651e3fe883eac7b1867"
EXPECTED_BLOB_BYTES = 2214335
EXPECTED_LEDGER_COMMIT = "ba956a11d96eccc0d80418835e4f80276c120733"
EXPECTED_KEY = "latest_execution_reconciliation_20261129_0139"
EXPECTED_HEAD = "a4eea4096673813cb91c6c70f1711b637c356f3b"
EXPECTED_PRODUCT_CODE_HEAD = "71f07b71bf13374f78320fb1e5f9882c8f37b63e"
EXPECTED_RUNS = [46162808044, 46162808104, 46162808059]


class CurrentLiveProductReconciliation0139Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_canonical_ledger_overlay_and_queue_receipts_match(self):
        pointer = self.overlay["canonical_ledger_reconciliation"]
        self.assertEqual(pointer["blob_sha"], EXPECTED_BLOB_SHA)
        self.assertEqual(pointer["bytes"], EXPECTED_BLOB_BYTES)
        self.assertEqual(pointer["canonical_ledger_commit_sha"], EXPECTED_LEDGER_COMMIT)
        self.assertEqual(pointer["latest_canonical_observation_key"], EXPECTED_KEY)
        source = self.queue["source_observation"]
        self.assertEqual(source["canonical_ledger_blob_sha"], EXPECTED_BLOB_SHA)
        self.assertEqual(source["canonical_ledger_bytes"], EXPECTED_BLOB_BYTES)
        self.assertEqual(source["canonical_ledger_commit_sha"], EXPECTED_LEDGER_COMMIT)
        self.assertEqual(self.ledger["latest_execution_reconciliation_key_20261129_0139"], EXPECTED_KEY)
        self.assertEqual(self.ledger["latest_execution_reconciliation_20261129_0139"]["pr165"]["head_sha_at_observation"], EXPECTED_HEAD)
        self.assertTrue(pointer["legacy_snapshot_pointers_preserved"])

    def test_exact_pr165_head_and_three_workflows_are_pinned(self):
        pr = self.overlay["pr165"]
        self.assertEqual(pr["head_sha_at_observation"], EXPECTED_HEAD)
        self.assertEqual(pr["product_code_head_sha"], EXPECTED_PRODUCT_CODE_HEAD)
        self.assertEqual(pr["head_compare"], {"status": "ahead", "ahead_by": 358, "behind_by": 0})
        self.assertEqual([x["run_id"] for x in pr["exact_head_ci"]], EXPECTED_RUNS)
        self.assertTrue(all(x["conclusion"] == "success" and x["head_sha"] == EXPECTED_HEAD for x in pr["exact_head_ci"]))
        self.assertEqual(pr["product_e2e_status"], "HOLD")
        self.assertEqual(pr["product_code_to_snapshot_compare"]["ahead_by"], 12)
        self.assertFalse(self.overlay["snapshot_branch_state"]["product_code_changed"])
        self.assertFalse(self.overlay["e2e_pass"])
        self.assertIn("ops/active_e2e_handoff_overlay_20261129_0058.json", self.overlay["reconciles_against"])

    def test_focus_and_file_current_source_identity_and_version_holds(self):
        products = self.overlay["products"]
        focus = products["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(focus["identity"]["current_source_binding_status"], "STALE_HISTORICAL_SOURCE_MISMATCH")
        self.assertEqual(focus["identity"]["historical_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertIsNone(focus["package_version"])
        self.assertFalse(focus["real_msix"])
        self.assertFalse(focus["store_assets"]["regeneration_or_modification_by_36"])
        filep = products["file_integrity_ledger"]
        self.assertEqual(filep["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertFalse(filep["identity"]["current_source_approved_identity_present"])
        self.assertEqual(filep["identity"]["approved_identity_path_readback"], "NOT_FOUND_404")
        self.assertIsNone(filep["package_version"])
        self.assertEqual(filep["current_source_request"]["status"], "DRY_RUN")
        self.assertFalse(filep["real_msix"])
        self.assertEqual(self.overlay["authoritative_version_discovery"]["decision"], "KEEP_VERSION_HOLD__DO_NOT_INFER_OR_WRITE_VERSION")

    def test_transport_is_fail_closed_but_no_real_package_or_downstream_receipts_exist(self):
        self.assertEqual(self.overlay["transport_contract"]["status"], "IMPLEMENTED_FAIL_CLOSED__EXACT_HEAD_CI_PASS")
        self.assertEqual(self.overlay["first_unconnected_interval"]["status"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        self.assertFalse(self.overlay["transport_contract"]["real_product_msix_received"])
        for field in ("real_msix", "github_backlog_receipt", "local_pull_receipt", "local_checker_receipt", "local_gui_install_receipt"):
            self.assertIs(self.overlay["pr165"][field], False)
        self.assertFalse(self.overlay["e2e_pass"])
        self.assertFalse(self.queue["e2e_pass"])

    def test_pr161_pr171_and_store_authority_remain_separate(self):
        self.assertEqual(self.overlay["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(self.overlay["pr161"]["exact_head_ci"][0]["run_id"], 42712757936)
        self.assertEqual(self.overlay["pr171"]["head_sha"], "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(self.overlay["pr171"]["exact_head_ci"][0]["run_id"], 44437197470)
        self.assertEqual(self.overlay["pr171"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.overlay["pr171"]["dry_run_started"])
        self.assertFalse(self.overlay["pr171"]["live_started"])
        self.assertFalse(self.overlay["safety"]["store_submission_allowed"])
        self.assertFalse(self.overlay["safety"]["certification_allowed"])
        self.assertFalse(self.overlay["safety"]["publish_allowed"])
        self.assertFalse(self.overlay["safety"]["merge_allowed"])
        self.assertFalse(self.overlay["safety"]["force_push_allowed"])
        self.assertEqual(self.queue["status"], "HOLD")
        self.assertFalse(self.queue["e2e_pass"])

    def test_local_code_sync_is_not_promoted_from_cloud_ci(self):
        sync = self.overlay["local_code_sync_receipt_status"]
        self.assertEqual(sync["status"], "NOT_OBSERVED__NO_USER_PC_RECEIPT_IN_CURRENT_RUN")
        self.assertFalse(sync["cloud_ci_promoted_to_local_pass"])


if __name__ == "__main__":
    unittest.main()
