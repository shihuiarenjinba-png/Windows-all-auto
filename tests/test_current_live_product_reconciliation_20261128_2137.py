import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ops" / "active_e2e_handoff.json"
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261128_2137.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261128_2137.json"


class CurrentLiveProductReconciliation20261128_2137Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger_bytes = LEDGER.read_bytes()
        cls.ledger = json.loads(cls.ledger_bytes.decode("utf-8"))
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_canonical_ledger_latest_append_matches_current_observation(self):
        pointer = self.overlay["canonical_ledger_reconciliation"]
        git_blob_sha = hashlib.sha1(
            b"blob " + str(len(self.ledger_bytes)).encode("ascii") + b"\\0" + self.ledger_bytes
        ).hexdigest()
        self.assertEqual(git_blob_sha, pointer["blob_sha"])
        self.assertEqual(len(self.ledger_bytes), pointer["bytes"])
        self.assertEqual(self.ledger["pr165_latest_observed_head_sha"], "460de073fcf6a028efe77f13b019f544e7d7831c")
        self.assertEqual(self.ledger["pr165_latest_observed_head_ci_status"], "PASS_EXACT_HEAD_CI")
        latest = self.ledger["latest_execution_reconciliation_20261128_2137"]
        self.assertEqual(latest["pr165"]["head_sha_at_observation"], "460de073fcf6a028efe77f13b019f544e7d7831c")
        self.assertEqual([x["run_id"] for x in latest["pr165"]["exact_head_ci"]], [46141536099, 46141536078, 46141536089])
        self.assertEqual(latest["status"], "HOLD")
        self.assertIs(latest["e2e_pass"], False)

    def test_focus_and_file_identity_gates_are_current_source_bound_or_held(self):
        products = self.ledger["latest_execution_reconciliation_20261128_2137"]["products"]
        focus = products["focus_session_desk"]
        file_product = products["file_integrity_ledger"]
        self.assertEqual(focus["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(focus["identity"]["historical_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertFalse(focus["identity"]["current_source_reuse_allowed"])
        self.assertFalse(focus["current_source_request"]["source_matches_current_pr_head"])
        self.assertIsNone(focus["package_version"])
        self.assertFalse(focus["real_msix"])
        self.assertFalse(file_product["identity"]["current_source_approved_identity_present"])
        self.assertEqual(file_product["current_source_request"]["status"], "DRY_RUN")
        self.assertIsNone(file_product["package_version"])
        self.assertFalse(file_product["real_msix"])

    def test_transport_ci_is_not_product_e2e_and_downstream_stays_closed(self):
        latest = self.ledger["latest_execution_reconciliation_20261128_2137"]
        self.assertEqual(latest["transport_contract"]["status"], "IMPLEMENTED_FAIL_CLOSED__EXACT_HEAD_CI_PASS")
        self.assertFalse(latest["transport_contract"]["real_product_msix_received"])
        self.assertEqual(latest["first_unconnected_interval"]["status"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        self.assertFalse(latest["pr165"]["github_backlog_receipt"])
        self.assertFalse(latest["pr165"]["local_pull_receipt"])
        self.assertFalse(latest["pr165"]["local_checker_receipt"])
        self.assertFalse(latest["pr165"]["local_gui_install_receipt"])

    def test_pr161_pr171_pins_and_store_safety_remain_unchanged(self):
        latest = self.ledger["latest_execution_reconciliation_20261128_2137"]
        self.assertEqual(latest["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(latest["pr171"]["head_sha"], "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(latest["pr171"]["windows_automator_pin"]["commit_sha"], "d3b8ed4ae7762a69d3fe2a90b64aa86ee938259b")
        self.assertIs(self.ledger["store_submission_allowed"], False)
        self.assertIs(self.ledger["certification_allowed"], False)
        self.assertIs(self.ledger["publish_allowed"], False)
        self.assertIs(self.overlay["safety"]["store_submission_allowed"], False)
        self.assertIs(self.overlay["safety"]["certification_allowed"], False)
        self.assertIs(self.overlay["safety"]["publish_allowed"], False)
        self.assertEqual(self.queue["status"], "HOLD")
        self.assertFalse(self.queue["new_product_generation_allowed"])
        self.assertEqual([x["product"] for x in self.queue["priority"]], ["Focus Session Desk", "File Integrity Ledger", "Prism Route 3D", "Signal Sprint"])
        self.assertEqual(self.queue["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.queue["store_upload_test_eligibility"]["dry_run_started"])


if __name__ == "__main__":
    unittest.main()
