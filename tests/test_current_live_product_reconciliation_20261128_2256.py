import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261128_2256.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261128_2256.json"
LEDGER = ROOT / "ops" / "active_e2e_handoff.json"


class CurrentLiveProductReconciliation20261128_2256Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger_bytes = LEDGER.read_bytes().replace(b"\\r\\n", b"\\n")
        cls.ledger = json.loads(cls.ledger_bytes.decode("utf-8"))
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_current_canonical_blob_and_timestamped_pointer_match(self):
        pointer = self.overlay["canonical_ledger_reconciliation"]
        digest = hashlib.sha1(b"blob " + str(len(self.ledger_bytes)).encode("ascii") + b"\\0" + self.ledger_bytes).hexdigest()
        self.assertEqual(digest, pointer["blob_sha"])
        self.assertEqual(len(self.ledger_bytes), pointer["bytes"])
        self.assertEqual(self.ledger["latest_execution_reconciliation_key_20261128_2238"], "latest_execution_reconciliation_20261128_2238")
        self.assertEqual(self.ledger["pr165_current_head_reconciled_as_of_20261128_2238"], "d048c192cb56843ca7648cd4e723313eb587825c")

    def test_legacy_snapshots_remain_immutable_and_new_live_projection_is_separate(self):
        self.assertEqual(self.ledger["latest_execution_reconciliation_key"], "latest_execution_reconciliation_20261126_133835")
        self.assertEqual(self.ledger["pr165_latest_live_observation_key"], "pr165_live_head_observation_20261126_045730")
        self.assertEqual(self.ledger["pr165_latest_live_head_sha"], "380d4818330688f47d3558217ed556868cf0b744")
        self.assertEqual(self.ledger["current_priority_products"][0]["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(self.ledger["current_priority_products_live_20261128_2238"][0]["source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")

    def test_product_gates_and_exact_head_ci_are_not_promoted_to_e2e(self):
        pr = self.overlay["pr165"]
        self.assertEqual(pr["head_sha_at_observation"], "d048c192cb56843ca7648cd4e723313eb587825c")
        self.assertEqual(pr["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in pr["exact_head_ci"]], [46149739195, 46149739205, 46149739252])
        self.assertEqual(pr["product_e2e_status"], "HOLD")
        self.assertFalse(pr["real_msix"])
        self.assertFalse(pr["github_backlog_receipt"])
        self.assertFalse(pr["local_pull_receipt"])
        self.assertFalse(pr["local_checker_receipt"])
        self.assertFalse(pr["local_gui_install_receipt"])

    def test_focus_file_identity_and_version_remain_fail_closed(self):
        focus = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(focus["current_source_request"]["request_id"], "app-focus-session-desk-b6b69464a9c7")
        self.assertEqual(focus["identity"]["current_source_binding_status"], "STALE_HISTORICAL_SOURCE_MISMATCH")
        self.assertIsNone(focus["package_version"])
        self.assertFalse(focus["real_msix"])
        file_product = self.overlay["products"]["file_integrity_ledger"]
        self.assertFalse(file_product["identity"]["current_source_approved_identity_present"])
        self.assertEqual(file_product["current_source_request"]["status"], "DRY_RUN")
        self.assertIsNone(file_product["package_version"])
        self.assertFalse(file_product["real_msix"])

    def test_local_store_and_repository_safety_remain_closed(self):
        self.assertEqual(self.overlay["local_code_sync_receipt_status"], "NOT_OBSERVED__NO_USER_PC_RECEIPT_IN_CURRENT_RUN")
        self.assertEqual(self.queue["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.queue["store_upload_test_eligibility"]["dry_run_started"])
        self.assertFalse(self.overlay["safety"]["store_submission_allowed"])
        self.assertFalse(self.overlay["safety"]["certification_allowed"])
        self.assertFalse(self.overlay["safety"]["publish_allowed"])
        self.assertFalse(self.ledger["e2e_pass"])


if __name__ == "__main__":
    unittest.main()
