import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ops" / "active_e2e_handoff.json"
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261126_084205.json"


class LocalCodeSyncSourceRefObservation20261126Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))

    def test_pr165_current_branch_head_exact_ci_is_separate_from_product_e2e(self):
        d = self.ledger
        obs = d["pr165_live_branch_head_observation_20261126_084205"]
        self.assertEqual(obs["head_sha"], "74dee49585edbeee7eb66d58ff9fa2ea0b97e27f")
        self.assertEqual(obs["parent_sha"], "68fdccd2edf55538b2898c3c67b39f678004a6f9")
        self.assertEqual(obs["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in obs["exact_head_ci"]], [45758828791, 45758828777, 45758828792])
        self.assertTrue(all(x["head_sha"] == obs["head_sha"] and x["conclusion"] == "success" for x in obs["exact_head_ci"]))
        self.assertFalse(obs["product_code_changed"])
        self.assertEqual(obs["product_e2e_status"], "HOLD")
        self.assertIs(obs["e2e_pass"], False)
        self.assertIs(d["e2e_pass"], False)
        self.assertEqual(d["e2e_status"], "HOLD")
        self.assertEqual(d["pr165_latest_live_head_sha"], "380d4818330688f47d3558217ed556868cf0b744")
        self.assertEqual(d["pr165_latest_live_observation_key"], "pr165_live_head_observation_20261126_045730")

    def test_exact_three_sha_tuple_and_current_source_refs_are_recorded(self):
        d = self.ledger["local_code_sync_source_ref_verification_20261126_084205"]
        self.assertEqual(d["overall_status"], "HOLD_LOCAL_WINDOWS_EXECUTION_NOT_AVAILABLE")
        self.assertEqual(d["exact_three_sha_tuple"], {
            "local_sync_tooling_commit": "b962910095adcdbcee7fb0c1ef12e4fb3575c9e8",
            "signal_sprint_source_sha": "1a349faa41663c417c40710140a4d50c79b62b78",
            "prism_route_3d_source_sha": "b03ce7b16c3f75c04fe20fdda224c45849eeba0d",
        })
        signal = next(x for x in d["targets"] if x["product"] == "Signal Sprint")
        self.assertEqual(signal["repository"], "shihuiarenjinba-png/AI-Game-Factory")
        self.assertEqual(signal["branch"], "codex/signal-sprint-frozen-source-ref-20261124")
        self.assertEqual(signal["source_sha"], "1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertTrue(signal["branch_head_verified"])
        self.assertIsNone(signal["first_run_receipt"])
        prism = next(x for x in d["targets"] if x["product"] == "Prism Route 3D")
        self.assertEqual(prism["repository"], "shihuiarenjinba-png/3d-game-factory")
        self.assertEqual(prism["branch"], "codex/prism-tower1-hud-clearance-fix-20261103")
        self.assertEqual(prism["source_sha"], "b03ce7b16c3f75c04fe20fdda224c45849eeba0d")
        self.assertTrue(prism["branch_head_verified"])
        self.assertIsNone(prism["first_run_receipt"])

    def test_offline_notes_and_prism_identity_remain_fail_closed(self):
        d = self.ledger["local_code_sync_source_ref_verification_20261126_084205"]
        offline = next(x for x in d["targets"] if x["product"] == "Offline Notes Canary")
        self.assertEqual(offline["status"], "HOLD_SOURCE_NOT_FIXED")
        self.assertEqual(offline["factory_state"]["stage"], "research")
        self.assertIsNone(offline["factory_state"]["slug"])
        self.assertIsNone(offline["request_id"])
        self.assertIsNone(offline["immutable_product_source_sha"])
        self.assertTrue(offline["candidate_sha_must_not_be_used"])
        prism = next(x for x in d["targets"] if x["product"] == "Prism Route 3D")
        self.assertEqual(prism["approved_identity_source_sha"], "15fdcb52e46e35e6de8e87c55af99719c21e09b9")
        self.assertNotEqual(prism["approved_identity_source_sha"], prism["source_sha"])
        self.assertFalse(prism["approved_identity_reuse_for_current_source_allowed"])
        self.assertIsNone(prism["package_version"])

    def test_no_local_receipts_or_store_authority_are_invented(self):
        d = self.ledger
        sync = d["local_code_sync_source_ref_verification_20261126_084205"]
        self.assertFalse(sync["local_execution"]["physical_user_windows_session_available"])
        self.assertFalse(sync["local_execution"]["powershell_available"])
        self.assertFalse(sync["local_execution"]["windows_task_scheduler_available"])
        self.assertIs(sync["local_execution"]["local_code_sync_pass"], False)
        self.assertEqual(d["local_code_sync_current_observation"]["status"], "CLOUD_PASS_ONLY")
        self.assertEqual(d["local_code_sync_receipt_status_20261126_latest"], "NOT_OBSERVED__CLOUD_PASS_ONLY")
        self.assertIsNone(next(x for x in sync["targets"] if x["product"] == "Signal Sprint")["task_scheduler_receipt"])
        self.assertIsNone(next(x for x in sync["targets"] if x["product"] == "Prism Route 3D")["idempotent_reuse_receipt"])
        for key in ("store_submission_allowed", "certification_allowed", "publish_allowed"):
            self.assertIs(d[key], False)
        self.assertIs(d["local_code_sync_source_ref_verification_20261126_084205"]["safety"]["cas_applied"], False)

    def test_overlay_matches_the_central_holds(self):
        o = self.overlay
        self.assertEqual(o["status"], "HOLD")
        self.assertIs(o["e2e_pass"], False)
        self.assertEqual(o["pr165"]["head_sha"], "74dee49585edbeee7eb66d58ff9fa2ea0b97e27f")
        self.assertEqual(o["pr165"]["product_e2e_status"], "HOLD")
        self.assertEqual(o["local_code_sync"]["overall_three_target_status"], "HOLD")
        self.assertEqual(o["pr171"]["eligible_fresh_unsold_products"], 0)
        self.assertIs(o["safety"]["store_submission_allowed"], False)


if __name__ == "__main__":
    unittest.main()
