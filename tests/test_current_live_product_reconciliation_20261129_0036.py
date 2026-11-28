"""Historical 00:36 JST E2E observation receipt; current ledger bytes are checked by the 00:50 test."""
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"ops"/"active_e2e_handoff_overlay_20261129_0036.json"
QUEUE=ROOT/"ops"/"completion_rush_queue_20261129_0036.json"
EXPECTED_BLOB_SHA="dfe1b1d6ad47501fb0f3959048e930aa31c8ce84"
EXPECTED_BLOB_BYTES=2107871
EXPECTED_LEDGER_COMMIT="d2fef2ee2a16cc4b0723b247b6ef0118fbad22e0"
EXPECTED_OBSERVATION_KEY="latest_execution_reconciliation_20261129_0036"
EXPECTED_PR165_HEAD="71f07b71bf13374f78320fb1e5f9882c8f37b63e"


class CurrentLiveProductReconciliation0036Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay=json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue=json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_historical_canonical_blob_receipt_is_preserved(self):
        pointer=self.overlay["canonical_ledger_reconciliation"]
        self.assertEqual(pointer["blob_sha"],EXPECTED_BLOB_SHA)
        self.assertEqual(pointer["bytes"],EXPECTED_BLOB_BYTES)
        self.assertEqual(pointer["canonical_ledger_commit_sha"],EXPECTED_LEDGER_COMMIT)
        self.assertEqual(pointer["latest_canonical_observation_key"],EXPECTED_OBSERVATION_KEY)
        self.assertTrue(pointer["legacy_snapshot_pointers_preserved"])
        self.assertEqual(self.queue["source_observation"]["canonical_ledger_blob_sha"],EXPECTED_BLOB_SHA)
        self.assertEqual(self.queue["source_observation"]["canonical_ledger_bytes"],EXPECTED_BLOB_BYTES)

    def test_timestamped_pr165_pointer_and_exact_head_ci(self):
        pr=self.overlay["pr165"]
        self.assertEqual(pr["head_sha_at_observation"],EXPECTED_PR165_HEAD)
        self.assertEqual(pr["head_compare"],{"status":"ahead","ahead_by":346,"behind_by":0})
        self.assertEqual(pr["exact_head_ci_status"],"PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in pr["exact_head_ci"]],[46156434417,46156434402,46156434415])
        self.assertEqual(pr["product_e2e_status"],"HOLD")
        for field in ("real_msix","github_backlog_receipt","local_pull_receipt","local_checker_receipt","local_gui_install_receipt"):
            self.assertIs(pr[field],False)

    def test_focus_file_and_3d_identity_version_holds(self):
        focus=self.overlay["products"]["focus_session_desk"]
        self.assertEqual(focus["identity"]["current_source_binding_status"],"STALE_HISTORICAL_SOURCE_MISMATCH")
        self.assertIsNone(focus["package_version"])
        self.assertFalse(focus["real_msix"])
        filep=self.overlay["products"]["file_integrity_ledger"]
        self.assertFalse(filep["identity"]["current_source_approved_identity_present"])
        self.assertIsNone(filep["package_version"])
        self.assertFalse(filep["real_msix"])
        prism=self.overlay["repository_provisioner_3d"]
        self.assertEqual(prism["pr11"]["head_sha"],"356cb7bcbf795c3335fb142cf82fef2db3a7478a")
        self.assertEqual(prism["pr11"]["no_secret_build"]["status"],"BLOCKED_GITHUB_SECRET_DEPENDENCY__NO_DISPATCH")
        self.assertFalse(prism["pr11"]["product_msix_created"])

    def test_pr161_pr171_and_store_safety_remain_separate(self):
        self.assertEqual(self.overlay["pr161"]["head_sha"],"71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(self.overlay["pr161"]["exact_head_ci"][0]["run_id"],42712757936)
        self.assertEqual(self.overlay["pr171"]["head_sha"],"764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(self.overlay["pr171"]["exact_head_ci"][0]["run_id"],44437197470)
        self.assertEqual(self.overlay["pr171"]["eligible_fresh_unsold_products"],0)
        self.assertFalse(self.overlay["pr171"]["dry_run_started"])
        self.assertFalse(self.overlay["pr171"]["live_started"])
        self.assertFalse(self.overlay["safety"]["store_submission_allowed"])
        self.assertFalse(self.overlay["safety"]["certification_allowed"])
        self.assertFalse(self.overlay["safety"]["publish_allowed"])
        self.assertFalse(self.overlay["safety"]["merge_allowed"])
        self.assertFalse(self.overlay["safety"]["force_push_allowed"])

    def test_legacy_pointer_chain_and_completion_order_are_preserved(self):
        pointer=self.overlay["canonical_ledger_reconciliation"]
        self.assertEqual(pointer["previous_blob_sha"],"72e4eaab91291d4268dcda3eb997a722a32aa2ab")
        self.assertEqual(pointer["previous_blob_bytes"],2070904)
        self.assertTrue(pointer["legacy_snapshot_pointers_preserved"])
        self.assertIn("ops/active_e2e_handoff_overlay_20261128_2238.json",self.overlay["reconciles_against"])
        self.assertFalse(self.queue["new_product_generation_allowed"])
        self.assertEqual([x["product"] for x in self.queue["priority"]],["Focus Session Desk","File Integrity Ledger","Prism Route 3D","Signal Sprint"])
        self.assertEqual(self.queue["status"],"HOLD")
        self.assertFalse(self.queue["e2e_pass"])


if __name__=="__main__":
    unittest.main()
