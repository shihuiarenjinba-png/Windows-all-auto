"""Evidence-only regression for independently observed GAME/3D new revisions.

This fixture reads the central ledger and deliberately refuses to turn an
Artifact or byte-custody receipt into Store package, CAS, local, or E2E PASS.
"""
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"


class NewLineageLedgerRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.revision = cls.data["revision_review_reconciliation"]
        cls.observations = cls.revision["observations"]
        cls.gates = cls.revision["cross_lane_gates"]

    def test_game_new_artifact_is_not_legacy_recovery_or_cas(self):
        g = self.observations["signal-sprint-new-lineage"]
        old = self.observations["signal-sprint"]
        self.assertEqual(g["new_workflow_run_id"], 41361263698)
        self.assertEqual(g["new_artifact_id"], 13105352227)
        self.assertEqual(g["run_head_sha"], "a1af3448cd2edeae5bd54cbaca486a53fd991944")
        self.assertEqual(g["immutable_source_sha"], "c058cbf7fe38e02d929c67d047d717ff74bd522e")
        self.assertNotEqual(g["run_head_sha"], g["immutable_source_sha"])
        self.assertEqual(g["old_artifact_id"], 12706862577)
        self.assertIn("EXPIRED_404", g["old_artifact_status"])
        self.assertIn("UNRESOLVED", old["original_exe_sha_conflict"])
        self.assertTrue(g["exact_new_artifact_bytes_rehashed_by_36"])
        self.assertEqual(g["inner_new_lineage_zip_sha256"], "46aff1ee7570459235c9e7ca7fb1faf6f494dc8100e62b6e132c6d07a6291b71")
        self.assertEqual(g["contained_exe_sha256"], "beb683b61b4fa4b2ec90fe1d413363c8a535bd4cb72b41b54b03a9685f516ee0")
        self.assertFalse(g["new_lineage_cas_applied"])
        self.assertFalse(g["gdk_msixvc_built"])
        self.assertFalse(g["approved_package_version"])
        self.assertEqual(g["registration_type"], "GDK_GAME")
        self.assertIn("HOLD", g["provisioner_validator_compatibility"])
        self.assertTrue(self.gates["game_new_lineage_github_artifact_present"])
        self.assertTrue(self.gates["game_new_lineage_exact_bytes_verified_by_36"])
        self.assertFalse(self.gates["game_new_lineage_cas_pass"])
        self.assertFalse(self.gates["game_gdk_msixvc_pass"])

    def test_sentinel_byte_custody_is_not_identity_rebinding(self):
        s = self.observations["prism-route-3d-sentinel"]
        self.assertEqual(s["current_review_head_sha"], "6b2afaf2adeb5ee4c7cc24d76bcfa1c24db72e1a")
        self.assertEqual(s["immutable_sentinel_source_sha"], "e432d94ed0db22878f61f1a8af140d7d7de2288f")
        self.assertEqual(s["immutable_sentinel_request_id"], "3d-prism-route-3d-e432d94ed0db")
        self.assertEqual(s["byte_custody_archive_bytes"], 30880705)
        self.assertEqual(s["byte_custody_zip_sha256"], "dc60f397e002bddf63a8f64ec263dd241a3eb8c4f7fd6e6595d115a9f273ae9c")
        self.assertEqual(s["byte_custody_exe_sha256"], "66b26ad96df7458ea917b632a73ac7c88bb058db24dbd11a457fd50435ab7b13")
        self.assertEqual(s["byte_custody_pck_sha256"], "3e92b7b6e336a0ab40419448b79f330cf00e0cba4d6bb9ec864ba70b89ecdb03")
        self.assertFalse(s["legacy_pck_matches_sentinel"])
        self.assertEqual(len(s["byte_custody_checks"]), 8)
        self.assertFalse(s["new_sentinel_cas_applied"])
        self.assertFalse(s["approved_package_version"])
        self.assertTrue(self.gates["three_d_sentinel_independent_byte_custody_receipt_verified"])
        self.assertFalse(self.gates["three_d_sentinel_new_revision_cas_pass"])
        new = self.data["other_lanes"]["GAME_3D"]["current_canary"]["sentinel_revision_observation"]
        self.assertFalse(new["legacy_identity_is_new_sentinel_cas"])
        self.assertEqual(new["new_revision_cas"], "HOLD")
        self.assertEqual(new["signed_store_msix"], "NOT_BUILT")

    def test_app_review_heads_never_rebind_immutable_sources(self):
        image = self.observations["offline-image-inventory-desk"]
        self.assertEqual(image["current_review_head_sha"], "9095cb77840fd86f0f73b5649ebbab829effd7da")
        self.assertEqual(image["immutable_pre_identity_source_sha"], "16b6a772952ca0988f2ae2f8b5f4db2e59ec5877")
        self.assertNotEqual(image["current_review_head_sha"], image["immutable_pre_identity_source_sha"])
        self.assertFalse(image["current_review_revision_promoted"])
        self.assertEqual(image["score"], 64)
        self.assertEqual(image["independent_buyers_completed"], 0)
        self.assertEqual(image["market_fit_gate"], "MARKET_FIT_HOLD")
        jp = self.observations["jp-bookkeeping-desk"]
        self.assertEqual(jp["current_review_head_sha"], "24e8beade64177cafd0d545d84392304b53dfe51")
        self.assertEqual(jp["promotion_status"], "CANDIDATE_ONLY")
        self.assertIsNone(jp["immutable_promoted_source_sha"])
        self.assertIsNone(jp["immutable_request_id"])

    def test_batch4_and_physical_gates_still_unproven(self):
        b = self.data["multi_product_partner_center_batch_4"]
        self.assertEqual(b["cloud_preflight_discovered_count"], 4)
        self.assertEqual(b["processed_count"], 0)
        self.assertEqual(b["trigger_proof"], "BATCH_SCHEDULE_TRIGGER_NOT_PROVEN")
        self.assertEqual(
            (self.gates["app_github_identity_returned"], self.gates["app_pre_identity_pending"],
             self.gates["app_local_processed"]), (2, 2, 0)
        )
        for k in ("scheduled_trigger_proven", "physical_local_code_sync_receipt_verified",
                  "local_task_scheduler_last_result_verified", "real_msix_pass",
                  "github_real_product_backlog_pass", "local_pull_pass", "checker_pass",
                  "gui_install_pass", "e2e_pass"):
            self.assertFalse(self.gates[k], k)
        self.assertFalse(self.data["e2e_pass"])


if __name__ == "__main__":
    unittest.main()
