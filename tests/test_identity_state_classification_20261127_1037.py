"""Regression for 2026-11-27 current-source Identity state classification."""
import json
import unittest
from pathlib import Path


class CurrentIdentityStateClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.data = json.loads(
            (root / "ops" / "active_e2e_handoff_overlay_20261127_1037.json")
            .read_text(encoding="utf-8")
        )
        cls.states = cls.data["identity_state_classification"]

    def test_observation_is_bound_to_live_pr205_and_pr165_heads(self):
        p205 = self.data["observation_basis"]["pr205"]
        self.assertEqual(p205["head_sha_before_append"],
                         "490e4533c35740f9eb6d9695bab860895630521e")
        self.assertEqual([x["run_id"] for x in p205["exact_head_ci"]],
                         [45917965610, 45917965618, 45917965593])
        self.assertTrue(all(x["head_sha"] == p205["head_sha_before_append"]
                            and x["conclusion"] == "success"
                            for x in p205["exact_head_ci"]))
        p165 = self.data["observation_basis"]["pr165"]
        self.assertEqual(p165["head_sha"],
                         "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertTrue(all(x["conclusion"] == "success"
                            for x in p165["exact_head_ci"]))
        self.assertEqual(p165["product_e2e_status"], "HOLD")

    def test_focus_is_not_waiting_for_identity_until_current_request_exists(self):
        f = self.states["focus_session_desk"]
        self.assertEqual(f["identity_state"], "PRE_IDENTITY_FIX_REQUIRED")
        self.assertEqual(f["current_source_sha"],
                         "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(f["current_source_request"]["expected_request_id"],
                         "app-focus-session-desk-b6b69464a9c7")
        self.assertFalse(f["current_source_request"]["observed"])
        self.assertEqual(f["current_source_request"]["previous_request_source_sha"],
                         "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(f["identity"]["source_sha"],
                         "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertFalse(f["identity"]["current_source_reuse_allowed"])
        self.assertEqual(f["non_identity_pre_identity_blocker_count"], 1)
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])

    def test_file_integrity_waiting_identity_has_zero_non_identity_preflight_blockers(self):
        f = self.states["file_integrity_ledger"]
        self.assertEqual(f["identity_state"], "WAITING_USER_IDENTITY")
        self.assertEqual(f["current_source_sha"],
                         "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        request = f["current_source_request"]
        self.assertEqual(request["request_id"],
                         "app-file-integrity-ledger-33d612be2774")
        self.assertEqual(request["source_sha"], f["current_source_sha"])
        self.assertEqual(request["status"], "DRY_RUN")
        self.assertEqual(request["source_head_verification"], "VERIFIED")
        self.assertTrue(request["artifact_downloaded_and_rehashed"])
        self.assertEqual(request["artifact_zip_sha256"],
                         "697528b3b0769e3962eebfa0efcdcb026618cd378d97fc60c4f234017882527e")
        self.assertEqual(f["non_identity_pre_identity_blocker_count"], 0)
        self.assertEqual(f["non_identity_pre_identity_blockers"], [])
        self.assertFalse(f["identity"]["present_on_current_source"])
        self.assertEqual(f["identity"]["historical_source_sha"],
                         "d1108d12f7d1697af30400f97c7db39cba5e6791")
        assets = f["pre_identity_evidence"]["store_assets"]
        self.assertFalse(assets["raw_sha256_independently_recomputed"])
        self.assertEqual(assets["Square44"],
                         "bd61099427a770f8ddf247f0f6928e5d50ba2cd8265797c7f13952e96147d70d")
        self.assertFalse(f["identity"]["current_source_reuse_allowed"])
        self.assertIsNone(f["package_version"])
        self.assertEqual(f["package_version_status"], "AUTHORITATIVE_VALUE_REQUIRED")
        self.assertFalse(f["real_msix"])
        self.assertFalse(f["github_backlog_receipt"])
        self.assertFalse(f["local_pull_receipt"])
        self.assertFalse(f["windows_checker_receipt"])
        self.assertFalse(f["local_gui_install_receipt"])
        self.assertFalse(f["product_e2e_pass"])

    def test_local_windows_build_label_is_downstream_not_a_pre_identity_blocker(self):
        f = self.states["file_integrity_ledger"]
        build = f["local_windows_build_classification"]
        self.assertEqual(build["observed_label"], "LOCAL_WINDOWS_BUILD_NOT_IMPLEMENTED")
        self.assertEqual(build["classification"],
                         "POST_IDENTITY_DELIVERY_STEP_NOT_PRE_IDENTITY_BLOCKER")
        self.assertEqual(build["non_identity_pre_identity_blocker_count"], 0)
        self.assertTrue(build["builder_in_current_pr115_source"]["present"])
        self.assertTrue(build["builder_in_current_pr115_source"]["requires_approved_identity_and_version"])
        self.assertFalse(build["request_workflow"]["invokes_product_builder"])
        preflight = f["pre_identity_evidence"]["source_preflight"]
        self.assertEqual(preflight["source_sha"], f["current_source_sha"])
        self.assertEqual(preflight["identity_status"], "MISSING")
        self.assertEqual(preflight["version_status"], "UNAVAILABLE")
        self.assertEqual(preflight["hold_reason"],
                         "official source-bound Identity return missing")
        self.assertFalse(preflight["makeappx_invoked_for_product"])
        self.assertFalse(preflight["product_msix_created"])
        self.assertTrue(preflight["separate_qa_fixture"]["not_file_integrity_product"])
        self.assertIn("RUN_WINDOWS_PYINSTALLER_AND_MAKEAPPX_FOR_EXACT_SOURCE",
                      build["post_identity_delivery_steps"])
        self.assertEqual(f["identity_state"], "WAITING_USER_IDENTITY")

    def test_prism_4c_is_tooling_and_old_identity_cannot_bind_to_b03(self):
        p = self.states["prism_route_3d"]
        self.assertEqual(p["identity_state"], "PRE_IDENTITY_FIX_REQUIRED")
        self.assertEqual(p["current_source_sha"],
                         "b03ce7b16c3f75c04fe20fdda224c45849eeba0d")
        self.assertEqual(p["current_request_id"],
                         "3d-prism-route-3d-b03ce7b16c3f")
        tooling = p["tooling_commit_4c22875c"]
        self.assertEqual(tooling["sha"],
                         "4c22875c5ed79d393516c6a7a95361b9e9ed1950")
        self.assertEqual(tooling["changed_files"],
                         ["tools/prism_revision_package_binding.py"])
        self.assertFalse(tooling["product_source"])
        self.assertEqual(p["historical_identity"]["source_sha"],
                         "15fdcb52e46e35e6de8e87c55af99719c21e09b9")
        self.assertFalse(p["historical_identity"]["old_identity_reuse_allowed"])
        qa = p["independent_qa"]
        self.assertEqual(qa["current_head_sha"],
                         "9b90bfc9dfa6ded9699c3f22df45390be909dae8")
        self.assertEqual(qa["exact_head_ci_status"], "PASS_8_OF_8")
        self.assertTrue(qa["cloud_ci_is_not_physical_qa"])
        self.assertEqual(qa["physical_windows_sessions_completed"], 0)
        self.assertEqual(qa["physical_screenshots_completed"], 0)

    def test_all_delivery_and_store_gates_remain_fail_closed(self):
        for value in self.data["downstream_gates"].values():
            if isinstance(value, bool):
                self.assertFalse(value)
        store = self.data["store_upload_test"]
        self.assertEqual(store["eligible_fresh_unsold_products"], 0)
        self.assertFalse(store["dry_run_started"])
        self.assertFalse(store["live_started"])
        safety = self.data["safety"]
        for key in (
            "live_partner_center_write_allowed",
            "store_submission_allowed",
            "certification_allowed",
            "publish_allowed",
            "merge_allowed",
            "main_release_direct_change_allowed",
            "force_push_allowed",
            "pr12_or_pr24_repo_touched",
        ):
            self.assertFalse(safety[key])
        self.assertEqual(self.data["status"], "HOLD")
        self.assertIs(self.data["e2e_pass"], False)


if __name__ == "__main__":
    unittest.main()
