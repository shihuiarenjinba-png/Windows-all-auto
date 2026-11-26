import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
KEY = "pr165_live_head_observation_20261126_074400"
HEAD = "74dee49585edbeee7eb66d58ff9fa2ea0b97e27f"
PR187_HEAD = "5ad7b5b9522ef4640481b5c71af301405b1f255b"


class CurrentLiveProductReconciliation20261126_074400Tests(unittest.TestCase):
    def test_pr165_and_pr187_exact_heads_are_recorded_without_product_e2e_promotion(self):
        ledger = json.loads((ROOT / "ops/active_e2e_handoff.json").read_text(encoding="utf-8"))
        queue = json.loads((ROOT / "ops/completion_rush_queue_20261116.json").read_text(encoding="utf-8"))
        overlay = json.loads((ROOT / "ops/active_e2e_handoff_overlay_20261126_074400.json").read_text(encoding="utf-8"))
        observation = ledger[KEY]

        self.assertEqual(ledger["pr165_latest_live_observation_key"], KEY)
        self.assertEqual(ledger["pr165_latest_live_head_sha"], HEAD)
        self.assertEqual(ledger["pr165_latest_live_head_parent_sha"], "68fdccd2edf55538b2898c3c67b39f678004a6f9")
        self.assertEqual(ledger["pr165_latest_live_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in observation["exact_head_ci"]], [45758828777, 45758828791, 45758828792])
        self.assertTrue(all(x["head_sha"] == HEAD and x["conclusion"] == "success" for x in observation["exact_head_ci"]))
        self.assertEqual(observation["comparison_to_last_verified_code_head"]["ahead_by"], 34)
        self.assertFalse(observation["product_code_changed"])
        self.assertTrue(observation["transport_contract_code_changed"])

        self.assertEqual(ledger["e2e_status"], "HOLD")
        self.assertIs(ledger["e2e_pass"], False)
        for field in ("real_msix", "github_backlog_receipt", "local_pull_receipt", "local_checker_receipt", "local_gui_install_receipt"):
            self.assertIs(observation[field], False)
        self.assertEqual(ledger["local_code_sync_receipt_status_20261126_latest"], "NOT_OBSERVED__CLOUD_PASS_ONLY")

        pr187 = observation["pr187_local_pull_transport"]
        self.assertEqual(pr187["base_sha"], HEAD)
        self.assertEqual(pr187["head_sha"], PR187_HEAD)
        self.assertEqual(pr187["status"], "IMPLEMENTED_CI_PASS_NOT_EXECUTED")
        self.assertEqual([x["run_id"] for x in pr187["exact_head_ci"]], [45768375683, 45768375692, 45768375748])
        self.assertTrue(all(x["head_sha"] == PR187_HEAD and x["conclusion"] == "success" for x in pr187["exact_head_ci"]))
        self.assertIs(pr187["local_pull_receipt"], False)
        self.assertIs(pr187["windows_checker_receipt"], False)
        self.assertIs(pr187["local_gui_install_receipt"], False)
        self.assertIs(pr187["product_e2e_pass"], False)

        focus = observation["product_blockers"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["approved_identity_file_binding_status"], "HISTORICAL_SOURCE_ONLY")
        self.assertEqual(focus["current_source_request_id"], "app-focus-session-desk-fb6293839bc7")
        self.assertEqual(focus["request_status"], "DRY_RUN")
        self.assertIsNone(focus["package_version"])
        self.assertEqual(focus["current_source_exe_custody_status"], "VERIFIED_UNSIGNED_PRE_IDENTITY_EXE_ONLY")
        self.assertIs(focus["real_msix"], False)

        file_product = observation["product_blockers"]["file_integrity_ledger"]
        self.assertEqual(file_product["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertIs(file_product["approved_identity_file_present_on_current_source"], False)
        self.assertEqual(file_product["request_status"], "DRY_RUN")
        self.assertEqual(file_product["official_identity_status"], "UNVERIFIED")
        self.assertIsNone(file_product["package_version"])
        self.assertIs(file_product["real_msix"], False)

        self.assertEqual(observation["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertIs(observation["store_upload_test_eligibility"]["dry_run_started"], False)
        self.assertIs(ledger["store_submission_allowed"], False)
        self.assertIs(ledger["certification_allowed"], False)
        self.assertIs(ledger["publish_allowed"], False)

        self.assertEqual(queue["latest_observation_key"], KEY)
        self.assertEqual(queue["pr165_latest_live_head_sha"], HEAD)
        self.assertIs(queue["e2e_pass"], False)
        self.assertEqual(overlay["pr165"]["head_sha"], HEAD)
        self.assertEqual(overlay["pr187"]["head_sha"], PR187_HEAD)
        self.assertEqual(overlay["status"], "HOLD")
        self.assertIs(overlay["e2e_pass"], False)
        self.assertFalse(overlay["safety"]["store_submission_allowed"])
        self.assertFalse(overlay["safety"]["certification_allowed"])
        self.assertFalse(overlay["safety"]["publish_allowed"])


if __name__ == "__main__":
    unittest.main()
