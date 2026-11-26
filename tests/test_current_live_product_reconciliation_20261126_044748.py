import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
KEY = "pr165_live_head_observation_20261126_044748"
HEAD = "ea55f1a496c68bec7b07db1e365f0b23301d5ae1"


class CurrentLiveProductReconciliation20261126_044748Tests(unittest.TestCase):
    def test_latest_pr165_head_is_reconciled_without_product_e2e_promotion(self):
        ledger = json.loads((ROOT / "ops/active_e2e_handoff.json").read_text(encoding="utf-8"))
        queue = json.loads((ROOT / "ops/completion_rush_queue_20261116.json").read_text(encoding="utf-8"))
        overlay = json.loads((ROOT / "ops/active_e2e_handoff_overlay_20261126_044748.json").read_text(encoding="utf-8"))
        observation = ledger[KEY]

        self.assertEqual(ledger["pr165_latest_live_observation_key"], "pr165_live_head_observation_20261126_053549")
        self.assertEqual(ledger["pr165_latest_live_head_sha"], "74dee49585edbeee7eb66d58ff9fa2ea0b97e27f")
        self.assertEqual(ledger["pr165_latest_live_head_parent_sha"], "68fdccd2edf55538b2898c3c67b39f678004a6f9")
        self.assertEqual(ledger["pr165_latest_live_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in observation["exact_head_ci"]], [45757413753, 45757413754, 45757413777])
        self.assertTrue(all(x["head_sha"] == HEAD and x["conclusion"] == "success" for x in observation["exact_head_ci"]))
        self.assertEqual(observation["push_offline_qa"]["run_id"], 45757409017)
        self.assertEqual(observation["comparison_to_last_verified_code_head"]["ahead_by"], 29)
        self.assertFalse(observation["product_code_changed"])
        self.assertTrue(observation["transport_contract_code_changed"])
        self.assertEqual(observation["transport_gate_change"]["status"], "IMPLEMENTED_FAIL_CLOSED__EXACT_HEAD_CI_PASS")
        self.assertEqual(observation["transport_gate_change"]["missing_receipt_result"], "HOLD_BEFORE_LOCAL_QA_QUEUE")

        self.assertEqual(ledger["e2e_status"], "HOLD")
        self.assertIs(ledger["e2e_pass"], False)
        self.assertIs(observation["e2e_pass"], False)
        self.assertIs(observation["real_msix"], False)
        self.assertIs(observation["github_backlog_receipt"], False)
        self.assertIs(observation["local_pull_receipt"], False)
        self.assertIs(observation["local_checker_receipt"], False)
        self.assertIs(observation["local_gui_install_receipt"], False)
        self.assertEqual(ledger["local_code_sync_receipt_status_20261126_latest"], "NOT_OBSERVED__CLOUD_PASS_ONLY")

        focus = observation["product_blockers"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["approved_identity_file_binding_status"], "HISTORICAL_SOURCE_ONLY")
        self.assertEqual(focus["current_source_identity_binding_status"], "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
        self.assertIsNone(focus["package_version"])
        self.assertEqual(focus["current_source_exe_custody_status"], "VERIFIED_UNSIGNED_PRE_IDENTITY_EXE_ONLY")
        self.assertIs(focus["real_msix"], False)
        self.assertEqual(focus["store_assets_msix_embedding_status"], "NOT_VERIFIED")

        file_product = observation["product_blockers"]["file_integrity_ledger"]
        self.assertEqual(file_product["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertIs(file_product["approved_identity_file_present_on_current_source"], False)
        self.assertIsNone(file_product["package_version"])
        self.assertEqual(file_product["request_status"], "DRY_RUN")
        self.assertIs(file_product["real_msix"], False)

        self.assertEqual(observation["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertIs(observation["store_upload_test_eligibility"]["dry_run_started"], False)
        self.assertIs(ledger["store_submission_allowed"], False)
        self.assertIs(ledger["certification_allowed"], False)
        self.assertIs(ledger["publish_allowed"], False)

        self.assertEqual(queue["latest_observation_key"], "pr165_live_head_observation_20261126_053549")
        self.assertEqual(queue["pr165_latest_live_head_sha"], "74dee49585edbeee7eb66d58ff9fa2ea0b97e27f")
        self.assertIs(queue["e2e_pass"], False)
        self.assertEqual(overlay["pr165"]["head_sha"], HEAD)
        self.assertEqual(overlay["status"], "HOLD")
        self.assertIs(overlay["e2e_pass"], False)
        self.assertEqual(overlay["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(overlay["pr171"]["head_sha"], "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(overlay["store_upload_test"]["eligible_fresh_unsold_products"], 0)


if __name__ == "__main__":
    unittest.main()
