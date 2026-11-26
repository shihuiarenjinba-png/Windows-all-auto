import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CurrentLiveProductReconciliation20261126Tests(unittest.TestCase):
    def test_latest_pr165_head_is_reconciled_without_product_e2e_promotion(self):
        ledger = json.loads((ROOT / "ops/active_e2e_handoff.json").read_text(encoding="utf-8"))
        overlay = json.loads((ROOT / "ops/active_e2e_handoff_overlay_20261126_040324.json").read_text(encoding="utf-8"))
        key = "pr165_live_head_observation_20261126_040324"
        observation = ledger[key]

        self.assertEqual(ledger["pr165_latest_live_observation_key"], "pr165_live_head_observation_20261126_074400")
        self.assertEqual(ledger["pr165_latest_live_head_sha"], "74dee49585edbeee7eb66d58ff9fa2ea0b97e27f")
        self.assertEqual(ledger["pr165_latest_live_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(observation["head_sha"], "f2a8d5b3f96b395ff248f42125daa26295f94c78")
        self.assertEqual(observation["parent_sha"], "13f8ed4f44e7c7e1ffaa3e64f9de73ba931e64d1")
        self.assertEqual(observation["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertTrue(all(item["head_sha"] == "f2a8d5b3f96b395ff248f42125daa26295f94c78" and item["conclusion"] == "success" for item in observation["exact_head_ci"]))
        self.assertFalse(observation["product_code_changed"])
        self.assertEqual(ledger["e2e_status"], "HOLD")
        self.assertIs(ledger["e2e_pass"], False)
        self.assertEqual(observation["product_e2e_status"], "HOLD")
        self.assertIs(observation["e2e_pass"], False)
        self.assertIs(observation["real_msix"], False)
        self.assertIs(observation["github_backlog_receipt"], False)
        self.assertIs(observation["local_pull_receipt"], False)
        self.assertIs(observation["local_checker_receipt"], False)
        self.assertIs(observation["local_gui_install_receipt"], False)

        focus = observation["product_blockers"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["current_source_exe_artifact_id"], 15083856249)
        self.assertTrue(focus["current_source_exe_bytes_present_in_artifact"])
        self.assertEqual(focus["current_source_exe_custody_status"], "VERIFIED_UNSIGNED_PRE_IDENTITY_EXE_ONLY")
        self.assertEqual(focus["current_source_identity_binding_status"], "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
        self.assertIsNone(focus["package_version"])
        self.assertIs(focus["real_msix"], False)
        self.assertTrue(focus["progress_visual_review_required"])

        file_product = observation["product_blockers"]["file_integrity_ledger"]
        self.assertEqual(file_product["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertIs(file_product["approved_identity_file_present_on_current_source"], False)
        self.assertIsNone(file_product["package_version"])
        self.assertIs(file_product["real_msix"], False)
        self.assertTrue(file_product["human_visual_review_required"])

        self.assertEqual(observation["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertIs(observation["store_upload_test_eligibility"]["dry_run_started"], False)
        self.assertIs(observation["safety"]["store_submission_allowed"], False)
        self.assertIs(observation["safety"]["certification_allowed"], False)
        self.assertIs(observation["safety"]["publish_allowed"], False)

        self.assertEqual(overlay["pr165"]["head_sha"], "f2a8d5b3f96b395ff248f42125daa26295f94c78")
        self.assertEqual(overlay["pr165"]["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(overlay["status"], "HOLD")
        self.assertIs(overlay["e2e_pass"], False)

    def test_completion_queue_records_focus_exe_custody_without_promoting_msix(self):
        queue = json.loads((ROOT / "ops/completion_rush_queue_20261116.json").read_text(encoding="utf-8"))
        focus = next(item for item in queue["priority"] if item["product"] == "Focus Session Desk")
        self.assertEqual(queue["latest_observation_key"], "pr165_live_head_observation_20261126_074400")
        self.assertEqual(focus["current_source_exe_artifact_id"], 15083856249)
        self.assertTrue(focus["current_source_exe_bytes_present_in_artifact"])
        self.assertEqual(focus["current_source_exe_custody_status"], "VERIFIED_UNSIGNED_PRE_IDENTITY_EXE_ONLY")
        self.assertIsNone(focus["package_version"])
        self.assertIs(focus["real_msix"], False)
        self.assertIs(queue["e2e_pass"], False)


if __name__ == "__main__":
    unittest.main()
