from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from all_auto.pre_store_static_block import (
    PreStoreStaticBlockError,
    build_pre_store_static_block_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "folder_engine_paid_trial_handoff_v2.json"


def handoff() -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["product"]["id"] = "scheduled-api-runner"
    payload["product"]["name"] = "Scheduled API Runner"
    payload["product"]["source_sha"] = "a" * 40
    payload["identity"]["store_id"] = "9PND0HG61XD6"
    payload["identity"]["name"] = "OkinawaDesktopTools.ScheduledAPIRunner"
    payload["package"]["package_sha256"] = "b" * 64
    payload["package"]["exe_sha256"] = "c" * 64
    payload["security"]["package_sha256"] = "b" * 64
    return payload


def artifact_receipt() -> dict:
    return {
        "schema_version": "local-store-product-artifact-pull-receipt/1",
        "status": "LOCAL_STORE_PRODUCT_ARTIFACT_VERIFIED",
        "store_id": "9PND0HG61XD6",
        "source_sha": "a" * 40,
        "package": {"sha256": "b" * 64},
        "artifact_run_id": 123,
        "artifact_name": "ScheduledApiRunner-Store-MSIX-UNSIGNED-DRAFT",
        "github_artifact_id": 456,
        "github_artifact_digest": "sha256:" + "d" * 64,
        "package_rebuilt": False,
        "security_bypass_used": False,
        "package_installed": False,
        "submitted_to_store": False,
        "certification_submitted": False,
        "published": False,
    }


def reconciled_launch() -> dict:
    return {
        "schema_version": "unsigned-exe-launch-reconciliation-receipt/1",
        "status": "APPLICATION_CONTROL_BLOCKED",
        "original_launch_status": "LAUNCH_FAILED",
        "expected_exe_sha256": "c" * 64,
        "actual_exe_sha256": "c" * 64,
        "launch_attempts": 1,
        "process_started": False,
        "normal_exit": False,
        "exit_code": None,
        "blocking_event_ids": [3033, 3077],
        "all_observed_event_ids": [3033, 3077, 3118],
        "policy_name": "VerifiedAndReputableDesktop",
        "policy_guid": "{0283ac0f-fff1-49ae-ada1-8a933130cad6}",
        "correlation_activity_id": "{2f3574e4-74dd-0008-cd37-9c3add74dd01}",
        "policy_id": "27555.1000.240208",
        "status_code": "0xc0e90002",
        "event_flat_hash": "c" * 64,
        "event_flat_hash_matches_exe_sha256": True,
        "original_receipt_preserved": True,
        "second_launch_performed": False,
        "security_bypass_used": False,
        "security_policy_modified": False,
        "certificate_store_modified": False,
        "alternate_bypass_used": False,
        "msix_installed": False,
        "partner_center_write_performed": False,
        "package_uploaded": False,
        "certification_submitted": False,
        "published": False,
        "local_final_qa_pass": False,
        "store_actions_authorized": False,
    }


class PreStoreStaticBlockReceiptTests(unittest.TestCase):
    def test_builds_limited_private_signing_lane_receipt(self):
        result = build_pre_store_static_block_receipt(
            handoff(),
            artifact_receipt(),
            reconciled_launch(),
        )
        self.assertEqual(result["schema_version"], "pre-store-static-qa-receipt/1")
        self.assertEqual(result["status"], "APPLICATION_CONTROL_BLOCKED")
        self.assertTrue(result["tests_passed"])
        self.assertTrue(result["package_sha_verified"])
        self.assertTrue(result["unpacked_exe_sha_verified"])
        self.assertTrue(result["manifest_identity_verified"])
        self.assertTrue(result["application_control_blocked"])
        self.assertFalse(result["package_rebuilt"])
        self.assertFalse(result["security_bypass_used"])
        self.assertEqual(result["blocking_event_ids"], [3033, 3077])
        self.assertEqual(result["policy_name"], "VerifiedAndReputableDesktop")
        self.assertEqual(
            result["correlation_activity_id"],
            "{2f3574e4-74dd-0008-cd37-9c3add74dd01}",
        )
        self.assertEqual(result["policy_id"], "27555.1000.240208")
        self.assertEqual(result["status_code"], "0xc0e90002")
        self.assertEqual(result["event_flat_hash"], "c" * 64)
        self.assertTrue(result["event_flat_hash_matches_exe_sha256"])

    def test_rejects_wrong_package_or_unsafe_artifact(self):
        bad = artifact_receipt()
        bad["package"] = {"sha256": "0" * 64}
        with self.assertRaisesRegex(PreStoreStaticBlockError, "package SHA mismatch"):
            build_pre_store_static_block_receipt(
                handoff(), bad, reconciled_launch()
            )

        bad = artifact_receipt()
        bad["security_bypass_used"] = True
        with self.assertRaisesRegex(PreStoreStaticBlockError, "unsafe"):
            build_pre_store_static_block_receipt(
                handoff(), bad, reconciled_launch()
            )

    def test_rejects_non_block_reconciliation(self):
        bad = reconciled_launch()
        bad["status"] = "LAUNCH_FAILED"
        with self.assertRaises(PreStoreStaticBlockError):
            build_pre_store_static_block_receipt(
                handoff(), artifact_receipt(), bad
            )


class FinalizeApplicationControlBlockLaneTests(unittest.TestCase):
    def test_cli_atomically_builds_reconciliation_static_receipt_and_bound_handoff(self):
        launch = {
            "schema_version": "unsigned-exe-launch-receipt/1",
            "status": "LAUNCH_FAILED",
            "expected_exe_sha256": "c" * 64,
            "actual_exe_sha256": "c" * 64,
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
        evidence = {
            "schema_version": "code-integrity-block-evidence/1",
            "status": "APPLICATION_CONTROL_BLOCKED",
            "exe_sha256": "c" * 64,
            "event_ids": [3033, 3077, 3118],
            "blocking_event_ids": [3033, 3077],
            "supplemental_event_ids": [3118],
            "policy_name": "VerifiedAndReputableDesktop",
            "policy_guid": "{0283ac0f-fff1-49ae-ada1-8a933130cad6}",
            "correlation_activity_id": "{2f3574e4-74dd-0008-cd37-9c3add74dd01}",
            "policy_id": "27555.1000.240208",
            "status_code": "0xc0e90002",
            "event_flat_hash": "c" * 64,
            "event_flat_hash_matches_exe_sha256": True,
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
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            handoff_path = root / "handoff.json"
            artifact_path = root / "artifact.json"
            launch_path = root / "launch.json"
            evidence_path = root / "ci.json"
            output_dir = root / "finalized"
            handoff_path.write_text(json.dumps(handoff()), encoding="utf-8")
            artifact_path.write_text(json.dumps(artifact_receipt()), encoding="utf-8")
            launch_path.write_text(json.dumps(launch), encoding="utf-8")
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "finalize_application_control_block_lane.py"),
                    "--handoff",
                    str(handoff_path),
                    "--artifact-receipt",
                    str(artifact_path),
                    "--launch-receipt",
                    str(launch_path),
                    "--code-integrity-evidence",
                    str(evidence_path),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(
                (output_dir / "unsigned-exe-launch-reconciliation-receipt.json").is_file()
            )
            self.assertTrue((output_dir / "pre-store-static-qa-receipt.json").is_file())
            bound_path = output_dir / "handoff-after-pre-store-static-block.json"
            self.assertTrue(bound_path.is_file())
            bound = json.loads(bound_path.read_text(encoding="utf-8"))
            self.assertTrue(bound["qa"]["pre_store_static_pass"])
            self.assertTrue(bound["qa"]["private_store_signing_lane_ready"])
            self.assertFalse(bound["qa"]["local_final_pass"])
            self.assertFalse(bound["qa"]["store_signed_install_pass"])
            reconciled = json.loads(
                (
                    output_dir
                    / "unsigned-exe-launch-reconciliation-receipt.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(
                reconciled["correlation_activity_id"],
                "{2f3574e4-74dd-0008-cd37-9c3add74dd01}",
            )
            self.assertEqual(reconciled["policy_id"], "27555.1000.240208")
            self.assertEqual(reconciled["status_code"], "0xc0e90002")
            self.assertEqual(reconciled["event_flat_hash"], "c" * 64)
            self.assertFalse((root / ".finalized.staging").exists())

    def test_cli_failure_removes_partial_staging(self):
        launch = {
            "schema_version": "unsigned-exe-launch-receipt/1",
            "status": "LAUNCH_FAILED",
            "expected_exe_sha256": "c" * 64,
            "actual_exe_sha256": "c" * 64,
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
        evidence = {
            "schema_version": "code-integrity-block-evidence/1",
            "status": "APPLICATION_CONTROL_BLOCKED",
            "exe_sha256": "0" * 64,
            "event_ids": [3033, 3077],
            "blocking_event_ids": [3033, 3077],
            "supplemental_event_ids": [],
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
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            handoff_path = root / "handoff.json"
            artifact_path = root / "artifact.json"
            launch_path = root / "launch.json"
            evidence_path = root / "ci.json"
            output_dir = root / "finalized"
            handoff_path.write_text(json.dumps(handoff()), encoding="utf-8")
            artifact_path.write_text(json.dumps(artifact_receipt()), encoding="utf-8")
            launch_path.write_text(json.dumps(launch), encoding="utf-8")
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "finalize_application_control_block_lane.py"),
                    "--handoff",
                    str(handoff_path),
                    "--artifact-receipt",
                    str(artifact_path),
                    "--launch-receipt",
                    str(launch_path),
                    "--code-integrity-evidence",
                    str(evidence_path),
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(output_dir.exists())
            self.assertFalse((root / ".finalized.staging").exists())


if __name__ == "__main__":
    unittest.main()
