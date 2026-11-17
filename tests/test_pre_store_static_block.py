from __future__ import annotations

import json
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
