from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from all_auto.unsigned_exe_launch import (
    UnsignedExeLaunchReceiptError,
    bind_unsigned_launch_to_local_qa,
    reconcile_delayed_application_control_evidence,
    validate_unsigned_exe_launch_receipt,
    validate_unsigned_exe_launch_reconciliation_receipt,
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

    def test_delayed_code_integrity_reconciliation_preserves_original_and_blocks(self):
        launch = base_receipt("LAUNCH_FAILED")
        evidence = {
            "schema_version": "code-integrity-block-evidence/1",
            "exe_sha256": SHA,
            "launch_attempts": 1,
            "process_started": False,
            "event_ids": [3033, 3077, 3118],
            "policy_name": "VerifiedAndReputableDesktop",
            "policy_guid": "{0283ac0f-fff1-49ae-ada1-8a933130cad6}",
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
        reconciled = reconcile_delayed_application_control_evidence(
            launch,
            evidence,
            expected_exe_sha256=SHA,
        )
        self.assertEqual(
            reconciled["schema_version"],
            "unsigned-exe-launch-reconciliation-receipt/1",
        )
        self.assertEqual(reconciled["status"], "APPLICATION_CONTROL_BLOCKED")
        self.assertEqual(reconciled["original_launch_status"], "LAUNCH_FAILED")
        self.assertEqual(reconciled["blocking_event_ids"], [3033, 3077])
        self.assertTrue(reconciled["original_receipt_preserved"])
        self.assertFalse(reconciled["second_launch_performed"])
        self.assertFalse(reconciled["local_final_qa_pass"])
        self.assertFalse(reconciled["store_actions_authorized"])

        validated = validate_unsigned_exe_launch_reconciliation_receipt(
            reconciled,
            expected_exe_sha256=SHA,
        )
        self.assertEqual(validated["status"], "APPLICATION_CONTROL_BLOCKED")

    def test_delayed_code_integrity_reconciliation_rejects_wrong_or_nonblocking_evidence(self):
        launch = base_receipt("LAUNCH_FAILED")
        evidence = {
            "schema_version": "code-integrity-block-evidence/1",
            "exe_sha256": "1" * 64,
            "launch_attempts": 1,
            "process_started": False,
            "event_ids": [3033],
            "policy_name": "VerifiedAndReputableDesktop",
            "policy_guid": "{0283ac0f-fff1-49ae-ada1-8a933130cad6}",
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
        with self.assertRaisesRegex(UnsignedExeLaunchReceiptError, "SHA256 mismatch"):
            reconcile_delayed_application_control_evidence(
                launch,
                evidence,
                expected_exe_sha256=SHA,
            )

        evidence["exe_sha256"] = SHA
        evidence["event_ids"] = [3118]
        with self.assertRaisesRegex(UnsignedExeLaunchReceiptError, "3033/3077"):
            reconcile_delayed_application_control_evidence(
                launch,
                evidence,
                expected_exe_sha256=SHA,
            )

    def test_reconciled_block_evidence_binds_but_never_unlocks_full_qa(self):
        qa = {
            "schema_version": "local-final-qa-receipt/1",
            "status": "HOLD",
            "product_specific_acceptance_passed": False,
            "normal_exit_passed": False,
            "package_rebuilt": False,
            "security_bypass_used": False,
        }
        launch = base_receipt("LAUNCH_FAILED")
        evidence = {
            "schema_version": "code-integrity-block-evidence/1",
            "exe_sha256": SHA,
            "launch_attempts": 1,
            "process_started": False,
            "event_ids": [3033, 3077],
            "policy_name": "VerifiedAndReputableDesktop",
            "policy_guid": "{0283ac0f-fff1-49ae-ada1-8a933130cad6}",
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
        reconciled = reconcile_delayed_application_control_evidence(
            launch,
            evidence,
            expected_exe_sha256=SHA,
        )
        bound = bind_unsigned_launch_to_local_qa(
            qa,
            reconciled,
            expected_exe_sha256=SHA,
        )
        self.assertEqual(bound["status"], "HOLD")
        self.assertFalse(bound["product_specific_acceptance_passed"])
        self.assertFalse(bound["normal_exit_passed"])
        self.assertEqual(
            bound["unsigned_exe_launch"]["status"],
            "APPLICATION_CONTROL_BLOCKED",
        )

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


class DelayedCodeIntegrityReconciliationTests(unittest.TestCase):
    def _evidence(self) -> dict:
        return {
            "schema_version": "code-integrity-block-evidence/1",
            "status": "APPLICATION_CONTROL_BLOCKED",
            "exe_sha256": SHA,
            "event_ids": [3033, 3077, 3118],
            "blocking_event_ids": [3033, 3077],
            "supplemental_event_ids": [3118],
            "policy_name": "VerifiedAndReputableDesktop",
            "policy_guid": "{0283ac0f-fff1-49ae-ada1-8a933130cad6}",
            "launch_attempts": 1,
            "process_started": False,
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

    def test_delayed_block_reconciles_immutable_launch_failed_receipt(self):
        launch = base_receipt("LAUNCH_FAILED")
        result = reconcile_delayed_application_control_evidence(
            launch,
            self._evidence(),
            expected_exe_sha256=SHA,
        )
        self.assertEqual(result["status"], "APPLICATION_CONTROL_BLOCKED")
        self.assertEqual(result["original_launch_status"], "LAUNCH_FAILED")
        self.assertTrue(result["original_receipt_preserved"])
        self.assertFalse(result["second_launch_performed"])
        self.assertEqual(result["blocking_event_ids"], [3033, 3077])
        self.assertIn(3118, result["all_observed_event_ids"])
        self.assertFalse(result["local_final_qa_pass"])
        self.assertFalse(result["store_actions_authorized"])

        validated = validate_unsigned_exe_launch_reconciliation_receipt(
            result,
            expected_exe_sha256=SHA,
        )
        self.assertEqual(validated["policy_name"], "VerifiedAndReputableDesktop")

        qa = {
            "schema_version": "local-final-qa-receipt/1",
            "status": "HOLD",
            "product_specific_acceptance_passed": False,
            "normal_exit_passed": False,
            "package_rebuilt": False,
            "security_bypass_used": False,
        }
        bound = bind_unsigned_launch_to_local_qa(
            qa,
            result,
            expected_exe_sha256=SHA,
        )
        self.assertEqual(bound["status"], "HOLD")
        self.assertFalse(bound["normal_exit_passed"])
        self.assertEqual(
            bound["unsigned_exe_launch"]["status"],
            "APPLICATION_CONTROL_BLOCKED",
        )

    def test_reconciliation_requires_block_class_event_and_same_exe(self):
        launch = base_receipt("LAUNCH_FAILED")
        evidence = self._evidence()
        evidence["event_ids"] = [3118]
        with self.assertRaisesRegex(UnsignedExeLaunchReceiptError, "3033/3077"):
            reconcile_delayed_application_control_evidence(
                launch,
                evidence,
                expected_exe_sha256=SHA,
            )

        evidence = self._evidence()
        evidence["exe_sha256"] = "1" * 64
        with self.assertRaisesRegex(UnsignedExeLaunchReceiptError, "mismatch"):
            reconcile_delayed_application_control_evidence(
                launch,
                evidence,
                expected_exe_sha256=SHA,
            )

    def test_reconciliation_rejects_second_launch_or_security_change(self):
        launch = base_receipt("LAUNCH_FAILED")
        evidence = self._evidence()
        evidence["launch_attempts"] = 2
        with self.assertRaisesRegex(UnsignedExeLaunchReceiptError, "exactly one"):
            reconcile_delayed_application_control_evidence(
                launch,
                evidence,
                expected_exe_sha256=SHA,
            )

        evidence = self._evidence()
        evidence["security_policy_modified"] = True
        with self.assertRaisesRegex(UnsignedExeLaunchReceiptError, "unsafe"):
            reconcile_delayed_application_control_evidence(
                launch,
                evidence,
                expected_exe_sha256=SHA,
            )


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
            "for ($pollAttempt = 1; $pollAttempt -le 6; $pollAttempt++)",
            "code_integrity_query_attempts",
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
