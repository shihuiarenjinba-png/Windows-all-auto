"""Current-source Identity, APP cohort and local sync reconciliation for 2026-11-27 12:39 JST."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261127_1239.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261127_1239.json"


class CurrentIdentityCohortReconciliation20261127Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_pr205_and_pr165_exact_heads_are_separate_from_product_e2e(self):
        p205 = self.overlay["observation_basis"]["pr205"]
        self.assertEqual(p205["head_sha_before_append"],
                         "49d3550b87250eaddf89f1ba9ae310a654e1abff")
        self.assertEqual([x["run_id"] for x in p205["exact_head_ci"]],
                         [45924695924, 45924695889, 45924695893])
        self.assertTrue(all(x["head_sha"] == p205["head_sha_before_append"]
                            and x["conclusion"] == "success"
                            for x in p205["exact_head_ci"]))
        self.assertEqual(p205["same_head_push_offline_qa"]["run_id"], 45924689404)
        self.assertEqual(p205["same_head_push_offline_qa"]["head_sha"],
                         p205["head_sha_before_append"])
        p165 = self.overlay["observation_basis"]["pr165"]
        self.assertEqual(p165["head_sha"], "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertTrue(all(x["conclusion"] == "success" for x in p165["exact_head_ci"]))
        self.assertEqual(self.overlay["status"], "HOLD")
        self.assertIs(self.overlay["e2e_pass"], False)

    def test_focus_is_pre_identity_fix_until_current_source_request_exists(self):
        f = self.overlay["product_identity_state_classification"]["focus_session_desk"]
        self.assertEqual(f["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(f["identity_state"], "PRE_IDENTITY_FIX_REQUIRED")
        self.assertEqual(f["non_identity_pre_identity_blocker_count"], 1)
        self.assertEqual(f["current_source_request"]["expected_request_id"],
                         "app-focus-session-desk-b6b69464a9c7")
        self.assertFalse(f["current_source_request"]["observed"])
        self.assertEqual(f["historical_identity"]["source_sha"],
                         "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertFalse(f["historical_identity"]["current_source_reuse_allowed"])
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])

    def test_file_waiting_user_identity_has_zero_non_identity_pre_identity_blockers(self):
        f = self.overlay["product_identity_state_classification"]["file_integrity_ledger"]
        self.assertEqual(f["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(f["identity_state"], "WAITING_USER_IDENTITY")
        self.assertEqual(f["non_identity_pre_identity_blocker_count"], 0)
        request = f["current_source_request"]
        self.assertEqual(request["request_id"], "app-file-integrity-ledger-33d612be2774")
        self.assertEqual(request["source_sha"], f["current_source_sha"])
        self.assertEqual(request["status"], "DRY_RUN")
        self.assertTrue(request["artifact_downloaded_and_rehashed"])
        build = f["local_windows_build_classification"]
        self.assertEqual(build["classification"],
                         "POST_IDENTITY_DELIVERY_STEP_NOT_PRE_IDENTITY_BLOCKER")
        self.assertEqual(build["non_identity_pre_identity_blocker_count"], 0)
        self.assertFalse(f["historical_identity"]["current_source_reuse_allowed"])
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])
        self.assertFalse(f["github_backlog_receipt"])
        self.assertFalse(f["local_pull_receipt"])
        self.assertFalse(f["windows_checker_receipt"])
        self.assertFalse(f["local_gui_install_receipt"])
        self.assertFalse(f["product_e2e_pass"])

    def test_prism_4c_is_tooling_and_current_source_waits_for_identity(self):
        p = self.overlay["product_identity_state_classification"]["prism_route_3d"]
        self.assertEqual(p["current_source_sha"], "b03ce7b16c3f75c04fe20fdda224c45849eeba0d")
        self.assertEqual(p["current_request_id"], "3d-prism-route-3d-b03ce7b16c3f")
        self.assertEqual(p["identity_state"], "WAITING_USER_IDENTITY")
        self.assertEqual(p["non_identity_pre_identity_blocker_count"], 0)
        tooling = p["tooling_commit_4c22875c"]
        self.assertEqual(tooling["sha"], "4c22875c5ed79d393516c6a7a95361b9e9ed1950")
        self.assertEqual(tooling["changed_files"], ["tools/prism_revision_package_binding.py"])
        self.assertFalse(tooling["product_source"])
        self.assertEqual(p["historical_identity"]["source_sha"],
                         "15fdcb52e46e35e6de8e87c55af99719c21e09b9")
        self.assertFalse(p["historical_identity"]["old_identity_reuse_allowed"])
        qa = p["independent_qa"]
        self.assertEqual(qa["current_head_sha"], "9b90bfc9dfa6ded9699c3f22df45390be909dae8")
        self.assertEqual(qa["exact_head_ci_status"], "PASS_8_OF_8")
        self.assertEqual(qa["physical_windows_sessions_completed"], 0)
        self.assertEqual(qa["physical_screenshots_completed"], 0)
        self.assertIsNone(p["package_version"])
        self.assertFalse(p["real_msix"])

    def test_signal_sprint_remains_gdk_only_and_dry_run(self):
        s = self.overlay["product_identity_state_classification"]["signal_sprint"]
        self.assertEqual(s["current_source_sha"], "1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertTrue(s["branch_head_verified"])
        self.assertEqual(s["current_request_id"],
                         "game-signal-sprint-1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertEqual(s["registration_type"], "GDK_GAME")
        self.assertEqual(s["route"], "GDK_GAME")
        self.assertTrue(s["request_dry_run"])
        self.assertFalse(s["request_submitted"])
        self.assertTrue(s["identity_reference_received"])
        self.assertFalse(s["identity_return_applied"])
        self.assertFalse(s["cas_applied"])
        self.assertEqual(s["gdk_sdk_status"], "HOLD_GDK_SDK_ROOT_NOT_FOUND")
        self.assertFalse(s["required_revision_in_frozen_source"])
        self.assertFalse(s["physical_windows_uia_pass"])
        self.assertFalse(s["real_msixvc"])
        self.assertFalse(s["ordinary_msix_allowed"])

    def test_app_cohort_counts_four_generated_and_one_candidate_only(self):
        cohort = self.overlay["app_cohort"]
        self.assertEqual(cohort["planned_products"], 5)
        self.assertEqual(cohort["historically_generated_products"], 4)
        self.assertEqual(cohort["current_source_identity_received"], 0)
        self.assertEqual(len(cohort["generated_products"]), 4)
        self.assertEqual(cohort["candidate_only_products"][0]["product"],
                         "Offline Notes Canary")
        self.assertFalse(cohort["candidate_only_products"][0]["generated"])
        self.assertTrue(cohort["no_sixth_product"])
        image = next(x for x in cohort["generated_products"]
                     if x["product"] == "Offline Image Inventory Desk")
        text = next(x for x in cohort["generated_products"]
                    if x["product"] == "Offline Text Diff Desk")
        self.assertEqual(image["artifact_download_status"],
                         "HTTP_404_CURRENT_ARTIFACT_UNAVAILABLE")
        self.assertEqual(text["artifact_download_status"],
                         "HTTP_404_CURRENT_ARTIFACT_UNAVAILABLE")
        self.assertEqual(image["gui_status"], "UNVERIFIED")
        self.assertEqual(text["gui_status"], "UNVERIFIED")

    def test_local_code_sync_is_not_promoted_from_cloud_to_local_pass(self):
        sync = self.overlay["local_code_sync"]
        self.assertEqual(sync["status"], "NOT_OBSERVED__CLOUD_PASS_ONLY")
        self.assertEqual(sync["overall_status"], "HOLD_LOCAL_WINDOWS_EXECUTION_NOT_AVAILABLE")
        self.assertEqual(sync["exact_three_sha_tuple"], {
            "local_sync_tooling_commit": "b962910095adcdbcee7fb0c1ef12e4fb3575c9e8",
            "signal_sprint_source_sha": "1a349faa41663c417c40710140a4d50c79b62b78",
            "prism_route_3d_source_sha": "b03ce7b16c3f75c04fe20fdda224c45849eeba0d",
        })
        local = sync["local_execution"]
        self.assertFalse(local["physical_user_windows_session_available"])
        self.assertFalse(local["powershell_available"])
        self.assertFalse(local["windows_task_scheduler_available"])
        self.assertFalse(local["local_code_sync_pass"])
        self.assertFalse(sync["repository_tree_scan"]["durable_local_code_sync_receipt_found"])

    def test_partner_center_readback_is_not_assumed(self):
        pc = self.overlay["partner_center_readback"]
        self.assertFalse(pc["authenticated_browser_context_available"])
        self.assertEqual(pc["browser_access_result"],
                         "REQUIRES_ORIGINATING_BROWSER_CONTEXT")
        self.assertEqual(pc["current_source_identity_readback"], "NOT_COLLECTED")
        self.assertEqual(pc["authoritative_package_version_readback"], "NOT_COLLECTED")
        self.assertFalse(pc["partner_center_write_performed"])
        self.assertFalse(pc["identity_write_performed"])
        self.assertFalse(pc["version_inferred"])

    def test_canonical_ledger_pointer_mismatch_is_disclosed_not_rewritten(self):
        ledger = self.overlay["canonical_ledger"]
        self.assertTrue(ledger["pointer_mismatch"])
        self.assertEqual(ledger["actual_pr165_head_sha"],
                         "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertIn("left unchanged", ledger["resolution"])

    def test_transport_and_store_gates_remain_fail_closed(self):
        d = self.overlay["transport_and_downstream"]
        self.assertEqual(d["first_unconnected_interval"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        for key in ("real_product_msix_received", "github_backlog_receipt",
                    "local_pull_receipt", "windows_checker_receipt",
                    "local_gui_install_receipt", "product_e2e_pass"):
            self.assertFalse(d[key])
        store = self.overlay["store_upload_test"]
        self.assertEqual(store["eligible_fresh_unsold_products"], 0)
        self.assertFalse(store["dry_run_started"])
        self.assertFalse(store["live_started"])
        for key in ("store_submission_allowed", "certification_allowed", "publish_allowed"):
            self.assertFalse(self.overlay["safety"][key])
        self.assertFalse(self.overlay["safety"]["pr12_or_pr24_repo_touched"])
        self.assertFalse(self.overlay["safety"]["png_generation_or_modification_by_36"])
        self.assertFalse(self.queue["new_product_generation_allowed"])
        self.assertEqual([x["product"] for x in self.queue["priority"]],
                         ["Focus Session Desk", "File Integrity Ledger",
                          "Prism Route 3D", "Signal Sprint"])


if __name__ == "__main__":
    unittest.main()
