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
        head = p["tested_code_head_sha"]
        self.assertEqual(head, "a6b9d2b1db3033d5846e136400d2fe67dede554d")
        self.assertEqual(p["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(
            [r["run_id"] for r in p["exact_head_ci"]],
            [45701014660, 45701014598, 45701014777],
        )
        self.assertTrue(all(r["head_sha"] == head and r["conclusion"] == "success"
                            for r in p["exact_head_ci"]))
        self.assertEqual(p["offline_qa"]["ubuntu_conclusion"], "success")
        self.assertEqual(p["offline_qa"]["windows_conclusion"], "success")
        self.assertEqual(p["offline_qa"]["tests_run"], 556)
        self.assertEqual(p["product_e2e_status"], "HOLD")
        self.assertIs(p["real_msix"], False)
        self.assertIs(p["downstream_receipts"], False)
        self.assertIs(d["e2e_pass"], False)
        self.assertEqual(d["status"], "HOLD")

    def test_focus_remains_blocked_on_current_source_identity_and_authoritative_version(self):
        p = self.data["products"]["focus_session_desk"]
        self.assertEqual(p["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(p["historical_approved_identity"]["source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertNotEqual(p["approved_identity"]["source_sha"], p["current_source_sha"])
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

    def test_active_ledger_unavailable_is_not_treated_as_an_empty_file(self):
        l = self.data["ledger_reconciliation"]
        self.assertIs(l["active_ledger_direct_content_available"], False)
        self.assertIn("NOT_TREATED_AS_EMPTY_FILE", l["active_ledger_content_fetch_status"])
        self.assertIs(l["active_ledger_direct_update_performed"], False)
        self.assertEqual(l["latest_pr165_head"], self.data["pr165"]["tested_code_head_sha"])

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
