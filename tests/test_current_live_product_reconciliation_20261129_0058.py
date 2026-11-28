"""PR165 current snapshot-head exact CI and fail-closed product state for 2026-11-29 00:58 JST."""
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"ops"/"active_e2e_handoff_overlay_20261129_0058.json"
QUEUE=ROOT/"ops"/"completion_rush_queue_20261129_0058.json"
EXPECTED_BLOB_SHA="86c5f81660c18f4893cdf2dd0c0922934f365126"
EXPECTED_BLOB_BYTES=2187228
EXPECTED_LEDGER_COMMIT="afced8eb3a08244e036ff66582a6639102622e31"
EXPECTED_KEY="latest_execution_reconciliation_20261129_0058"
EXPECTED_PR165_HEAD="5a493d55fd2d90d59831fe0104bacee941dd8673"
EXPECTED_PRODUCT_CODE_HEAD="71f07b71bf13374f78320fb1e5f9882c8f37b63e"
EXPECTED_RUNS=[46162605229,46162605222,46162605220]


class CurrentLiveProductReconciliation0058Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay=json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue=json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_canonical_blob_sha_bytes_and_commit_pointer_are_consistent(self):
        pointer=self.overlay["canonical_ledger_reconciliation"]
        self.assertEqual(pointer["blob_sha"],EXPECTED_BLOB_SHA)
        self.assertEqual(pointer["bytes"],EXPECTED_BLOB_BYTES)
        self.assertEqual(pointer["canonical_ledger_commit_sha"],EXPECTED_LEDGER_COMMIT)
        self.assertEqual(pointer["latest_canonical_observation_key"],EXPECTED_KEY)
        source=self.queue["source_observation"]
        self.assertEqual(source["canonical_ledger_blob_sha"],EXPECTED_BLOB_SHA)
        self.assertEqual(source["canonical_ledger_bytes"],EXPECTED_BLOB_BYTES)
        self.assertEqual(source["canonical_ledger_commit_sha"],EXPECTED_LEDGER_COMMIT)

    def test_current_pr165_snapshot_head_and_exact_ci_are_recorded(self):
        pr=self.overlay["pr165"]
        self.assertEqual(pr["head_sha_at_observation"],EXPECTED_PR165_HEAD)
        self.assertEqual(pr["product_code_head_sha"],EXPECTED_PRODUCT_CODE_HEAD)
        self.assertEqual(pr["head_compare"],{"status":"ahead","ahead_by":356,"behind_by":0})
        self.assertEqual([x["run_id"] for x in pr["exact_head_ci"]],EXPECTED_RUNS)
        self.assertTrue(all(x["conclusion"]=="success" and x["head_sha"]==EXPECTED_PR165_HEAD for x in pr["exact_head_ci"]))
        self.assertEqual(pr["product_e2e_status"],"HOLD")
        self.assertFalse(self.overlay["snapshot_branch_state"]["product_code_changed"])
        self.assertFalse(self.overlay["e2e_pass"])

    def test_historical_snapshot_ci_recovery_is_preserved(self):
        recovery=self.overlay["pr165"]["intermediate_ci_recovery"]
        self.assertEqual(len(recovery["failed_snapshots"]),5)
        self.assertEqual(recovery["final_correction_commit"],EXPECTED_PR165_HEAD)
        self.assertEqual(recovery["final_exact_head_ci"],"PASS")
        self.assertTrue(self.overlay["canonical_ledger_reconciliation"]["legacy_snapshot_pointers_preserved"])

    def test_focus_file_and_prism_gates_remain_held(self):
        products=self.overlay["products"]
        focus=products["focus_session_desk"]
        self.assertEqual(focus["identity"]["current_source_binding_status"],"STALE_HISTORICAL_SOURCE_MISMATCH")
        self.assertIsNone(focus["package_version"])
        self.assertFalse(focus["real_msix"])
        filep=products["file_integrity_ledger"]
        self.assertFalse(filep["identity"]["current_source_approved_identity_present"])
        self.assertIsNone(filep["package_version"])
        self.assertFalse(filep["real_msix"])
        prism=self.overlay["repository_provisioner_3d"]
        self.assertEqual(prism["pr11"]["head_sha"],"356cb7bcbf795c3335fb142cf82fef2db3a7478a")
        self.assertEqual(prism["pr11"]["no_secret_build"]["status"],"BLOCKED_GITHUB_SECRET_DEPENDENCY__NO_DISPATCH")
        self.assertFalse(prism["pr11"]["product_msix_created"])
        self.assertEqual(prism["pr11"]["physical_windows_qa"]["sessions_completed"],0)
        self.assertEqual(prism["pr11"]["physical_windows_qa"]["screenshots_captured"],0)

    def test_downstream_receipts_and_store_safety_remain_closed(self):
        pr=self.overlay["pr165"]
        for field in ("real_msix","github_backlog_receipt","local_pull_receipt","local_checker_receipt","local_gui_install_receipt"):
            self.assertIs(pr[field],False)
        self.assertEqual(self.overlay["store_upload_test"]["eligible_fresh_unsold_products"],0)
        self.assertFalse(self.overlay["safety"]["store_submission_allowed"])
        self.assertFalse(self.overlay["safety"]["certification_allowed"])
        self.assertFalse(self.overlay["safety"]["publish_allowed"])
        self.assertFalse(self.overlay["safety"]["merge_allowed"])
        self.assertFalse(self.overlay["safety"]["force_push_allowed"])
        self.assertEqual(self.queue["status"],"HOLD")
        self.assertFalse(self.queue["e2e_pass"])


if __name__=="__main__":
    unittest.main()
