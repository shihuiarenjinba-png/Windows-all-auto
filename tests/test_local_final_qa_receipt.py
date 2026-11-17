import json
import subprocess
import sys
import unittest
from pathlib import Path

from all_auto.store_product_handoff import (
    StoreHandoffError,
    apply_local_final_qa_receipt,
    apply_pre_store_static_qa_receipt,
    apply_store_signed_install_qa_receipt,
    normalize_store_product_handoff,
)


class LocalFinalQaReceiptTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parent / "fixtures" / "folder_engine_paid_trial_handoff_v2.json"
        self.payload = json.loads(path.read_text(encoding="utf-8"))
        self.payload["qa"] = {
            "github_exact_head_ci_pass": True,
            "local_final_pass": False,
            "store_signed_install_pass": False,
        }
        self.receipt = {
            "schema_version": "local-final-qa-receipt/1",
            "status": "PASS",
            "store_id": self.payload["identity"]["store_id"],
            "source_sha": self.payload["product"]["source_sha"],
            "package_sha256": self.payload["package"]["package_sha256"],
            "tests_passed": True,
            "package_sha_verified": True,
            "unpacked_exe_sha_verified": True,
            "jp_en_gui_passed": True,
            "dpi_matrix_passed": True,
            "product_specific_acceptance_passed": True,
            "normal_exit_passed": True,
            "package_rebuilt": False,
            "security_bypass_used": False,
            "product_specific_checks": ["folder-copy", "folder-move"],
        }

    def test_qa_gate_is_required_when_handoff_declares_qa(self):
        n = normalize_store_product_handoff(self.payload)
        self.assertIn("qa.local_final_pass", n["missing_for_draft"])

    def test_exact_receipt_advances_only_local_qa_gate(self):
        n = apply_local_final_qa_receipt(self.payload, self.receipt)
        self.assertTrue(n["qa"]["local_final_pass"])
        self.assertNotIn("qa.local_final_pass", n["missing_for_draft"])
        self.assertFalse(n["approvals"]["owner_approved_for_draft"])
        self.assertFalse(n["security"]["owner_confirmation_complete"])

    def test_wrong_package_or_rebuild_is_rejected(self):
        bad = dict(self.receipt)
        bad["package_sha256"] = "0" * 64
        with self.assertRaises(StoreHandoffError):
            apply_local_final_qa_receipt(self.payload, bad)
        bad = dict(self.receipt)
        bad["package_rebuilt"] = True
        with self.assertRaises(StoreHandoffError):
            apply_local_final_qa_receipt(self.payload, bad)

    def test_security_bypass_is_rejected(self):
        bad = dict(self.receipt)
        bad["security_bypass_used"] = True
        with self.assertRaises(StoreHandoffError):
            apply_local_final_qa_receipt(self.payload, bad)

    def test_duplicate_full_local_suite_contract_is_rejected(self):
        bad = dict(self.receipt)
        bad["local_full_test_suite_required"] = True
        with self.assertRaisesRegex(StoreHandoffError, "duplicating the full GitHub CI"):
            apply_local_final_qa_receipt(self.payload, bad)

    def test_github_primary_metadata_is_validated_when_present(self):
        good = dict(self.receipt)
        good["github_ci_is_primary"] = True
        good["local_full_test_suite_required"] = False
        good["test_source"] = "github_exact_head_ci"
        n = apply_local_final_qa_receipt(self.payload, good)
        self.assertTrue(n["qa"]["local_final_pass"])

        bad = dict(good)
        bad["github_ci_is_primary"] = False
        with self.assertRaisesRegex(StoreHandoffError, "GitHub CI as primary"):
            apply_local_final_qa_receipt(self.payload, bad)

    def test_application_control_block_opens_only_private_store_signing_lane(self):
        receipt = {
            "schema_version": "pre-store-static-qa-receipt/1",
            "status": "APPLICATION_CONTROL_BLOCKED",
            "store_id": self.payload["identity"]["store_id"],
            "source_sha": self.payload["product"]["source_sha"],
            "package_sha256": self.payload["package"]["package_sha256"],
            "tests_passed": True,
            "package_sha_verified": True,
            "unpacked_exe_sha_verified": True,
            "manifest_identity_verified": True,
            "application_control_blocked": True,
            "package_rebuilt": False,
            "security_bypass_used": False,
            "security_policy_modified": False,
            "certificate_store_modified": False,
            "alternate_bypass_used": False,
        }
        n = apply_pre_store_static_qa_receipt(self.payload, receipt)
        self.assertTrue(n["qa"]["pre_store_static_pass"])
        self.assertEqual(
            "APPLICATION_CONTROL_BLOCKED",
            n["qa"]["unsigned_gui_execution_status"],
        )
        self.assertTrue(n["qa"]["private_store_signing_lane_ready"])
        self.assertFalse(n["qa"]["local_final_pass"])
        self.assertFalse(n["qa"]["store_signed_install_pass"])
        self.assertNotIn("qa.local_final_pass", n["missing_for_draft"])

        public = json.loads(json.dumps(n))
        public["distribution"]["audience"] = "PUBLIC_RELEASE"
        public["distribution"]["public_release_approved"] = True
        public_n = normalize_store_product_handoff(public)
        self.assertIn("qa.store_signed_install_pass", public_n["missing_for_draft"])

    def test_store_signed_receipt_unlocks_public_qa_gate_only(self):
        self.payload["distribution"]["audience"] = "PUBLIC_RELEASE"
        self.payload["distribution"]["public_release_approved"] = True
        receipt = {
            "schema_version": "store-signed-install-qa-receipt/1",
            "status": "PASS",
            "store_id": self.payload["identity"]["store_id"],
            "source_sha": self.payload["product"]["source_sha"],
            "original_package_sha256": self.payload["package"]["package_sha256"],
            "identity_name": self.payload["identity"]["name"],
            "version": self.payload["identity"]["version"],
            "architecture": self.payload["identity"]["architecture"],
            "acquisition_method": "PROMO_CODE",
            "acquisition_cost_paid": False,
            "microsoft_store_delivery_verified": True,
            "signature_trust_verified": True,
            "jp_en_gui_passed": True,
            "dpi_matrix_passed": True,
            "product_specific_acceptance_passed": True,
            "normal_exit_passed": True,
            "package_rebuilt": False,
            "security_bypass_used": False,
            "product_specific_checks": ["signed-store-install"],
        }
        n = apply_store_signed_install_qa_receipt(self.payload, receipt)
        self.assertTrue(n["qa"]["store_signed_install_pass"])
        self.assertNotIn("qa.store_signed_install_pass", n["missing_for_draft"])
        self.assertFalse(n["approvals"]["owner_approved_for_draft"])
        self.assertFalse(n["security"]["owner_confirmation_complete"])
        self.assertEqual("PROMO_CODE", n["qa"]["store_signed_acquisition_method"])
        self.assertFalse(n["qa"]["store_signed_acquisition_cost_paid"])

    def test_store_signed_receipt_rejects_paid_acquisition(self):
        self.payload["distribution"]["audience"] = "PUBLIC_RELEASE"
        self.payload["distribution"]["public_release_approved"] = True
        receipt = {
            "schema_version": "store-signed-install-qa-receipt/1",
            "status": "PASS",
            "store_id": self.payload["identity"]["store_id"],
            "source_sha": self.payload["product"]["source_sha"],
            "original_package_sha256": self.payload["package"]["package_sha256"],
            "identity_name": self.payload["identity"]["name"],
            "version": self.payload["identity"]["version"],
            "architecture": self.payload["identity"]["architecture"],
            "acquisition_method": "PROMO_CODE",
            "acquisition_cost_paid": True,
            "microsoft_store_delivery_verified": True,
            "signature_trust_verified": True,
            "jp_en_gui_passed": True,
            "dpi_matrix_passed": True,
            "product_specific_acceptance_passed": True,
            "normal_exit_passed": True,
            "package_rebuilt": False,
            "security_bypass_used": False,
        }
        with self.assertRaises(StoreHandoffError):
            apply_store_signed_install_qa_receipt(self.payload, receipt)

    def test_documented_store_handoff_scripts_run_directly(self):
        root = Path(__file__).resolve().parents[1]
        scripts = (
            "create_local_final_qa_receipt_template.py",
            "apply_local_final_qa_receipt.py",
            "prepare_store_automator_input.py",
            "apply_identity_reverify_receipt.py",
            "apply_initial_submission_receipt.py",
            "apply_pre_store_static_qa_receipt.py",
            "apply_store_signed_install_qa_receipt.py",
            "apply_unsigned_exe_launch_receipt.py",
            "reconcile_delayed_code_integrity_launch.py",
            "create_code_integrity_block_evidence.py",
            "reconcile_delayed_code_integrity_launch.py",
            "create_pre_store_static_block_receipt.py",
        )
        for name in scripts:
            with self.subTest(script=name):
                result = subprocess.run(
                    [sys.executable, str(root / "scripts" / name), "--help"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
