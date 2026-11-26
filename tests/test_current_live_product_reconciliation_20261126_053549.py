import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
KEY = "pr165_live_head_observation_20261126_053549"
HEAD = "74dee49585edbeee7eb66d58ff9fa2ea0b97e27f"
CI_RUNS = [45758828777, 45758828791, 45758828792]


class CurrentLiveProductReconciliation20261126_053549Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads((ROOT / "ops/active_e2e_handoff.json").read_text(encoding="utf-8"))
        cls.queue = json.loads((ROOT / "ops/completion_rush_queue_20261116.json").read_text(encoding="utf-8"))
        cls.recon = json.loads((ROOT / "ops/focus_file_transport_reconciliation_20261126.json").read_text(encoding="utf-8"))
        cls.overlay = json.loads((ROOT / "ops/active_e2e_handoff_overlay_20261126_053549.json").read_text(encoding="utf-8"))

    def test_latest_head_pointer_matches_exact_head_ci(self):
        for doc in (self.ledger, self.queue, self.recon):
            self.assertEqual(doc["latest_observation_key"], KEY) if "latest_observation_key" in doc else None
        self.assertEqual(self.ledger["pr165_latest_live_observation_key"], KEY)
        self.assertEqual(self.ledger["pr165_latest_live_head_sha"], HEAD)
        self.assertEqual(self.ledger["pr165_latest_live_head_parent_sha"], "68fdccd2edf55538b2898c3c67b39f678004a6f9")
        self.assertEqual(self.ledger["pr165_latest_live_head_ci_status"], "PASS_EXACT_HEAD_CI")
        observation = self.ledger[KEY]
        self.assertEqual(observation["head_sha"], HEAD)
        self.assertEqual([x["run_id"] for x in observation["exact_head_ci"]], CI_RUNS)
        self.assertTrue(all(x["head_sha"] == HEAD and x["conclusion"] == "success" for x in observation["exact_head_ci"]))
        self.assertEqual(observation["comparison_to_last_verified_code_head"]["ahead_by"], 34)
        self.assertFalse(observation["product_code_changed"])
        self.assertTrue(observation["transport_contract_code_changed"])
        self.assertEqual(observation["parent_ci_status"], "PARTIAL_FAIL_TEST_ONLY_HISTORICAL_POINTER_ASSERTIONS")
        self.assertFalse(observation["e2e_pass"])
        self.assertEqual(self.queue["latest_observation_key"], KEY)
        self.assertEqual(self.queue["pr165_latest_live_head_sha"], HEAD)
        self.assertEqual(self.queue["pr165_latest_live_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(self.recon["latest_observation_key"], KEY)
        self.assertEqual(self.recon["pr165_latest_live_head_sha"], HEAD)
        self.assertEqual(self.recon["pr165_latest_live_head_ci_status"], "PASS_EXACT_HEAD_CI")

    def test_focus_and_file_integrity_remain_blocked_before_real_msix(self):
        focus = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["approved_identity_file_binding_status"], "HISTORICAL_SOURCE_ONLY")
        self.assertNotEqual(focus["approved_identity_source_sha"], focus["current_source_sha"])
        self.assertEqual(focus["current_source_request_status"], "DRY_RUN")
        self.assertEqual(focus["official_identity_status"], "NOT_COLLECTED_FOR_CURRENT_SOURCE")
        self.assertIsNone(focus["package_version"])
        self.assertEqual(focus["msix_export_status"], "FAILED_MISSING_VERIFIED_VERSION")
        self.assertFalse(focus["real_msix"])

        file = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(file["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertFalse(file["approved_identity_file_present_on_current_source"])
        self.assertEqual(file["approved_identity_file_readback"], "NOT_FOUND__HTTP_404")
        self.assertEqual(file["current_source_request_status"], "DRY_RUN")
        self.assertEqual(file["official_identity_status"], "UNVERIFIED")
        self.assertIsNone(file["package_version"])
        self.assertEqual(file["msix_export_status"], "SKIPPED_NO_ARTIFACT")
        self.assertFalse(file["real_msix"])

    def test_no_downstream_receipts_or_store_promotion(self):
        for field in ("real_msix", "github_backlog_receipt", "local_pull_receipt", "local_checker_receipt", "local_gui_install_receipt"):
            self.assertIs(self.overlay["pr165"][field] if field in self.overlay["pr165"] else False, False)
        self.assertEqual(self.overlay["first_unconnected_interval"]["status"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        self.assertEqual(self.overlay["store_upload_test"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.overlay["store_upload_test"]["dry_run_started"])
        self.assertFalse(self.overlay["store_upload_test"]["live_partner_center_write_allowed"])
        for field in ("store_submission_allowed", "certification_allowed", "publish_allowed", "merge_allowed", "force_push_allowed", "identity_write_allowed", "version_inference_allowed"):
            self.assertFalse(self.overlay["safety"][field])
        self.assertFalse(self.ledger["e2e_pass"])
        self.assertEqual(self.ledger["e2e_status"], "HOLD")

    def test_pr184_is_not_reused_as_a_stale_base(self):
        stale = self.overlay["pr184_stale_branch_assessment"]
        self.assertEqual(stale["comparison_to_current_pr165_head"]["status"], "diverged")
        self.assertEqual(stale["comparison_to_current_pr165_head"]["ahead_by"], 17)
        self.assertEqual(stale["comparison_to_current_pr165_head"]["behind_by"], 51)
        self.assertEqual(stale["decision"], "DO_NOT_RESTACK_WHOLE_PR__SELECTIVELY_REAPPLY_LOCAL_PULL_CUSTODY")


if __name__ == "__main__":
    unittest.main()
