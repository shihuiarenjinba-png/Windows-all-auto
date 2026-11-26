import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops/active_e2e_handoff_overlay_20261126_173752.json"


class IdentitySourceVersionReconciliation20261127Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.focus = cls.data["source_identity_version_reconciliation"]["focus_session_desk"]
        cls.file = cls.data["source_identity_version_reconciliation"]["file_integrity_ledger"]

    def test_historical_focus_identity_is_not_current_source_approval(self):
        current = self.focus["current_source"]
        old = self.focus["historical_approved_identity_return"]
        self.assertEqual(old["source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(old["request_id"], "app-focus-session-desk-8b00bc4e9082")
        self.assertEqual(old["store_id"], "9P6452C61N7B")
        self.assertEqual(old["package_version_gate"], "HOLD")
        self.assertEqual(old["signature_status"], "PRE_IDENTITY_EXE_NOT_MSIX")
        self.assertEqual(current["source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(current["request_id"], "app-focus-session-desk-fb6293839bc7")
        self.assertEqual(current["identity_status"], "STALE_TRACKED")
        self.assertEqual(current["source_compare_from_returned_identity_source"]["ahead_by"], 27)
        self.assertEqual(current["source_compare_from_returned_identity_source"]["behind_by"], 0)
        self.assertIsNone(current["package_version"])
        self.assertEqual(current["version_status"], "MISSING")

    def test_historical_file_identity_is_not_current_source_approval(self):
        current = self.file["current_source"]
        old = self.file["historical_approved_identity_return"]
        self.assertEqual(old["source_sha"], "d1108d12f7d1697af30400f97c7db39cba5e6791")
        self.assertEqual(old["request_id"], "app-file-integrity-ledger-d1108d12f7d1")
        self.assertEqual(old["store_id"], "9PGZ445SR5GM")
        self.assertEqual(old["package_version_gate"], "HOLD")
        self.assertEqual(old["signature_status"], "PRE_IDENTITY_EXE_NOT_MSIX")
        self.assertEqual(current["source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(current["request_id"], "app-file-integrity-ledger-33d612be2774")
        self.assertFalse(current["approved_identity_file_present"])
        self.assertEqual(current["identity_status"], "MISSING")
        compare = current["source_compare_from_returned_identity_source"]
        self.assertEqual(compare["status"], "diverged")
        self.assertEqual(compare["ahead_by"], 16)
        self.assertEqual(compare["behind_by"], 8)
        self.assertEqual(compare["merge_base"], "deaa9f324326a1ee276596c325f7a360adf27877")
        self.assertIsNone(current["package_version"])
        self.assertEqual(current["version_status"], "UNAVAILABLE")

    def test_real_product_preflight_remains_fail_closed(self):
        p = self.data["package_source_preflight"]
        self.assertEqual(p["focus"]["asset_validation"], "PASS")
        self.assertEqual(p["focus"]["identity_status"], "STALE_TRACKED")
        self.assertEqual(p["focus"]["version_status"], "MISSING")
        self.assertFalse(p["focus"]["product_msix_created"])
        self.assertEqual(p["file_integrity_ledger"]["asset_validation"], "PASS")
        self.assertEqual(p["file_integrity_ledger"]["identity_status"], "MISSING")
        self.assertEqual(p["file_integrity_ledger"]["version_status"], "UNAVAILABLE")
        self.assertFalse(p["file_integrity_ledger"]["product_msix_created"])
        fixture = p["disposable_makeappx_fixture"]
        self.assertEqual(fixture["artifact_class"], "QA_FIXTURE_ONLY_NOT_PRODUCT")
        self.assertTrue(fixture["identity_fixture_only"])
        self.assertTrue(fixture["version_fixture_only"])
        self.assertEqual(fixture["fixture_version"], "1.0.0.0")

    def test_focus_error_recovery_qa_does_not_promote_msix_or_e2e(self):
        q = self.data["focus_error_recovery_qa"]
        self.assertEqual(q["windows_gui_conclusion"], "success")
        self.assertEqual(q["product_source_sha"], self.focus["current_source"]["source_sha"])
        self.assertEqual(q["request_id"], self.focus["current_source"]["request_id"])
        self.assertEqual(q["scenarios"]["corrupt_primary_valid_backup"], "PASS")
        self.assertEqual(q["scenarios"]["invalid_duration_zero"], "PASS")
        self.assertFalse(q["real_msix_created"])

    def test_green_transport_ci_does_not_promote_product_e2e(self):
        t = self.data["transport"]
        self.assertEqual(t["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(t["pr165"]["head_sha"], "84f9a3480e2df93f0d75bddc29fb8de47e4ec941")
        self.assertEqual(t["pr192"]["head_sha"], "792a6ab7bc1a5847c03ebf59e07354edb3d3afb0")
        self.assertEqual(t["pr194"]["head_sha"], "294e4dc2c3c631778edfee5c855ffe687d55d494")
        self.assertEqual(self.data["e2e_status"], "HOLD")
        self.assertFalse(self.data["e2e_pass"])
        self.assertFalse(self.data["downstream_receipts"]["real_msix"])
        self.assertFalse(self.data["downstream_receipts"]["github_backlog_receipt"])
        self.assertFalse(self.data["downstream_receipts"]["local_pull_receipt"])
        self.assertFalse(self.data["downstream_receipts"]["local_checker_receipt"])
        self.assertFalse(self.data["downstream_receipts"]["local_gui_install_receipt"])
        self.assertEqual(self.data["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.data["store_upload_test_eligibility"]["dry_run_started"])
        self.assertFalse(self.data["safety"]["store_submission_allowed"])
        self.assertFalse(self.data["safety"]["certification_allowed"])
        self.assertFalse(self.data["safety"]["publish_allowed"])


if __name__ == "__main__":
    unittest.main()
