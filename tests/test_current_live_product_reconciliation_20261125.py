import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ops" / "active_e2e_handoff.json"
RECON = ROOT / "ops" / "focus_file_transport_reconciliation_20261125.json"


class CurrentLiveProductReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.recon = json.loads(RECON.read_text(encoding="utf-8"))

    def test_pr165_exact_head_ci_is_not_product_e2e(self):
        latest = self.ledger["latest_transport_reconciliation"]
        self.assertEqual(latest["central_head"], "addefcb0303897c3ce25c0b54f5d43b9336232f9")
        self.assertEqual(latest["central_tested_head_sha"], "addefcb0303897c3ce25c0b54f5d43b9336232f9")
        self.assertEqual(latest["previous_central_head_sha"], "dfe03df83a75cd696f6bdb10d482db4ada9c0d35")
        self.assertEqual(latest["pr165_current_branch_head_sha"], "addefcb0303897c3ce25c0b54f5d43b9336232f9")
        self.assertEqual(latest["pr165_current_branch_head_parent_sha"], "dfe03df83a75cd696f6bdb10d482db4ada9c0d35")
        self.assertEqual(latest["pr165_current_branch_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in latest["pr165_current_branch_head_ci"]],
                         [45680373334, 45680373323, 45680373386])
        self.assertEqual([x["run_id"] for x in latest["exact_head_ci"]],
                         [45680373334, 45680373323, 45680373386])
        self.assertEqual([x["run_id"] for x in latest["previous_exact_head_ci"]],
                         [45669620650, 45669620537, 45669620784])
        self.assertEqual(latest["previous_tested_head_sha"], "b67e333178bff5a2214ad059a370163597a528c6")
        self.assertEqual([x["run_id"] for x in latest["previous_tested_exact_head_ci"]],
                         [45658953507, 45658953645, 45658953242])
        self.assertEqual(latest["pr165_current_head_parent_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in latest["pr165_current_head_parent_ci"]], [45669620650, 45669620537, 45669620784])
        self.assertEqual(latest["ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(latest["status"], "HOLD")
        observation = self.ledger["pr165_live_head_observation_20261126_latest"]
        self.assertEqual(observation["head_sha"], "c2c901525718cce96eb56135c9044edb5d062682")
        self.assertEqual(observation["parent_sha"], "addefcb0303897c3ce25c0b54f5d43b9336232f9")
        self.assertEqual(observation["comparison_to_previous_tested_head"]["ahead_by"], 1)
        self.assertEqual(observation["status"], "FAIL_STALE_TEST_EXPECTATIONS")
        self.assertEqual(observation["last_verified_head_sha"], "addefcb0303897c3ce25c0b54f5d43b9336232f9")
        self.assertEqual(self.ledger["pr165_current_head_parent_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in self.ledger["pr165_current_head_parent_ci"]], [45680373334, 45680373323, 45680373386])
        self.assertEqual(self.ledger["pr165_current_branch_head_ci_status"], "FAIL_STALE_TEST_EXPECTATIONS")
        self.assertEqual(self.ledger["e2e_status"], "HOLD")
        self.assertIs(self.ledger["e2e_pass"], False)
        self.assertIs(latest["real_msix"], False)

    def test_focus_and_file_integrity_remain_source_and_version_held(self):
        products = {x["product"]: x for x in self.ledger["current_priority_products"]}
        focus = products["Focus Session Desk"]
        self.assertEqual(focus["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["approved_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(focus["expected_current_source_request_id"], "app-focus-session-desk-fb6293839bc7")
        self.assertEqual(focus["current_source_request_status"],
                         "GENERATED__DRY_RUN_ARTIFACT_VERIFIED__IDENTITY_READBACK_PENDING")
        self.assertIsNone(focus["package_version"])
        self.assertIs(focus["real_msix"], False)

        file_row = products["File Integrity Ledger"]
        self.assertEqual(file_row["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(file_row["current_source_request_id"], "app-file-integrity-ledger-33d612be2774")
        self.assertEqual(file_row["current_source_request_status"],
                         "DRY_RUN__OFFICIAL_IDENTITY_UNVERIFIED__PACKAGE_NOT_BUILT__LOCAL_WINDOWS_BUILD_NOT_IMPLEMENTED")
        self.assertEqual(file_row["current_source_request_artifact_id"], 14934034365)
        self.assertEqual(file_row["current_source_request_artifact_sha256"],
                         "697528b3b0769e3962eebfa0efcdcb026618cd378d97fc60c4f234017882527e")
        self.assertEqual(file_row["current_source_request_official_identity_status"], "UNVERIFIED")
        self.assertIs(file_row["approved_identity_file_present_on_current_pr115_head"], False)
        self.assertIsNone(file_row["package_version"])
        self.assertIs(file_row["real_msix"], False)

    def test_signal_current_tuple_is_separate_from_historical_c058(self):
        self.assertIsNone(self.ledger["current_active_product"])
        self.assertTrue(self.ledger["active_product_is_historical"])
        self.assertEqual(self.ledger["active_product_record_status"], "HISTORICAL_ONLY_NOT_CURRENT_REQUEST")
        self.assertEqual(self.ledger["active_product_pointer_status"],
                         "HISTORICAL_RECORD_ONLY__NO_ACTIVE_REQUEST_POINTER__USE_PRIORITY_QUEUE")
        historical = self.ledger["active_product"]
        self.assertFalse(historical["current_request_pointer"])
        self.assertEqual(historical["source_sha"], "c058cbf7fe38e02d929c67d047d717ff74bd522e")
        self.assertEqual(historical["request_id"],
                         "game-signal-sprint-c058cbf7fe38e02d929c67d047d717ff74bd522e")
        self.assertEqual(self.ledger["historical_active_product_20261125"]["source_sha"],
                         "c058cbf7fe38e02d929c67d047d717ff74bd522e")
        self.assertEqual(self.ledger["current_completion_priority"]["product"], "Focus Session Desk")
        signal = self.ledger["current_signal_sprint_live_20261125"]
        self.assertEqual(signal["current_candidate_source_sha"],
                         "1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertTrue(signal["source_branch_head_matches_pinned_source"])
        self.assertEqual(signal["current_request_id"],
                         "game-signal-sprint-1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertEqual(signal["registration_type"], "GDK_GAME")
        self.assertTrue(signal["request_dry_run"])
        self.assertFalse(signal["request_submitted"])
        self.assertEqual(signal["cas_status"], "NOT_APPLIED")
        self.assertTrue(signal["identity_preview"]["preview_stale_relative_to_latest_build"])
        self.assertEqual(signal["identity_preview"]["preview_build_run_id"], 45418088785)
        self.assertEqual(signal["latest_build"]["run_id"], 45446392478)
        self.assertEqual(signal["latest_build"]["exe_artifact_id"], 14946655071)
        self.assertEqual(signal["latest_build"]["gdk_readiness_artifact_id"], 14946675208)
        self.assertEqual(signal["gdk_sdk_status"], "HOLD_GDK_SDK_ROOT_NOT_FOUND")
        self.assertFalse(signal["physical_windows_uia_pass"])
        self.assertFalse(signal["required_revision_in_frozen_source"])
        self.assertIsNone(signal["package_version"])
        self.assertFalse(signal["real_msixvc"])

    def test_registration_routes_are_explicit_and_not_inferred_from_identity(self):
        routes = self.ledger["current_live_registration_routing_20261125"]
        entries = {x["product"]: x for x in routes["entries"]}
        self.assertEqual(entries["Focus Session Desk"]["registration_type"], "MSIX_OR_PWA_APP")
        self.assertEqual(entries["File Integrity Ledger"]["registration_type"], "MSIX_OR_PWA_APP")
        self.assertEqual(entries["Signal Sprint"]["registration_type"], "GDK_GAME")
        self.assertEqual(entries["Prism Route 3D"]["registration_type"], "MSIX_OR_PWA_GAME")
        self.assertEqual(entries["Offline Notes Canary"]["registration_type"], "MSIX_OR_PWA_APP")
        self.assertEqual(entries["Offline Text Diff Desk"]["registration_type"], "MSIX_OR_PWA_APP")
        self.assertEqual(entries["Offline Image Inventory Desk"]["registration_type"], "MSIX_OR_PWA_APP")
        self.assertEqual(routes["source_ci_run_id"], 40638938248)

    def test_pr174_and_store_safety_remain_fail_closed(self):
        self.assertEqual(self.recon["pr174"]["compare_to_current_pr165_head"]["behind_by"], 149)
        self.assertEqual(self.recon["pr174"]["decision"], "DO_NOT_RESTACK")
        self.assertEqual(self.ledger["parallel_draft_branch_assessment_20261125_0635"]["decision"],
                         "NO_BLIND_RESTACK__ALL_RELEVANT_CHANGES_ALREADY_PRESENT_OR_SUPERSEDED")
        parallel = self.ledger["parallel_draft_branch_assessment_20261125_0635"]
        self.assertEqual(parallel["current_pr165_head_sha"], "b67e333178bff5a2214ad059a370163597a528c6")
        self.assertEqual([x["behind_by"] for x in parallel["branches"]], [63, 63, 63])
        self.assertEqual([x["ahead_by"] for x in parallel["branches"]], [6, 16, 6])
        self.assertEqual(self.ledger["store_upload_test_bridge"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.ledger["store_upload_test_bridge"]["dry_run_started"])
        self.assertEqual(self.ledger["local_code_sync_receipt_status_20261125"],
                         "NOT_OBSERVED__CLOUD_PASS_ONLY")
        for key in ("store_submission_allowed", "certification_allowed", "publish_allowed",
                    "live_partner_center_write_allowed", "merge_allowed", "force_push_allowed"):
            self.assertIs(self.ledger[key], False)


if __name__ == "__main__":
    unittest.main()
