"""Regression contract for the active E2E ledger; never re-run historical GAME jobs."""
import json
from pathlib import Path
import unittest

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
CURRENT = "da2068a4a3c17b2742949966944fa1a39f22c626"
HISTORICAL = "e9ae4669f6739d34cad63764767328a3c796a5f9"
PREVIOUS = "4d5c03c3aba4fccba786801e8e1b97e6fbbf3984"
HISTORICAL_PREVIOUS = "4bf0ebf436144bc5eda18c9429506a813e4d4384"
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
        self.assertEqual(active["provisioner_head_observation"]["historical_previous_observed_head"], HISTORICAL_PREVIOUS)
        self.assertEqual(active["provisioner_game_gdk_pr"]["historical_head_sha"], HISTORICAL)
        self.assertEqual(active["historical_local_commands_20261027"][1].count(HISTORICAL), 1)
        commands = "\n".join(active["local_commands"])
        self.assertNotIn(HISTORICAL, commands)
        self.assertIn("HOLD_PROVISIONER_HEAD_DRIFT", commands)
        self.assertIn("ARTIFACT_EXACT_BYTES_HOLD", commands)
        self.assertNotIn("--apply-request-id", commands)

    def test_new_provisioner_head_check_only_does_not_promote_cas(self):
        data = self.data
        active = data["active_product"]
        lineage = active["provisioner_game_gdk_pr"]["new_lineage_contract"]
        self.assertEqual(lineage["current_head"], CURRENT)
        self.assertEqual(lineage["workflow_run_id"], 41381739751)
        self.assertEqual(lineage["compare_to_prior_head"], "AHEAD_11_BEHIND_0_FROM_4D5C03C3")
        self.assertEqual(data["latest_provisioner_heads_observed"]["game"]["previous_observation_sha"], PREVIOUS)
        self.assertEqual(data["last_36_execution"]["game_provisioner_pr10_current"]["head_sha"], CURRENT)
        self.assertEqual(active["provisioner_package_safety"]["ci_run_id"], 41381739751)
        self.assertEqual(lineage["new_request_id"], "game-signal-sprint-c058cbf7fe38e02d929c67d047d717ff74bd522e-reissue-sprint-41361263698-41361263698")
        self.assertEqual(lineage["new_build_artifact_id"], 13105352227)
        for gate in ("reviewed_new_request_cas_contract", "physical_windows_check_only", "cas_applied", "gdk_msixvc_built", "package_version_approved"):
            self.assertFalse(lineage[gate])
        self.assertFalse(active["original_exe_artifact_audit"]["ready_for_cas"])
        self.assertFalse(active["cas_returned"])
        self.assertFalse(data["quality_gates"]["real_gdk_msixvc_pass"])
        self.assertFalse(data["e2e_pass"])
        commands = "\\n".join(active["local_commands"])
        self.assertIn(CURRENT, commands)
        self.assertNotIn(PREVIOUS, commands)
        self.assertIn("ARTIFACT_EXACT_BYTES_HOLD", commands)

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


    def test_current_identity_and_local_mode_are_not_confused_with_historical_wait(self):
        data = self.data
        active = data["active_product"]
        worker = active["local_identity_return_worker"]
        old_receipt = worker["local_check_only"]
        self.assertEqual(data["local_availability"]["mode"], "LOCAL_MODE")
        self.assertEqual(active["identity_registry_status"], "USER_IDENTITY_RECEIVED__REVIEWED_NON_SECRET_REFERENCE__NOT_LOCAL_VALIDATED")
        self.assertEqual(active["local_execution_result"]["historical_next_stage"], "OBTAIN_AUTHENTICATED_OFFICIAL_IDENTITY")
        self.assertEqual(active["local_execution_result"]["next_stage"], "HOLD_ARTIFACT_EXACT_BYTES__USER_IDENTITY_RECEIVED_NOT_LOCAL_VALIDATED")
        self.assertTrue(active["local_execution_result"]["historical_record"])
        self.assertEqual(worker["historical_status"], "CHECK_ONLY_WAITING_OFFICIAL_IDENTITY_LOCAL_WINDOWS_VERIFIED")
        self.assertEqual(old_receipt["historical_state"], "WAITING_OFFICIAL_IDENTITY")
        self.assertEqual(old_receipt["historical_hold_class"], "EXTERNAL_IDENTITY")
        self.assertEqual(old_receipt["hold_class"], "ARTIFACT_EXACT_BYTES")
        self.assertTrue(old_receipt["historical_receipt_only"])
        self.assertIn("CURRENT_HEAD_LOCAL_CHECK_ONLY_NOT_OBSERVED", worker["status"])
        self.assertIn("CURRENT_HEAD_LOCAL_CHECK_ONLY_NOT_OBSERVED", old_receipt["state"])
        self.assertNotIn("DEFERRED_LOCAL_GATE", " | ".join(active["blocked_by"]))
        self.assertIn("ARTIFACT_EXACT_BYTES_HOLD", active["blocked_by"][0])
        cloud = data["multi_product_identity_scheduler"]["rotation_queue"]["live_cloud_check"]
        self.assertEqual(cloud["historical_local_windows_qa"], "DEFERRED_LOCAL_GATE")
        self.assertEqual(cloud["local_windows_qa"], "LOCAL_MODE__PHYSICAL_RECEIPT_NOT_OBSERVED")
        self.assertFalse(data["quality_gates"]["local_source_code_sync_physical_pass"])
        self.assertFalse(data["quality_gates"]["local_source_code_sync_scheduler_pass"])
        self.assertFalse(active["original_exe_artifact_audit"]["ready_for_cas"])
        self.assertFalse(active["cas_returned"])
        self.assertFalse(data["e2e_pass"])


    def test_review_head_is_not_promoted_image_source_or_market_fit(self):
        data = self.data
        review = data["revision_review_reconciliation"]
        image = review["observations"]["offline-image-inventory-desk"]
        old = next(p for p in data["rotation_cohorts"]["app_jobs"]
                   if p["slug"] == "offline-image-inventory-desk")
        pipeline = next(p for p in data["post_identity_pipeline"]["products"]
                        if p["product"] == "Offline Image Inventory Desk")
        self.assertEqual(review["writer"], "36_WINDOWS_E2E_ONLY")
        self.assertEqual(image["current_review_head_sha"],
                         "9095cb77840fd86f0f73b5649ebbab829effd7da")
        self.assertNotEqual(image["current_review_head_sha"], old["source_sha"])
        self.assertEqual(image["immutable_pre_identity_source_sha"], old["source_sha"])
        self.assertEqual(image["immutable_pre_identity_request_id"], old["request_id"])
        self.assertEqual(image["separately_reported_prior_promoted_source_sha"],
                         "7cba0dac41401683d625eb63e82432c1fca4ce3d")
        self.assertFalse(image["current_review_revision_promoted"])
        self.assertIsNone(image["new_revision_source_sha"])
        self.assertIsNone(image["new_revision_request_id"])
        self.assertEqual(image["score"], 64)
        self.assertGreater(image["required_score"], image["score"])
        self.assertEqual(image["independent_buyers_completed"], 0)
        self.assertEqual(image["independent_buyers_required"], 5)
        self.assertFalse(image["why_pay_verified"])
        self.assertEqual(image["market_fit_gate"], "MARKET_FIT_HOLD")
        self.assertEqual(old["status"], "PRE_IDENTITY_READY")
        self.assertEqual(pipeline["identity_status"], "PRE_IDENTITY_READY__NO_APPROVED_FILE")
        self.assertIsNone(pipeline["identity_return_commit_sha"])
        self.assertEqual(pipeline["gates"]["real_msix_or_gdk"], "NOT_BUILT")
        self.assertEqual(data["last_36_execution"]["factory_image_current"]["observed_head"],
                         image["current_review_head_sha"])

    def test_jp_bookkeeping_review_head_does_not_create_source_or_tax_pass(self):
        data = self.data
        jp = data["revision_review_reconciliation"]["observations"]["jp-bookkeeping-desk"]
        intake = next(p for p in data["accounting_candidate_intake"]["products"]
                      if p["slug"] == "jp-bookkeeping-desk")
        self.assertEqual(jp["current_review_head_sha"],
                         "50d4a9c9e079b9e37f96944503e7f79aabd5c68b")
        self.assertEqual(intake["observed_factory_pr_head"], jp["current_review_head_sha"])
        self.assertEqual(jp["previous_review_head_sha"],
                         "32c5976971d1494e205156b8ad27c89598cb2f46")
        self.assertEqual(jp["historical_previous_review_head_sha"],
                         "24e8beade64177cafd0d545d84392304b53dfe51")
        self.assertIsNone(intake["source_sha"])
        self.assertIsNone(intake["request_id"])
        self.assertIsNone(jp["immutable_promoted_source_sha"])
        self.assertIsNone(jp["immutable_request_id"])
        self.assertEqual(jp["promotion_status"], "CANDIDATE_ONLY")
        self.assertEqual((jp["country"], jp["locale"], jp["currency"]),
                         ("Japan", "ja-JP", "JPY"))
        self.assertEqual(jp["pending_receipts_as_of_month_end"], None)
        self.assertEqual(jp["identity_status"], "NOT_YET_REQUIRED")
        self.assertEqual(jp["package_gate"], "HOLD")
        self.assertEqual(data["accounting_candidate_intake"]["real_msix"], "NOT_BUILT")

    def test_sentinel_new_source_does_not_reuse_historical_prism_cas(self):
        data = self.data
        sentinel = data["revision_review_reconciliation"]["observations"]["prism-route-3d-sentinel"]
        historical = next(p for p in data["post_identity_pipeline"]["products"]
                          if p["product"] == "Prism Route 3D")
        self.assertEqual(sentinel["current_review_head_sha"],
                         "6b2afaf2adeb5ee4c7cc24d76bcfa1c24db72e1a")
        self.assertEqual(sentinel["immutable_sentinel_source_sha"],
                         "e432d94ed0db22878f61f1a8af140d7d7de2288f")
        self.assertEqual(sentinel["immutable_sentinel_request_id"],
                         "3d-prism-route-3d-e432d94ed0db")
        self.assertNotEqual(sentinel["immutable_sentinel_source_sha"],
                            historical["source_sha"])
        self.assertNotEqual(sentinel["immutable_sentinel_request_id"],
                            historical["request_id"])
        self.assertEqual(historical["identity_return_commit_sha"],
                         "11417b75636ee18816028ffd5221884c4c9a9836")
        self.assertEqual(sentinel["historical_identity_return_commit_sha"],
                         historical["identity_return_commit_sha"])
        self.assertEqual(sentinel["historical_store_id"], historical["identity_store_id"])
        self.assertEqual(sentinel["new_sentinel_identity_cas_status"],
                         "HOLD_NEW_REVISION_CAS_AUTHENTICATION_REQUIRED")
        self.assertFalse(sentinel["new_sentinel_cas_applied"])
        self.assertFalse(sentinel["approved_package_version"])
        self.assertFalse(sentinel["qa_unsigned_fixture_is_product_msix"])
        self.assertEqual(sentinel["real_signed_msix"], "NOT_BUILT")
        self.assertEqual(historical["state"], "POST_IDENTITY_READY")
        self.assertEqual(data["latest_provisioner_heads_observed"]["three_d_sentinel_review"]["head_sha"],
                         sentinel["current_review_head_sha"])

    def test_game_original_bytes_and_physical_local_gates_remain_hold(self):
        data = self.data
        game = data["revision_review_reconciliation"]["observations"]["signal-sprint"]
        active = data["active_product"]
        gates = data["revision_review_reconciliation"]["cross_lane_gates"]
        self.assertEqual(game["current_review_head_sha"], CURRENT)
        self.assertEqual(game["immutable_source_sha"], active["source_sha"])
        self.assertEqual(game["immutable_request_id"], active["request_id"])
        self.assertEqual(game["original_zip_status"], "EXPIRED_404__NOT_RECOVERED")
        self.assertFalse(game["cas_applied"])
        self.assertFalse(active["original_exe_artifact_audit"]["authority_reconciled"])
        self.assertEqual(gates["app_batch_cloud_discovered"], 4)
        self.assertEqual(gates["app_github_identity_returned"], 2)
        self.assertEqual(gates["app_pre_identity_pending"], 2)
        self.assertEqual(gates["app_local_processed"], 0)
        for key in ("scheduled_trigger_proven", "physical_local_code_sync_receipt_verified",
                    "local_task_scheduler_last_result_verified", "real_msix_pass",
                    "github_real_product_backlog_pass", "local_pull_pass",
                    "checker_pass", "gui_install_pass", "e2e_pass"):
            self.assertFalse(gates[key], key)
        self.assertFalse(data["quality_gates"]["local_source_code_sync_physical_pass"])
        self.assertFalse(data["quality_gates"]["local_source_code_sync_scheduler_pass"])
        self.assertFalse(data["e2e_pass"])


if __name__ == "__main__":
    unittest.main()
