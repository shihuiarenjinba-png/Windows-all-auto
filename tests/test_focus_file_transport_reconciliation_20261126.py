"""Append-only 2026-11-26 exact-head reconciliation; CI is not product E2E."""
import json
import unittest
from pathlib import Path

RECORD = Path(__file__).resolve().parents[1] / "ops" / "focus_file_transport_reconciliation_20261126.json"


class FocusFileTransportReconciliation20261126(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(RECORD.read_text(encoding="utf-8"))

    def test_pr165_exact_head_regressions_pass_without_promoting_product_e2e(self):
        d = self.data
        p = d["pr165"]
        head = p["latest_verified_code_head_sha"]
        self.assertEqual(head, "c68adc79ecf8a0c6ad4b538146648391b1b4eddb")
        self.assertEqual(p["tested_code_head_sha"], "c68adc79ecf8a0c6ad4b538146648391b1b4eddb")
        self.assertEqual(p["latest_exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(p["latest_exact_head_ci_run_ids"], [45731501639, 45731501700, 45731501669])
        self.assertEqual(p["latest_offline_qa_tests_run"], 564)
        self.assertEqual(p["latest_product_e2e_status"], "HOLD")
        latest = d["latest_observation"]
        self.assertEqual(latest["pr165_head_sha"], head)
        self.assertTrue(all(r["head_sha"] == head and r["conclusion"] == "success"
                            for r in latest["exact_head_workflows"]))
        self.assertEqual(p["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([r["run_id"] for r in p["exact_head_ci"]], [45731501639, 45731501700, 45731501669])
        self.assertTrue(all(r["head_sha"] == head and r["conclusion"] == "success"
                            for r in p["exact_head_ci"]))
        self.assertEqual(p["offline_qa"]["ubuntu_conclusion"], "success")
        self.assertEqual(p["offline_qa"]["windows_conclusion"], "success")
        self.assertEqual(p["offline_qa"]["tests_run"], 564)
        self.assertEqual(p["offline_qa"]["windows_skipped"], 2)
        self.assertEqual(p["product_e2e_status"], "HOLD")
        self.assertIs(p["real_msix"], False)
        self.assertIs(p["downstream_receipts"], False)
        self.assertIs(d["e2e_pass"], False)
        self.assertEqual(d["status"], "HOLD")

    def test_current_branch_head_pass_is_separate_from_parent_snapshot_failure(self):
        current = self.data["current_branch_head_observation"]
        self.assertEqual(current["head_sha"], "1b2f2c15a8d1ed436e364f7b9a61591b47d8a3d0")
        self.assertEqual(current["parent_sha"], "2ba11031c1c713abb7b548125b10b48af5346bfd")
        self.assertEqual(current["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(current["comparison_to_last_tested_code_head"]["ahead_by"], 15)
        self.assertFalse(current["product_code_changed"])
        self.assertFalse(current["e2e_pass"])
        self.assertEqual(current["parent_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in current["parent_ci"]], [45735513903, 45735513946, 45735513940])
        self.assertEqual(self.data["pr165_current_branch_head_sha"], current["head_sha"])
        self.assertEqual(self.data["pr165_current_branch_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(self.data["snapshot_commit_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(self.data["ledger_reconciliation"]["actual_pr165_head"], current["head_sha"])
        self.assertEqual([x["run_id"] for x in current["exact_head_ci"]], [45735790127, 45735790125, 45735790106])
        self.assertEqual(self.data["pr165"]["latest_verified_code_head_sha"], "c68adc79ecf8a0c6ad4b538146648391b1b4eddb")
        self.assertEqual(self.data["pr165"]["immediate_parent_ci_status"], "PARTIAL_FAIL_RECONCILIATION_TEST_KEYERROR")
        self.assertEqual([x["run_id"] for x in self.data["pr165"]["immediate_parent_exact_head_ci"]], [45731429031, 45731429039, 45731429057])
        self.assertFalse(self.data["e2e_pass"])

    def test_request_artifacts_are_verified_dry_run_only_and_have_no_authoritative_version(self):
        evidence = self.data["independent_request_artifact_readback_20261126"]
        focus = evidence["focus_session_desk"]
        self.assertEqual(focus["artifact_id"], 15049692591)
        self.assertEqual(focus["artifact_sha256"], "c8b15058243982d90699dfb2a885a71b064a0a02b01dcb3c7492dec83ec3afae")
        self.assertEqual(focus["request_sha256"], "a950b9bcf0bf59b45cc724651ed9a736181ff69388c04f8aefcdd7d9975b7a94")
        self.assertEqual(focus["source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertIsNone(focus["package_version"])
        self.assertTrue(focus["dry_run"])
        self.assertFalse(focus["identity_write"])
        self.assertFalse(focus["partner_center_write"])
        self.assertFalse(focus["msix_build"])
        file = evidence["file_integrity_ledger"]
        self.assertEqual(file["artifact_id"], 14934034365)
        self.assertEqual(file["artifact_sha256"], "697528b3b0769e3962eebfa0efcdcb026618cd378d97fc60c4f234017882527e")
        self.assertEqual(file["request_sha256"], "dc477b03dd8eb024dd4145fb56cace5d57531a9ae3bbba74a487631f823b2557")
        self.assertEqual(file["source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(file["package_status"], "NOT_BUILT")
        self.assertEqual(file["official_identity_status"], "UNVERIFIED")
        self.assertIsNone(file["version"])
        self.assertFalse(file["partner_center_lookup_performed"])
        focus_identity = self.data["focus_identity_file_readback_20261126"]
        self.assertEqual(focus_identity["identity_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(focus_identity["package_version_gate"], "HOLD")
        self.assertFalse(focus_identity["current_source_reuse_allowed"])
        file_identity = self.data["file_identity_file_readback_20261126"]
        self.assertEqual(file_identity["status"], "NOT_FOUND_ON_CURRENT_PR115_HEAD")

    def test_focus_remains_blocked_on_current_source_identity_and_authoritative_version(self):
        p = self.data["products"]["focus_session_desk"]
        self.assertEqual(p["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(p["historical_approved_identity"]["source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertNotEqual(p["historical_approved_identity"]["source_sha"], p["current_source_sha"])
        self.assertEqual(p["current_source_identity_binding_status"],
                         "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
        self.assertEqual(p["current_source_request"]["status"], "DRY_RUN")
        self.assertEqual(p["current_source_request"]["official_identity_status"], "NOT_COLLECTED")
        self.assertIsNone(p["current_source_request"]["package_version"])
        self.assertIsNone(p["package_version"])
        self.assertIs(p["real_msix"], False)
        self.assertEqual(p["msix_export"]["status"], "FAILED_MISSING_VERIFIED_VERSION")
        self.assertEqual(p["product_quality_score"], 54)
        self.assertEqual(p["sale_decision"], "DO_NOT_SELL_BELOW_80")
        self.assertEqual(p["assets"]["owner"], "00")
        self.assertIs(p["assets"]["raw_png_bytes_rehashed_this_run"], False)

    def test_file_integrity_remains_blocked_on_current_source_identity_and_owner_review(self):
        p = self.data["products"]["file_integrity_ledger"]
        self.assertEqual(p["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(p["historical_approved_identity"]["source_sha"],
                         "d1108d12f7d1697af30400f97c7db39cba5e6791")
        self.assertIs(p["current_source_approved_identity_present"], False)
        self.assertEqual(p["current_source_request"]["status"], "DRY_RUN")
        self.assertEqual(p["current_source_request"]["official_identity_status"], "UNVERIFIED")
        self.assertIsNone(p["current_source_request"]["package_version"])
        self.assertIsNone(p["package_version"])
        self.assertIs(p["real_msix"], False)
        self.assertEqual(p["msix_export"]["status"], "SKIPPED_NO_ARTIFACT")
        self.assertIs(p["human_owner_visual_review_required"], True)
        self.assertEqual(p["gui_evidence"]["visual_review_status"],
                         "36_SCREENSHOT_INSPECTION_PASS__HUMAN_OWNER_REVIEW_REQUIRED")

    def test_real_transport_requires_current_source_approved_identity_and_custody_pair(self):
        t = self.data["transport_contract"]
        self.assertEqual(
            t["app_identity_return_requires_paired_files"],
            ["approved-identity.json", "transport_receipt.json", "github-custody.json"],
        )
        self.assertTrue(t["synthetic_regression_fixtures_only"])
        self.assertIs(t["real_product_msix_verified"], False)
        self.assertIs(t["live_partner_center_readback_verified"], False)
        self.assertIs(t["local_product_e2e_verified"], False)
        self.assertIs(t["store_authorization"], False)
        f = self.data["first_unconnected_interval"]
        self.assertEqual(f["status"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        self.assertIs(f["real_msix"], False)
        self.assertIs(f["github_backlog_receipt"], False)
        self.assertIs(f["local_pull_receipt"], False)
        self.assertIs(f["windows_checker_receipt"], False)
        self.assertIs(f["local_gui_install_receipt"], False)
        self.assertIs(f["product_e2e_pass"], False)

    def test_pr161_pr171_and_pr177_are_not_misrepresented(self):
        d = self.data
        self.assertEqual(d["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(d["pr161"]["exact_head_run_id"], 42712757936)
        self.assertEqual(d["pr161"]["exact_head_conclusion"], "success")
        self.assertEqual(d["pr171"]["head_sha"], "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(d["pr171"]["exact_head_run_id"], 44437197470)
        self.assertEqual(d["pr171"]["exact_head_conclusion"], "success")
        self.assertTrue(d["pr171"]["store_upload_bridge_present"])
        self.assertIs(d["pr171"]["store_upload_dry_run_started"], False)
        self.assertEqual(d["pr171"]["eligible_fresh_unsold_products"], 0)
        self.assertEqual(d["pr177"]["compare_to_pr165"]["ahead_by"], 89)
        self.assertEqual(d["pr177"]["compare_to_pr165"]["behind_by"], 6)
        self.assertEqual(d["pr177"]["decision"], "DO_NOT_RESTACK")
        self.assertEqual(d["pr177"]["latest_compare_to_latest_pr165"]["ahead_by"], 6)
        self.assertEqual(d["pr177"]["latest_compare_to_latest_pr165"]["behind_by"], 119)
        self.assertEqual(d["pr177"]["latest_compare_to_latest_pr165"]["decision"], "DO_NOT_RESTACK")

    def test_active_ledger_direct_blob_readback_is_reconciled(self):
        l = self.data["ledger_reconciliation"]
        self.assertIs(l["active_ledger_direct_content_available"], True)
        self.assertIn("NOT_TREATED_AS_EMPTY_FILE", l["active_ledger_content_fetch_status"])
        self.assertIs(l["active_ledger_direct_update_performed"], True)
        self.assertEqual(l["latest_pr165_head"], self.data["pr165"]["latest_verified_code_head_sha"])

    def test_store_and_repository_safety_flags_remain_closed(self):
        s = self.data["safety"]
        for key in (
            "store_submission_allowed", "certification_allowed", "publish_allowed",
            "live_partner_center_write_allowed", "merge_allowed", "force_push_allowed",
            "product_code_changes", "prism_old_source_identity_cas",
            "twelve_repo_touched", "twentyfour_repo_touched", "png_generation_or_modification",
        ):
            self.assertIs(s[key], False)
        self.assertEqual(self.data["store_upload_test"]["eligible_fresh_unsold_products"], 0)
        self.assertIs(self.data["store_upload_test"]["dry_run_started"], False)


if __name__ == "__main__":
    unittest.main()
