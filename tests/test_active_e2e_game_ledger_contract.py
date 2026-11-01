"""Regression contract for the active E2E ledger; never re-run historical GAME jobs."""
import json
from pathlib import Path
import unittest

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
CURRENT = "63d358fc8e6d2ad403e405421291155d8583f17a"
HISTORICAL = "e9ae4669f6739d34cad63764767328a3c796a5f9"
PREVIOUS = "4bf0ebf436144bc5eda18c9429506a813e4d4384"
FACTORY_LOG_EXE = "9c31c3633de0d9e248cd1642f9003962f4f117bf6780cf4fab9f66d1d73485ad"
HISTORICAL_EXE = "e8517df8cd31a40e5ce72afdd4e6a4d63626fb99f7ff8a4fa3296ff8deef05f4"


class ActiveE2EGameLedgerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_pr10_current_head_is_separate_from_history(self):
        data = self.data
        active = data["active_product"]
        self.assertEqual(active["provisioner_head_observed"], CURRENT)
        self.assertEqual(data["latest_provisioner_heads_observed"]["game"]["sha"], CURRENT)
        self.assertEqual(data["multi_product_identity_scheduler"]["pre_identity_queue"]["provisioner_head_observed"], CURRENT)
        for section in ("provisioner_package_safety", "provisioner_identity_resume", "provisioner_game_gdk_pr"):
            self.assertEqual(active[section]["head_sha"], CURRENT)
        self.assertEqual(active["local_identity_return_worker"]["required_provisioner_sha"], CURRENT)
        self.assertEqual(active["provisioner_head_observation"]["previous_observed_head"], PREVIOUS)
        self.assertEqual(active["provisioner_game_gdk_pr"]["historical_head_sha"], HISTORICAL)
        self.assertEqual(active["historical_local_commands_20261027"][1].count(HISTORICAL), 1)
        commands = "\n".join(active["local_commands"])
        self.assertNotIn(HISTORICAL, commands)
        self.assertIn("HOLD_PROVISIONER_HEAD_DRIFT", commands)
        self.assertIn("ARTIFACT_EXACT_BYTES_HOLD", commands)
        self.assertNotIn("--apply-request-id", commands)

    def test_original_zip_missing_and_exe_authority_conflict_blocks_cas(self):
        data = self.data
        active = data["active_product"]
        evidence = active["original_exe_artifact_audit"]
        self.assertEqual(evidence["historical_supervisor_exe_sha256"], HISTORICAL_EXE)
        self.assertEqual(evidence["original_factory_job_log_exe_sha256"], FACTORY_LOG_EXE)
        self.assertNotEqual(HISTORICAL_EXE, FACTORY_LOG_EXE)
        self.assertEqual(evidence["original_artifact_availability"], "EXPIRED_404__ORIGINAL_ZIP_NOT_PRESERVED")
        self.assertFalse(evidence["authority_reconciled"])
        self.assertFalse(evidence["original_zip_bytes_verified"])
        self.assertFalse(evidence["ready_for_cas"])
        self.assertFalse(active["cas_returned"])
        self.assertFalse(data["quality_gates"]["real_gdk_msixvc_pass"])
        self.assertFalse(data["e2e_pass"])

    def test_completed_identity_returns_are_not_pre_queue_replayed(self):
        products = {p["product"]: p for p in self.data["post_identity_pipeline"]["products"]}
        for name in ("Focus Session Desk", "File Integrity Ledger", "Prism Route 3D"):
            self.assertEqual(products[name]["identity_status"], "CAS_RETURN_COMMIT_GITHUB_VERIFIED")
            self.assertTrue(products[name]["identity_return_commit_sha"])
        for name in ("Offline Text Diff Desk", "Offline Image Inventory Desk"):
            self.assertEqual(products[name]["identity_status"], "PRE_IDENTITY_READY__NO_APPROVED_FILE")
            self.assertIsNone(products[name]["identity_return_commit_sha"])
        self.assertEqual(products["Offline Notes Canary"]["identity_status"], "USER_IDENTITY_REFERENCE_RECEIVED__SOURCE_REQUEST_UNBOUND")
        self.assertEqual(products["Signal Sprint"]["identity_status"], "USER_IDENTITY_RECEIVED__NO_GITHUB_APPROVED_FILE")
        batch = self.data["multi_product_partner_center_batch_4"]
        self.assertEqual(batch["cloud_preflight_discovered_count"], 4)
        self.assertNotEqual(batch["trigger_proof"], "SCHEDULED_TRIGGER_PROVEN")
        self.assertFalse(self.data["quality_gates"]["local_source_code_sync_physical_pass"])
        self.assertFalse(self.data["quality_gates"]["local_source_code_sync_scheduler_pass"])


if __name__ == "__main__":
    unittest.main()
