import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "ops/completion_rush_queue_20261116.json"
CURRENT = ROOT / "ops/active_e2e_handoff_overlay_20261126_161044.json"
HISTORICAL = ROOT / "ops/active_e2e_handoff_overlay_20261126_074400.json"
PR165_HEAD = "84f9a3480e2df93f0d75bddc29fb8de47e4ec941"
PR192_HEAD = "792a6ab7bc1a5847c03ebf59e07354edb3d3afb0"


class CurrentTransportRestack20261126_161044Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        cls.current = json.loads(CURRENT.read_text(encoding="utf-8"))
        cls.historical = json.loads(HISTORICAL.read_text(encoding="utf-8"))

    def test_pr165_branch_tip_and_pr192_restack_are_exact_head_ci_green_only(self):
        old = self.current["pr165"]
        self.assertEqual(old["head_sha"], PR165_HEAD)
        self.assertEqual(old["parent_sha"], "64a57e24a377c33904749fd6deac5d14655ea6d5")
        self.assertEqual(old["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in old["exact_head_ci"]],
                         [45833181013, 45833181073, 45833180930])
        self.assertTrue(all(x["head_sha"] == PR165_HEAD and x["conclusion"] == "success"
                            for x in old["exact_head_ci"]))
        self.assertFalse(old["comparison_to_last_product_code_head"]["product_code_changed"])

        restack = self.current["pr192_restaked"]
        self.assertEqual(restack["base_sha"], PR165_HEAD)
        self.assertEqual(restack["head_sha"], PR192_HEAD)
        self.assertEqual(restack["status"], "IMPLEMENTED_CI_PASS_NOT_EXECUTED")
        self.assertEqual([x["run_id"] for x in restack["exact_head_ci"]],
                         [45856211088, 45856211096, 45856211210])
        self.assertTrue(all(x["head_sha"] == PR192_HEAD and x["conclusion"] == "success"
                            for x in restack["exact_head_ci"]))
        self.assertEqual(len(restack["changed_files"]), 6)
        for field in ("local_pull_receipt", "windows_checker_receipt",
                      "local_gui_install_receipt", "product_e2e_pass"):
            self.assertIs(restack[field], False)

        self.assertEqual(self.current["status"], "HOLD")
        self.assertIs(self.current["e2e_pass"], False)
        self.assertIs(self.current["downstream_receipts"]["real_msix"], False)
        self.assertIs(self.current["downstream_receipts"]["github_backlog_receipt"], False)
        self.assertIs(self.current["downstream_receipts"]["local_pull_receipt"], False)
        self.assertIs(self.current["downstream_receipts"]["windows_checker_receipt"], False)
        self.assertIs(self.current["downstream_receipts"]["local_gui_install_receipt"], False)

    def test_focus_and_file_current_source_gates_remain_fail_closed(self):
        focus = self.current["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["expected_current_source_request_id"],
                         "app-focus-session-desk-fb6293839bc7")
        self.assertEqual(focus["approved_identity_source_sha"],
                         "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(focus["state"], "POST_IDENTITY_UPGRADE")
        self.assertEqual(focus["current_source_identity_binding_status"],
                         "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
        self.assertIsNone(focus["package_version"])
        self.assertEqual(focus["current_source_request"]["source_sha"],
                         focus["current_source_sha"])
        self.assertIs(focus["real_msix"], False)

        file_product = self.current["file_integrity_ledger"]
        self.assertEqual(file_product["current_source_sha"],
                         "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(file_product["current_source_request_id"],
                         "app-file-integrity-ledger-33d612be2774")
        self.assertIs(file_product["approved_identity_file_present_on_current_pr115_head"], False)
        self.assertEqual(file_product["human_visual_review_status"], "PASS")
        self.assertEqual(file_product["asset_mapping_qa_run_id"], 45747686529)
        self.assertIsNone(file_product["package_version"])
        self.assertIs(file_product["real_msix"], False)

    def test_prism_and_signal_use_current_projection_not_historical_identity_or_missing_artifact_claims(self):
        prism = self.current["prism_route_3d"]
        self.assertEqual(prism["current_source_sha"],
                         "b03ce7b16c3f75c04fe20fdda224c45849eeba0d")
        self.assertEqual(prism["historical_approved_identity_source_sha"],
                         "15fdcb52e46e35e6de8e87c55af99719c21e09b9")
        self.assertIs(prism["old_identity_reuse_allowed"], False)
        self.assertIsNone(prism["package_version"])
        self.assertEqual(prism["physical_windows_qa_sessions_completed"], 0)
        self.assertIs(prism["real_msix"], False)

        signal = self.current["signal_sprint"]
        self.assertEqual(signal["current_source_sha"],
                         "1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertEqual(signal["historical_request_id"],
                         "game-signal-sprint-c058cbf7fe38e02d929c67d047d717ff74bd522e")
        self.assertEqual(signal["current_build_artifact_id"], 14946655071)
        self.assertEqual(signal["current_gdk_readiness_artifact_id"], 14946675208)
        self.assertEqual(signal["current_identity_preview_status"],
                         "STALE_BUILD_PROVENANCE__REFRESH_REQUIRED")
        self.assertEqual(signal["gdk_sdk_status"], "HOLD_GDK_SDK_ROOT_NOT_FOUND")
        self.assertIs(signal["physical_windows_uia_pass"], False)
        self.assertIs(signal["real_msixvc"], False)

    def test_file_visual_and_asset_map_pass_does_not_clear_identity_or_version_gate(self):
        file_product = next(x for x in self.queue["priority"]
                            if x["product"] == "File Integrity Ledger")
        self.assertEqual(file_product["human_visual_review_status"], "PASS")
        self.assertEqual(file_product["human_visual_review_observed_at_utc"],
                         "2026-11-26T13:30:25Z")
        self.assertIs(file_product["human_visual_review_required"], False)
        self.assertIs(file_product["immutable_receipt_visual_review_required"], True)
        self.assertEqual(file_product["asset_mapping_qa_head_sha"],
                         "d245b5b0541a09af2de46d092e5525023456f843")
        self.assertEqual(file_product["asset_mapping_qa_run_id"], 45747686529)
        self.assertIsNone(file_product["package_version"])
        self.assertIs(file_product["real_msix"], False)

    def test_current_pr161_pr171_and_windows_automator_pins_are_directly_read_back(self):
        self.assertEqual(self.current["pr161"]["head_sha"],
                         "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(self.current["pr161"]["exact_head_ci"][0]["run_id"], 42712757936)
        self.assertEqual(self.current["pr171"]["head_sha"],
                         "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(self.current["pr171"]["exact_head_ci"][0]["run_id"], 44437197470)
        self.assertEqual(self.current["windows_automator_pin"]["commit_sha"],
                         "d3b8ed4ae7762a69d3fe2a90b64aa86ee938259b")
        self.assertEqual(self.current["windows_automator_pin"]["exact_head_ci"][0]["run_id"], 44319200630)

        eligibility = self.current["store_upload_test"]
        self.assertEqual(eligibility["eligible_fresh_unsold_products"], 0)
        self.assertIs(eligibility["dry_run_started"], False)
        self.assertIs(eligibility["store_submission_allowed"], False)
        self.assertIs(eligibility["certification_allowed"], False)
        self.assertIs(eligibility["publish_allowed"], False)

    def test_074400_overlay_remains_historical_and_161044_overlay_is_append_only(self):
        self.assertEqual(self.historical["observed_at_utc"], "2026-11-26T07:44:00Z")
        self.assertEqual(self.historical["pr165"]["head_sha"],
                         "74dee49585edbeee7eb66d58ff9fa2ea0b97e27f")
        self.assertEqual(self.historical["status"], "HOLD")
        self.assertEqual(self.current["pr165"]["head_sha"], PR165_HEAD)
        self.assertIn("ops/active_e2e_handoff_overlay_20261126_074400.json",
                      self.current["supersedes"])
        self.assertIs(self.current["e2e_pass"], False)

    def test_signal_queue_and_store_write_gates_stay_held(self):
        signal = next(x for x in self.queue["priority"] if x["product"] == "Signal Sprint")
        self.assertEqual(signal["current_build_artifact_id"], 14946655071)
        self.assertEqual(signal["current_gdk_readiness_artifact_id"], 14946675208)
        self.assertNotIn("no build artifact is configured", signal["next_action"].lower())
        self.assertIn("artifacts do exist", signal["next_action"].lower())
        self.assertIs(self.queue["store_submission_allowed"], False)
        self.assertIs(self.queue["certification_allowed"], False)
        self.assertIs(self.queue["publish_allowed"], False)


if __name__ == "__main__":
    unittest.main()
