import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TS = "2026-11-26T16:10:44Z"
PR165_HEAD = "84f9a3480e2df93f0d75bddc29fb8de47e4ec941"
PR192_HEAD = "792a6ab7bc1a5847c03ebf59e07354edb3d3afb0"


class CurrentTransportRestack20261126_161044Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads((ROOT / "ops/active_e2e_handoff.json").read_text(encoding="utf-8"))
        cls.queue = json.loads((ROOT / "ops/completion_rush_queue_20261116.json").read_text(encoding="utf-8"))
        cls.current = json.loads((ROOT / "ops/active_e2e_handoff_overlay_20261126_161044.json").read_text(encoding="utf-8"))
        cls.historical = json.loads((ROOT / "ops/active_e2e_handoff_overlay_20261126_074400.json").read_text(encoding="utf-8"))

    def test_pr165_branch_tip_and_pr192_restack_are_exact_head_ci_green_only(self):
        old = self.ledger["pr165_branch_tip_observation_20261126_161044"]
        self.assertEqual(old["head_sha"], PR165_HEAD)
        self.assertEqual(old["parent_sha"], "64a57e24a377c33904749fd6deac5d14655ea6d5")
        self.assertEqual(old["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in old["exact_head_ci"]], [45833181013, 45833181073, 45833180930])
        self.assertTrue(all(x["head_sha"] == PR165_HEAD and x["conclusion"] == "success" for x in old["exact_head_ci"]))
        self.assertFalse(old["comparison_to_last_product_code_head"]["product_code_changed"])

        restack = self.ledger["pr192_local_pull_transport_20261126_161044"]
        self.assertEqual(restack["base_sha"], PR165_HEAD)
        self.assertEqual(restack["head_sha"], PR192_HEAD)
        self.assertEqual(restack["status"], "IMPLEMENTED_CI_PASS_NOT_EXECUTED")
        self.assertEqual([x["run_id"] for x in restack["exact_head_ci"]], [45856211088, 45856211096, 45856211210])
        self.assertTrue(all(x["head_sha"] == PR192_HEAD and x["conclusion"] == "success" for x in restack["exact_head_ci"]))
        self.assertEqual(len(restack["changed_files"]), 6)
        for field in ("local_pull_receipt", "windows_checker_receipt", "local_gui_install_receipt", "product_e2e_pass"):
            self.assertIs(restack[field], False)

        self.assertEqual(self.ledger["e2e_status"], "HOLD")
        self.assertIs(self.ledger["e2e_pass"], False)
        self.assertIs(self.ledger["real_msix"], False)
        self.assertIs(self.ledger["github_backlog_receipt"], False)
        self.assertIs(self.ledger["local_pull_receipt"], False)
        self.assertIs(self.ledger["local_checker_receipt"], False)
        self.assertIs(self.ledger["local_gui_install_receipt"], False)

    def test_focus_and_file_current_source_gates_remain_fail_closed(self):
        products = {x["product"]: x for x in self.ledger["current_priority_products_live_20261126_161044"]}
        focus = products["Focus Session Desk"]
        self.assertEqual(focus["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["current_source_request_id"], "app-focus-session-desk-fb6293839bc7")
        self.assertEqual(focus["historical_approved_identity_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(focus["current_source_identity_binding_status"], "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
        self.assertIsNone(focus["package_version"])
        self.assertEqual(focus["owner_visual_signoff_status"], "PENDING_ERROR_RECOVERY")
        self.assertEqual(focus["current_source_exe_artifact_id"], 15083856249)
        self.assertIs(focus["real_msix"], False)

        file_product = products["File Integrity Ledger"]
        self.assertEqual(file_product["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertIs(file_product["approved_identity_file_present_on_current_pr_head"], False)
        self.assertEqual(file_product["human_visual_review_status"], "PASS")
        self.assertTrue(file_product["immutable_receipt_visual_review_required"])
        self.assertEqual(file_product["asset_mapping_qa_pr"], 124)
        self.assertIsNone(file_product["package_version"])
        self.assertIs(file_product["real_msix"], False)

    def test_prism_and_signal_use_current_projection_not_historical_identity_or_missing_artifact_claims(self):
        products = {x["product"]: x for x in self.ledger["current_priority_products_live_20261126_161044"]}
        prism = products["Prism Route 3D"]
        self.assertEqual(prism["current_source_sha"], "b03ce7b16c3f75c04fe20fdda224c45849eeba0d")
        self.assertEqual(prism["historical_approved_identity_source_sha"], "15fdcb52e46e35e6de8e87c55af99719c21e09b9")
        self.assertIs(prism["old_identity_reuse_allowed"], False)
        self.assertIsNone(prism["package_version"])
        self.assertEqual(prism["physical_windows_qa_sessions_completed"], 0)
        self.assertIs(prism["real_msix"], False)

        signal = products["Signal Sprint"]
        self.assertEqual(signal["current_source_sha"], "1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertEqual(signal["historical_request_id"], "game-signal-sprint-c058cbf7fe38e02d929c67d047d717ff74bd522e")
        self.assertEqual(signal["current_build_artifact_id"], 14946655071)
        self.assertEqual(signal["current_gdk_readiness_artifact_id"], 14946675208)
        self.assertEqual(signal["current_identity_preview_status"], "STALE_BUILD_PROVENANCE__REFRESH_REQUIRED")
        self.assertEqual(signal["gdk_sdk_status"], "HOLD_GDK_SDK_ROOT_NOT_FOUND")
        self.assertIs(signal["physical_windows_uia_pass"], False)
        self.assertIs(signal["real_msixvc"], False)

    def test_file_visual_and_asset_map_pass_does_not_clear_identity_or_version_gate(self):
        file_product = self.ledger["current_priority_products_live_20261126_161044"][1]
        self.assertEqual(file_product["human_visual_review_status"], "PASS")
        self.assertEqual(file_product["asset_mapping_qa_head_sha"], "d245b5b0541a09af2de46d092e5525023456f843")
        self.assertEqual(file_product["asset_mapping_qa_run_id"], 45747686529)
        self.assertEqual(file_product["current_source_identity_readback_status"], "NOT_COLLECTED")
        self.assertEqual(file_product["package_version_status"], "AUTHORITATIVE_VALUE_REQUIRED")
        self.assertIs(file_product["real_msix"], False)

    def test_current_pr161_pr171_and_windows_automator_pins_are_directly_read_back(self):
        self.assertEqual(self.ledger["pr161_current_head_readback_20261126_161044"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(self.ledger["pr161_current_head_readback_20261126_161044"]["exact_head_ci"][0]["run_id"], 42712757936)
        self.assertEqual(self.ledger["pr171_current_head_readback_20261126_161044"]["head_sha"], "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(self.ledger["pr171_current_head_readback_20261126_161044"]["exact_head_ci"][0]["run_id"], 44437197470)
        self.assertEqual(self.ledger["windows_automator_pin_readback_20261126_161044"]["pinned_sha"], "d3b8ed4ae7762a69d3fe2a90b64aa86ee938259b")
        self.assertEqual(self.ledger["windows_automator_pin_readback_20261126_161044"]["exact_head_ci"][0]["run_id"], 44319200630)

        self.assertEqual(self.queue["store_upload_test_eligibility_current"]["eligible_fresh_unsold_products"], 0)
        self.assertIs(self.queue["store_upload_test_eligibility_current"]["dry_run_started"], False)
        self.assertIs(self.queue["store_submission_allowed"], False)
        self.assertIs(self.queue["certification_allowed"], False)
        self.assertIs(self.queue["publish_allowed"], False)

    def test_pr188_074400_snapshot_is_historical_and_new_overlay_is_current(self):
        self.assertEqual(self.historical["observed_at_utc"], "2026-11-26T07:44:00Z")
        self.assertEqual(self.historical["pr165"]["head_sha"], "74dee49585edbeee7eb66d58ff9fa2ea0b97e27f")
        self.assertEqual(self.historical["pr187"]["head_sha"], "5ad7b5b9522ef4640481b5c71af301405b1f255b")
        self.assertEqual(self.historical["status"], "HOLD")
        self.assertEqual(self.current["pr165"]["head_sha"], PR165_HEAD)
        self.assertEqual(self.current["pr192_restaked"]["head_sha"], PR192_HEAD)
        self.assertIn("ops/active_e2e_handoff_overlay_20261126_074400.json", self.current["supersedes"])
        self.assertIs(self.current["e2e_pass"], False)

    def test_signal_queue_no_longer_says_the_existing_exe_artifact_is_missing(self):
        signal = next(x for x in self.queue["priority"] if x["product"] == "Signal Sprint")
        self.assertEqual(signal["current_build_artifact_id"], 14946655071)
        self.assertEqual(signal["current_gdk_readiness_artifact_id"], 14946675208)
        self.assertNotIn("no build artifact is configured", signal["next_action"].lower())
        self.assertIn("artifacts do exist", signal["next_action"].lower())
        self.assertEqual(self.queue["current_transport_observation_key"], "pr192_local_pull_transport_20261126_161044")
        self.assertEqual(self.queue["current_transport_reconciliation"]["pr192"]["head_sha"], PR192_HEAD)


if __name__ == "__main__":
    unittest.main()
