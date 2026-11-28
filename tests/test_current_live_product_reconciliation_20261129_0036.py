"""Exact current E2E ledger and Provisioner observation for 2026-11-29 00:36 JST."""
import hashlib
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER_REL = "ops/active_e2e_handoff.json"
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261129_0036.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261129_0036.json"
EXPECTED_BLOB_SHA = "dfe1b1d6ad47501fb0f3959048e930aa31c8ce84"
EXPECTED_BLOB_BYTES = 2107871
EXPECTED_LEDGER_COMMIT = "d2fef2ee2a16cc4b0723b247b6ef0118fbad22e0"
EXPECTED_OBSERVATION_KEY = "latest_execution_reconciliation_20261129_0036"
EXPECTED_PR165_HEAD = "71f07b71bf13374f78320fb1e5f9882c8f37b63e"
EXPECTED_PR165_RUNS = [46156434417,46156434402,46156434415]
EXPECTED_3D_PR11_HEAD = "356cb7bcbf795c3335fb142cf82fef2db3a7478a"
EXPECTED_3D_PR10_HEAD = "894775ae23cb5c8a6daca959b04804918ec255b9"
EXPECTED_3D_SOURCE_HEAD = "b03ce7b16c3f75c04fe20fdda224c45849eeba0d"
EXPECTED_3D_QA_ARTIFACT_SHA256 = "a02ed2a03ef37ebdb4dc46ad31c84148da3949fb1e55c5b0e0ae3627769f1b9f"
EXPECTED_3D_RUNS = [46099215677, 46099215673]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


class CurrentLiveProductReconciliation0036Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob_sha = git("rev-parse", f"HEAD:{LEDGER_REL}").decode("ascii").strip()
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
        self.assertEqual(self.queue["source_observation"]["canonical_ledger_blob_sha"], self.blob_sha)
        self.assertEqual(self.queue["source_observation"]["canonical_ledger_bytes"], len(self.raw_blob))

    def test_timestamped_pr165_pointer_and_exact_head_ci(self):
        self.assertEqual(self.ledger["latest_execution_reconciliation_key_20261129_0036"], EXPECTED_OBSERVATION_KEY)
        self.assertEqual(self.ledger["pr165_current_head_reconciled_as_of_20261129_0036"], EXPECTED_PR165_HEAD)
        self.assertEqual(self.ledger["pr165_current_head_reconciled_ci_status_20261129_0036"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(self.ledger["pr165_current_head_ci_run_ids_20261129_0036"], EXPECTED_PR165_RUNS)
        self.assertEqual(self.overlay["pr165"]["head_sha_at_observation"], EXPECTED_PR165_HEAD)
        self.assertEqual(self.overlay["pr165"]["head_compare"], {"status":"ahead","ahead_by":346,"behind_by":0})
        self.assertEqual(self.overlay["pr165"]["product_e2e_status"], "HOLD")
        self.assertFalse(self.ledger["e2e_pass"])
        for field in ("real_msix","github_backlog_receipt","local_pull_receipt","local_checker_receipt","local_gui_install_receipt"):
            self.assertIs(self.overlay["pr165"][field], False)

    def test_focus_and_file_current_source_identity_and_version_holds(self):
        focus = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(focus["identity"]["current_source_binding_status"], "STALE_HISTORICAL_SOURCE_MISMATCH")
        self.assertEqual(focus["identity"]["historical_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertIsNone(focus["package_version"])
        file_product = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(file_product["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertIs(file_product["identity"]["current_source_approved_identity_present"], False)
        self.assertIsNone(file_product["package_version"])
        self.assertIs(file_product["real_msix"], False)

    def test_3d_provisioner_current_head_and_no_secret_gate(self):
        obs = self.overlay["repository_provisioner_3d"]
        self.assertEqual(obs["pr11"]["head_sha"], EXPECTED_3D_PR11_HEAD)
        self.assertEqual(obs["pr11"]["base_sha"], EXPECTED_3D_PR10_HEAD)
        self.assertEqual(obs["factory_source"]["head_sha"], EXPECTED_3D_SOURCE_HEAD)
        self.assertEqual(obs["pr11"]["exact_head_ci"][0]["run_id"], EXPECTED_3D_RUNS[0])
        self.assertEqual(obs["pr11"]["exact_head_ci"][1]["run_id"], EXPECTED_3D_RUNS[1])
        self.assertEqual(obs["pr11"]["exact_head_ci"][1]["jobs"][1]["conclusion"], "skipped")
        self.assertFalse(obs["pr11"]["product_msix_created"])
        self.assertEqual(obs["qa_custody_artifact"]["sha256"], EXPECTED_3D_QA_ARTIFACT_SHA256)
        self.assertTrue(obs["pr11"]["no_secret_build"]["secret_storage_prohibited"])
        self.assertFalse(obs["pr11"]["no_secret_build"]["real_product_workflow_dispatched"])
        self.assertEqual(obs["pr11"]["physical_windows_qa"]["sessions_completed"], 0)
        self.assertEqual(obs["pr11"]["physical_windows_qa"]["screenshots_captured"], 0)

    def test_pr161_pr171_and_store_safety_remain_separate(self):
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
        self.assertFalse(self.ledger["e2e_pass"])

    def test_legacy_pointers_and_completion_order_are_preserved(self):
        self.assertEqual(self.ledger["latest_execution_reconciliation_key"], "latest_execution_reconciliation_20261126_133835")
        self.assertEqual(self.ledger["pr165_latest_live_observation_key"], "pr165_live_head_observation_20261126_045730")
        self.assertEqual(self.ledger["current_priority_products"][0]["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(self.ledger["latest_execution_reconciliation_key_20261128_2335"], "latest_execution_reconciliation_20261128_2335")
        self.assertFalse(self.queue["new_product_generation_allowed"])
        self.assertEqual([item["product"] for item in self.queue["priority"]], ["Focus Session Desk","File Integrity Ledger","Prism Route 3D","Signal Sprint"])
        self.assertEqual(self.queue["status"], "HOLD")
        self.assertFalse(self.queue["e2e_pass"])


if __name__ == "__main__":
    unittest.main()
