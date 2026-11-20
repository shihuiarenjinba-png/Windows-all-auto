from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DataContractGroupCTeacherTests(unittest.TestCase):
    def setUp(self):
        self.receipt = json.loads(
            (
                ROOT
                / "ops"
                / "data_contract_auditor_group_c_teacher_20261120.json"
            ).read_text(encoding="utf-8")
        )

    def test_live_product_binding_is_exact(self):
        product = self.receipt["product"]
        self.assertEqual(product["name"], "Data Contract Auditor")
        self.assertEqual(product["store_id"], "9PDL4ZWSB45P")
        self.assertEqual(product["draft_id"], "1152921505702212222")
        self.assertEqual(product["submission_route"], "msix_pwa_app")
        self.assertEqual(
            product["source_sha"],
            "107e59f2cbcde9c6ca88cf1aaf3d52262004e6e0",
        )

    def test_partner_center_identity_matches_product_only(self):
        identity = self.receipt["partner_center_live_observation"]["identity"]
        self.assertEqual(
            identity["package_identity_name"],
            "OkinawaDesktopTools.DataContractAuditor",
        )
        self.assertEqual(
            identity["publisher"],
            "CN=46263F21-A700-41DB-8C9B-114C22FB82FC",
        )
        self.assertEqual(
            identity["package_family_name"],
            "OkinawaDesktopTools.DataContractAuditor_j8yefg9jgfh58",
        )

    def test_qa_package_can_never_be_promoted(self):
        package = self.receipt["github_evidence"]["qa_only_package"]
        self.assertIn("QA_UNSIGNED", package["file_name"])
        self.assertFalse(package["store_upload_allowed"])
        self.assertEqual(package["version"], "1.0.63.0")
        self.assertEqual(
            self.receipt["route_mechanics"]["current_action"],
            "HOLD_BEFORE_PACKAGE_UPLOAD",
        )

    def test_partial_qa_is_not_real_device_pass(self):
        qa = self.receipt["windows_real_device_qa"]
        self.assertEqual(qa["core_engine"]["valid_input"], "PASS")
        self.assertTrue(qa["core_engine"]["source_files_byte_unchanged"])
        self.assertEqual(qa["ja_en_ui"], "NOT_EXECUTED")
        self.assertEqual(qa["secondary_dpi"], "NOT_EXECUTED")
        self.assertEqual(qa["status"], "PARTIAL_CORE_PASS_UI_PENDING")
        self.assertEqual(
            qa["launch_reconciliation"]["classification"],
            "UNKNOWN_NOT_POLICY_BLOCK",
        )
        self.assertFalse(
            qa["launch_reconciliation"]["matching_code_integrity_event_observed"]
        )

    def test_missing_formal_inputs_fail_closed(self):
        gate = self.receipt["formal_candidate_gate"]
        self.assertIsNone(gate["approved_store_version"])
        self.assertFalse(gate["final_artwork_approved"])
        self.assertFalse(gate["windows_real_device_qa_pass"])
        self.assertFalse(gate["ready_for_formal_store_msix"])
        self.assertFalse(gate["ready_for_partner_center_package_upload"])
        self.assertEqual(
            self.receipt["current_state"],
            "HOLD_FORMAL_VERSION_ASSETS_UI_QA",
        )

    def test_external_side_effects_are_absent(self):
        safety = self.receipt["safety"]
        self.assertFalse(safety["qa_unsigned_uploaded"])
        self.assertFalse(safety["package_uploaded"])
        self.assertFalse(safety["package_save_performed"])
        self.assertFalse(safety["certification_executed"])
        self.assertFalse(safety["publish_executed"])


if __name__ == "__main__":
    unittest.main()
