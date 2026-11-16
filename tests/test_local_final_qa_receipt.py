import json
import unittest
from pathlib import Path

from all_auto.store_product_handoff import (
    StoreHandoffError,
    apply_local_final_qa_receipt,
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


if __name__ == "__main__":
    unittest.main()
