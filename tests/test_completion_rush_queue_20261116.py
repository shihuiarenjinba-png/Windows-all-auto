import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "ops" / "completion_rush_queue_20261116.json"


class CompletionRushQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_new_products_are_disabled_during_completion_rush(self):
        self.assertFalse(self.data["new_product_generation_allowed"])

    def test_focus_and_file_integrity_remain_delivery_only_and_version_held(self):
        items = {x["product"]: x for x in self.data["priority"]}
        for name in ("Focus Session Desk", "File Integrity Ledger"):
            row = items[name]
            self.assertEqual(row["state"], "POST_IDENTITY_UPGRADE")
            self.assertEqual(row["hold_class"], "DELIVERY_HOLD")
            self.assertFalse(row["functional_hold"])
            self.assertTrue(row["product_frozen_for_package"])
            self.assertEqual(row["identity_return"], "VERIFIED")
            self.assertEqual(row["identity_return_scope"], "HISTORICAL_SOURCE_ONLY")
            self.assertIsNone(row["package_version"])
            self.assertEqual(row["package_version_status"], "AUTHORITATIVE_VALUE_REQUIRED")
            self.assertFalse(row["real_msix"])

    def test_focus_identity_is_not_reused_for_current_source(self):
        row = next(x for x in self.data["priority"] if x["product"] == "Focus Session Desk")
        self.assertEqual(row["source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(row["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(row["current_source_identity_binding_status"], "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
        self.assertEqual(row["current_source_request_status"], "GENERATED__DRY_RUN_ARTIFACT_VERIFIED__IDENTITY_READBACK_PENDING")
        self.assertEqual(row["package_version_status"], "AUTHORITATIVE_VALUE_REQUIRED")
        self.assertEqual(row["store_assets_evidence"]["native_exe_gui"]["run_id"], 45234786152)
        self.assertEqual(row["store_assets_evidence"]["native_exe_gui"]["visual_review_status"],
                         "PASS_36_VISUAL_REVIEW__100_PERCENT_AND_COLD_RESTART_PERSISTENCE")
        self.assertEqual(row["product_quality_assessment"]["score"]["total"], 54)
        self.assertEqual(row["product_quality_assessment"]["decision"], "DO_NOT_SELL__BELOW_80")

    def test_file_integrity_pr115_is_integrated_candidate_not_package_ready(self):
        row = next(x for x in self.data["priority"] if x["product"] == "File Integrity Ledger")
        self.assertEqual(row["current_factory_pr"], 115)
        self.assertEqual(row["current_factory_head"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(row["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(row["source_selection_status"],
                         "INTEGRATED_CANDIDATE_PR115__AWAITING_HUMAN_VISUAL_REVIEW_AND_IDENTITY_REVALIDATION")
        self.assertEqual(row["current_factory_compare"], {
            "status": "ahead", "ahead_by": 2, "behind_by": 0, "total_commits": 2, "changed_files": 8
        })
        self.assertEqual(row["current_gui_followup"]["run_id"], 45422895435)
        self.assertEqual(row["current_gui_followup"]["artifact_id"], 14934752145)
        self.assertEqual(row["current_gui_followup"]["artifact_sha256"],
                         "6faa6db6d0e05b6baa71347c31b6f4d871fedcf35e28b787a7fbdb99816ab04c")
        self.assertEqual(row["current_gui_followup"]["exe_sha256"],
                         "425e8f03397fc00a7b1442d58cc99d460fea53238e83c5b96500ac450bab85c6")
        self.assertTrue(row["current_gui_followup"]["artifact_bytes_independently_downloaded_and_rehashed"])
        self.assertTrue(row["current_gui_followup"]["exe_sha256_independently_rehashed"])
        self.assertEqual(row["current_gui_followup"]["receipt_statuses"], ["UNCHANGED", "MODIFIED", "MISSING"])
        self.assertTrue(row["current_gui_followup"]["visual_review_required"])
        self.assertEqual(row["current_gui_followup_visual_review_status"],
                         "36_SCREENSHOT_INSPECTION_PASS__HUMAN_OWNER_REVIEW_REQUIRED")
        self.assertEqual(row["current_source_request_id"], "app-file-integrity-ledger-33d612be2774")
        self.assertEqual(row["current_source_request"]["status"], "DRY_RUN")
        self.assertEqual(row["current_source_request"]["source_sha"], row["current_source_sha"])
        self.assertEqual(row["current_source_request"]["route"], "MSIX_OR_PWA_APP")
        self.assertFalse(row["approved_identity_file_present_on_current_pr115_head"])
        self.assertEqual(row["approved_identity_file_current_pr115_head_readback"], "NOT_FOUND")
        self.assertEqual(row["source_lineage_observation_20261125"]["historical_approved_source_sha"],
                         "d1108d12f7d1697af30400f97c7db39cba5e6791")
        self.assertEqual(row["source_lineage_observation_20261125"]["msix_export"]["status"], "SKIPPED_NO_ARTIFACT")
        self.assertEqual(row["msix_export"]["run_id"], 45422811552)
        self.assertIsNone(row["package_version"])
        self.assertFalse(row["real_msix"])
        self.assertFalse(row["github_backlog_receipt"])
        self.assertFalse(row["local_checker_receipt"])
        self.assertTrue(row["store_assets_git_blob_sha_verified"])

    def test_no_version_is_invented(self):
        for row in self.data["priority"]:
            if "package_version" in row and not row.get("real_msix"):
                self.assertIsNone(row["package_version"])

    def test_priority_is_unique_and_ordered(self):
        ranks = [row["rank"] for row in self.data["priority"]]
        products = [row["product"] for row in self.data["priority"]]
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))
        self.assertEqual(len(products), len(set(products)))

    def test_latest_transport_and_store_gate_stay_held(self):
        latest = self.data["latest_transport_reconciliation"]
        self.assertEqual(latest["central_head"], "c68adc79ecf8a0c6ad4b538146648391b1b4eddb")
        self.assertEqual(latest["central_tested_head_sha"], "c68adc79ecf8a0c6ad4b538146648391b1b4eddb")
        self.assertEqual(latest["previous_central_head_sha"], "20d64d0a43581372477f2990133b914390ca3559")
        self.assertEqual(latest["previous_tested_head_sha"], "1d02a0307c6ce456b25c3d4fafa40362078f7c0a")
        self.assertEqual([x["run_id"] for x in latest["exact_head_ci"]], [45731501639, 45731501700, 45731501669])
        self.assertEqual(latest["ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(latest["status"], "HOLD")
        self.assertEqual(latest["pr165_current_head_parent_ci_status"], "PARTIAL_FAIL_RECONCILIATION_TEST_KEYERROR")
        self.assertEqual([x["run_id"] for x in latest["pr165_current_head_parent_ci"]], [45731429031, 45731429039, 45731429057])
        self.assertEqual([x["run_id"] for x in latest["previous_exact_head_ci"]], [45731429031, 45731429039, 45731429057])
        self.assertEqual([x["run_id"] for x in latest["previous_tested_exact_head_ci"]], [45727872167, 45727872209, 45727872206])
        observation = self.data["pr165_live_head_observation_20261126_latest"]
        self.assertEqual(observation["head_sha"], "c68adc79ecf8a0c6ad4b538146648391b1b4eddb")
        self.assertEqual(observation["parent_sha"], "20d64d0a43581372477f2990133b914390ca3559")
        self.assertEqual(observation["status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(observation["last_verified_head_sha"], "c68adc79ecf8a0c6ad4b538146648391b1b4eddb")
        self.assertEqual(self.data["pr165_current_head_sha"], "c68adc79ecf8a0c6ad4b538146648391b1b4eddb")
        self.assertEqual(self.data["pr165_current_head_parent_sha"], "20d64d0a43581372477f2990133b914390ca3559")
        self.assertEqual(self.data["pr165_current_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in self.data["pr165_current_head_ci"]], [45731501639, 45731501700, 45731501669])
        self.assertEqual(self.data["pr165_current_branch_head_sha"], "7e5cb744bb5c3cffbf17695c670ed0813f67f720")
        self.assertEqual(self.data["pr165_current_branch_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(self.data["pr165_current_branch_head_parent_sha"], "b1ebc578c39084a032502d153bfa159480fc7116")
        self.assertEqual(self.data["pr165_current_branch_head_parent_ci_status"], "PARTIAL_FAIL_TEST_ONLY_KEYERROR_EXACT_HEAD_WORKFLOWS_FIELD")
        live = self.data["pr165_live_branch_head_observation_20261126_012000"]
        self.assertEqual(live["head_sha"], "7e5cb744bb5c3cffbf17695c670ed0813f67f720")
        self.assertEqual(live["comparison_to_last_tested_code_head"]["ahead_by"], 12)
        self.assertFalse(live["product_code_changed"])
        self.assertFalse(live["e2e_pass"])
        self.assertEqual(self.data["pr165_current_branch_head_ci_run_ids"], [45734980032, 45734979170, 45734979161])
        self.assertEqual(self.data["pr165_current_head_parent_ci_status"], "PARTIAL_FAIL_RECONCILIATION_TEST_KEYERROR")
        self.assertEqual([x["run_id"] for x in self.data["pr165_current_head_parent_ci"]], [45731429031, 45731429039, 45731429057])
        self.assertFalse(observation["e2e_pass"])
        self.assertEqual(latest["status"], "HOLD")
        self.assertFalse(latest["e2e_pass"])
        self.assertFalse(latest["real_msix"])
        self.assertEqual(self.data["store_upload_test_eligibility_live_20261125"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.data["store_upload_test_eligibility_live_20261125"]["dry_run_started"])
        self.assertFalse(self.data["store_submission_allowed"])
        self.assertFalse(self.data["certification_allowed"])
        self.assertFalse(self.data["publish_allowed"])



if __name__ == "__main__":
    unittest.main()
