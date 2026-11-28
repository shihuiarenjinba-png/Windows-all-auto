"""Exact PR165 snapshot-head reconciliation and fail-closed product state for 2026-11-29 00:50 JST."""
import hashlib
import json
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"ops"/"active_e2e_handoff_overlay_20261129_0050.json"
QUEUE=ROOT/"ops"/"completion_rush_queue_20261129_0050.json"
LEDGER="ops/active_e2e_handoff.json"
EXPECTED_BLOB_SHA="1126ee5675381b74c12edba4f4fc3ad308565c00"
EXPECTED_BLOB_BYTES=2145028
EXPECTED_LEDGER_COMMIT="d76010c31f173018ca75774ff67b24768fbfd379"
EXPECTED_KEY="latest_execution_reconciliation_20261129_0050"
EXPECTED_PR165_HEAD="edaed39dcfbab7f1c94194a5d438ad3be6399239"
EXPECTED_PRODUCT_CODE_HEAD="71f07b71bf13374f78320fb1e5f9882c8f37b63e"
EXPECTED_RUNS=[46161847628,46161847594,46161847587]


def git(*args):
    return subprocess.check_output(["git",*args],cwd=ROOT)


class CurrentLiveProductReconciliation0050Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob_sha=git("rev-parse",f"HEAD:{LEDGER}").decode("ascii").strip()
        cls.raw=git("cat-file","blob",cls.blob_sha)
        cls.size=int(git("cat-file","-s",cls.blob_sha).decode("ascii").strip())
        cls.ledger=json.loads(cls.raw.decode("utf-8"))
        cls.overlay=json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue=json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_current_canonical_blob_sha_size_and_commit_pointer(self):
        self.assertEqual(self.blob_sha,EXPECTED_BLOB_SHA)
        self.assertEqual(self.size,EXPECTED_BLOB_BYTES)
        self.assertEqual(len(self.raw),EXPECTED_BLOB_BYTES)
        self.assertEqual(hashlib.sha1(b"blob "+str(len(self.raw)).encode("ascii")+b"\\0"+self.raw).hexdigest(),self.blob_sha)
        pointer=self.overlay["canonical_ledger_reconciliation"]
        self.assertEqual(pointer["blob_sha"],self.blob_sha)
        self.assertEqual(pointer["bytes"],len(self.raw))
        self.assertEqual(pointer["canonical_ledger_commit_sha"],EXPECTED_LEDGER_COMMIT)
        self.assertEqual(self.queue["source_observation"]["canonical_ledger_blob_sha"],self.blob_sha)

    def test_pr165_current_snapshot_head_and_exact_ci_are_distinct_from_product_code_head(self):
        self.assertEqual(self.overlay["pr165"]["head_sha_at_observation"],EXPECTED_PR165_HEAD)
        self.assertEqual(self.overlay["pr165"]["product_code_head_sha"],EXPECTED_PRODUCT_CODE_HEAD)
        self.assertEqual(self.overlay["pr165"]["head_compare"],{"status":"ahead","ahead_by":350,"behind_by":0})
        self.assertEqual([x["run_id"] for x in self.overlay["pr165"]["exact_head_ci"]],EXPECTED_RUNS)
        self.assertTrue(all(x["conclusion"]=="success" for x in self.overlay["pr165"]["exact_head_ci"]))
        self.assertEqual(self.overlay["pr165"]["product_e2e_status"],"HOLD")
        self.assertFalse(self.ledger["e2e_pass"])
        self.assertEqual(self.ledger["latest_execution_reconciliation_key_20261129_0050"],EXPECTED_KEY)

    def test_historical_test_recovery_is_recorded_without_rewriting_old_overlay(self):
        recovery=self.overlay["pr165"]["intermediate_ci_recovery"]
        self.assertEqual(recovery["failed_snapshots"][0]["run_id"],46161631198)
        self.assertEqual(recovery["failed_snapshots"][1]["run_id"],46161739861)
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
