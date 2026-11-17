from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from all_auto.unsigned_exe_launch import (
    UnsignedExeLaunchReceiptError,
    bind_unsigned_launch_to_local_qa,
    validate_unsigned_exe_launch_receipt,
)


SHA = "0" * 64


def base_receipt(status: str) -> dict:
    receipt = {
        "schema_version": "unsigned-exe-launch-receipt/1",
        "status": status,
        "expected_exe_sha256": SHA,
        "actual_exe_sha256": SHA,
        "normal_user_context": True,
        "elevated": False,
        "launch_attempts": 1,
        "process_started": False,
        "exit_code": None,
        "normal_exit": False,
        "code_integrity_event_ids": [],
        "package_rebuilt": False,
        "security_bypass_used": False,
        "security_policy_modified": False,
        "certificate_store_modified": False,
        "alternate_bypass_used": False,
        "msix_installed": False,
        "partner_center_write_performed": False,
        "package_uploaded": False,
        "certification_submitted": False,
        "published": False,
    }
    return receipt


class UnsignedExeLaunchReceiptTests(unittest.TestCase):
    def test_pass_requires_one_clean_normal_exit(self):
        receipt = base_receipt("PASS_NORMAL_EXIT")
        receipt.update(process_started=True, normal_exit=True, exit_code=0)
        n = validate_unsigned_exe_launch_receipt(receipt, expected_exe_sha256=SHA)
        self.assertTrue(n["validated"])
        self.assertFalse(n["local_final_qa_pass"])
        self.assertFalse(n["store_actions_authorized"])

    def test_application_control_block_requires_event_evidence(self):
        receipt = base_receipt("APPLICATION_CONTROL_BLOCKED")
        with self.assertRaisesRegex(UnsignedExeLaunchReceiptError, "Code Integrity"):
            validate_unsigned_exe_launch_receipt(receipt, expected_exe_sha256=SHA)
        receipt["code_integrity_event_ids"] = [3077]
        n = validate_unsigned_exe_launch_receipt(receipt, expected_exe_sha256=SHA)
        self.assertEqual(n["status"], "APPLICATION_CONTROL_BLOCKED")

    def test_unsafe_flags_or_second_attempt_are_rejected(self):
        receipt = base_receipt("LAUNCH_FAILED")
        receipt["security_bypass_used"] = True
        with self.assertRaisesRegex(UnsignedExeLaunchReceiptError, "unsafe"):
            validate_unsigned_exe_launch_receipt(receipt, expected_exe_sha256=SHA)

        receipt = base_receipt("LAUNCH_FAILED")
        receipt["launch_attempts"] = 2
        with self.assertRaisesRegex(UnsignedExeLaunchReceiptError, "exactly 1"):
            validate_unsigned_exe_launch_receipt(receipt, expected_exe_sha256=SHA)

    def test_bind_never_unlocks_full_local_qa(self):
        qa = {
            "schema_version": "local-final-qa-receipt/1",
            "status": "HOLD",
            "product_specific_acceptance_passed": False,
            "normal_exit_passed": False,
            "package_rebuilt": False,
            "security_bypass_used": False,
        }
        receipt = base_receipt("PASS_NORMAL_EXIT")
        receipt.update(process_started=True, normal_exit=True, exit_code=0)
        bound = bind_unsigned_launch_to_local_qa(
            qa, receipt, expected_exe_sha256=SHA
        )
        self.assertEqual(bound["status"], "HOLD")
        self.assertFalse(bound["product_specific_acceptance_passed"])
        self.assertTrue(bound["normal_exit_passed"])


class UnsignedLaunchPowerShellContractTests(unittest.TestCase):
    def test_script_is_one_shot_normal_user_and_contains_no_bypass(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "scripts" / "run_unsigned_exact_exe_smoke.ps1").read_text(
            encoding="utf-8"
        )
        for required in (
            "launch_attempts = 1",
            "Get-FileHash",
            "WindowsBuiltInRole]::Administrator",
            "APPLICATION_CONTROL_BLOCKED",
            "Microsoft-Windows-CodeIntegrity/Operational",
            "3033",
            "3077",
            "security_bypass_used = $false",
            "msix_installed = $false",
            "partner_center_write_performed = $false",
        ):
            self.assertIn(required, text)
        for forbidden in (
            "-Verb RunAs",
            "Add-AppxPackage",
            "Set-MpPreference",
            "certutil",
            "New-SelfSignedCertificate",
            "bcdedit",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
