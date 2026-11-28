"""Exact canonical Git blob byte reconciliation for the 2026-11-28 23:35 JST snapshot."""
import hashlib
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER_REL = "ops/active_e2e_handoff.json"
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261128_2335.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261128_2335.json"
EXPECTED_BLOB_SHA = "72e4eaab91291d4268dcda3eb997a722a32aa2ab"
EXPECTED_BLOB_BYTES = 2070904
EXPECTED_LEDGER_COMMIT = "905656dcdd03615019d53e03a25c058128c95d06"
EXPECTED_OBSERVATION_KEY = "latest_execution_reconciliation_20261128_2335"
EXPECTED_PR165_CODE_HEAD = "c35831ed375e84d9551ebe42e9f02dca319d3b26"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


class CurrentLiveProductReconciliation2335Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob_sha = git("rev-parse", f"{EXPECTED_LEDGER_COMMIT}:{LEDGER_REL}").decode("ascii").strip()
        cls.blob_size = int(git("cat-file", "-s", cls.blob_sha).decode("ascii").strip())
        cls.raw_blob = git("cat-file", "blob", cls.blob_sha)
        cls.ledger = json.loads(cls.raw_blob.decode("utf-8"))
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_canonical_git_blob_sha_and_real_byte_size_match(self):
        self.assertEqual(self.blob_sha, EXPECTED_BLOB_SHA)
        self.assertEqual(self.blob_size, EXPECTED_BLOB_BYTES)
        self.assertEqual(len(self.raw_blob), EXPECTED_BLOB_BYTES)
        digest = hashlib.sha1(
            b"blob " + str(len(self.raw_blob)).encode("ascii") + b"\0" + self.raw_blob
        ).hexdigest()
        self.assertEqual(digest, self.blob_sha)
        pointer = self.overlay["canonical_ledger_reconciliation"]
        self.assertEqual(pointer["blob_sha"], self.blob_sha)
        self.assertEqual(pointer["bytes"], len(self.raw_blob))
        self.assertEqual(pointer["canonical_ledger_commit_sha"], EXPECTED_LEDGER_COMMIT)

    def test_timestamped_canonical_pointer_matches_current_observation(self):
        self.assertEqual(self.ledger["latest_execution_reconciliation_key_20261128_2335"], EXPECTED_OBSERVATION_KEY)
        self.assertEqual(self.ledger["pr165_current_head_reconciled_as_of_20261128_2335"], EXPECTED_PR165_CODE_HEAD)
        self.assertEqual(self.ledger["pr165_current_head_reconciled_ci_status_20261128_2335"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(self.ledger["pr165_current_head_ci_run_ids_20261128_2335"], [46152396758, 46152396852, 46152396940])
        self.assertEqual(self.ledger["e2e_status"], "HOLD")
        self.assertIs(self.ledger["e2e_pass"], False)

    def test_legacy_pointers_are_preserved(self):
        self.assertEqual(self.ledger["latest_execution_reconciliation_key"], "latest_execution_reconciliation_20261126_133835")
        self.assertEqual(self.ledger["pr165_latest_live_observation_key"], "pr165_live_head_observation_20261126_045730")
        self.assertEqual(self.ledger["pr165_latest_live_head_sha"], "380d4818330688f47d3558217ed556868cf0b744")
        self.assertEqual(self.ledger["current_priority_products"][0]["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(self.ledger["latest_execution_reconciliation_key_20261128_2238"], "latest_execution_reconciliation_20261128_2238")
        self.assertEqual(self.ledger["pr165_current_head_reconciled_as_of_20261128_2238"], "d048c192cb56843ca7648cd4e723313eb587825c")

    def test_exact_head_ci_is_not_product_e2e(self):
        pr = self.overlay["pr165"]
        self.assertEqual(pr["head_sha_at_observation"], EXPECTED_PR165_CODE_HEAD)
        self.assertEqual(pr["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([item["run_id"] for item in pr["exact_head_ci"]], [46152396758, 46152396852, 46152396940])
        self.assertTrue(all(item["head_sha"] == EXPECTED_PR165_CODE_HEAD and item["conclusion"] == "success"
                            for item in pr["exact_head_ci"]))
        self.assertEqual(pr["product_e2e_status"], "HOLD")
        for field in ("real_msix", "github_backlog_receipt", "local_pull_receipt",
                      "local_checker_receipt", "local_gui_install_receipt"):
            self.assertIs(pr[field], False)

    def test_focus_and_file_integrity_keep_identity_and_version_holds(self):
        focus = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(focus["identity"]["current_source_binding_status"], "STALE_HISTORICAL_SOURCE_MISMATCH")
        self.assertEqual(focus["identity"]["historical_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertIsNone(focus["package_version"])
        self.assertIs(focus["real_msix"], False)
        file_product = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(file_product["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertIs(file_product["identity"]["current_source_approved_identity_present"], False)
        self.assertEqual(file_product["current_source_request"]["status"], "DRY_RUN")
        self.assertIsNone(file_product["package_version"])
        self.assertIs(file_product["real_msix"], False)

    def test_pr161_pr171_and_store_bridge_are_separate_from_product_e2e(self):
        self.assertEqual(self.overlay["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(self.overlay["pr161"]["exact_head_ci"][0]["run_id"], 42712757936)
        self.assertEqual(self.overlay["pr171"]["head_sha"], "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(self.overlay["pr171"]["exact_head_ci"][0]["run_id"], 44437197470)
        self.assertEqual(self.overlay["pr171"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.overlay["pr171"]["dry_run_started"])
        self.assertFalse(self.overlay["pr171"]["live_started"])

    def test_local_store_and_repository_authority_remain_closed(self):
        self.assertEqual(self.overlay["local_code_sync_receipt_status"], "NOT_OBSERVED__NO_USER_PC_RECEIPT_IN_CURRENT_RUN")
        self.assertFalse(self.overlay["store_upload_test"]["dry_run_started"])
        self.assertEqual(self.overlay["store_upload_test"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.overlay["safety"]["store_submission_allowed"])
        self.assertFalse(self.overlay["safety"]["certification_allowed"])
        self.assertFalse(self.overlay["safety"]["publish_allowed"])
        self.assertFalse(self.overlay["safety"]["merge_allowed"])
        self.assertFalse(self.overlay["safety"]["force_push_allowed"])
        self.assertFalse(self.ledger["e2e_pass"])

    def test_queue_keeps_existing_product_priority_and_delivery_holds(self):
        self.assertFalse(self.queue["new_product_generation_allowed"])
        self.assertEqual([item["product"] for item in self.queue["priority"]],
                         ["Focus Session Desk", "File Integrity Ledger", "Prism Route 3D", "Signal Sprint"])
        self.assertEqual(self.queue["priority"][0]["hold_class"], "DELIVERY_HOLD")
        self.assertEqual(self.queue["priority"][1]["hold_class"], "DELIVERY_HOLD")
        self.assertEqual(self.queue["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertEqual(self.queue["store_upload_test_eligibility"]["hold"], 2)
        self.assertEqual(self.queue["status"], "HOLD")
        self.assertIs(self.queue["e2e_pass"], False)


if __name__ == "__main__":
    unittest.main()
