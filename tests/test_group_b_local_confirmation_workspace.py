from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "prepare_group_b_local_confirmation",
    ROOT / "scripts" / "prepare_group_b_local_confirmation.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def artifact_receipt() -> dict:
    return {
        "schema_version": "local-store-product-artifact-pull-receipt/1",
        "status": "LOCAL_STORE_PRODUCT_ARTIFACT_VERIFIED",
        "product_id": "scheduled-api-runner",
        "product_name": "Scheduled API Runner",
        "repository_full_name": "shihuiarenjinba-png/scheduled-api-runner",
        "workflow_name": "Windows desktop / Windowsデスクトップ",
        "workflow_head_sha": "a" * 40,
        "artifact_run_id": 123,
        "artifact_name": "ScheduledApiRunner-Store-MSIX-UNSIGNED-DRAFT",
        "source_sha": "a" * 40,
        "store_id": "9PND0HG61XD6",
        "identity": {
            "name": "OkinawaDesktopTools.ScheduledAPIRunner",
            "publisher": "CN=ABC",
            "version": "1.0.0.0",
            "architecture": "x64",
        },
        "package": {
            "file_name": "ScheduledApiRunner.msix",
            "sha256": "b" * 64,
            "bytes": 100,
        },
        "local_package_path": "C:/qa/package.msix",
        "local_handoff_path": "C:/qa/store-product-handoff.json",
        "central_registry_binding_verified": True,
        "package_rebuilt": False,
        "security_bypass_used": False,
        "package_installed": False,
        "submitted_to_store": False,
        "certification_submitted": False,
        "published": False,
    }


def qa_template() -> dict:
    return {
        "schema_version": "local-final-qa-receipt/1",
        "status": "HOLD",
        "github_ci_is_primary": True,
        "local_full_test_suite_required": False,
        "test_source": "github_exact_head_ci",
        "product_specific_checks": [
            "authorized non-production HTTPS GET",
            "Windows Task Scheduler lifecycle",
        ],
    }


class GroupBLocalConfirmationWorkspaceTests(unittest.TestCase):
    def test_manifest_is_local_only_and_preserves_github_primary(self):
        manifest = MODULE.build_workspace_manifest(
            artifact_receipt(),
            qa_template(),
            product_id="scheduled-api-runner",
            artifact_receipt_path=Path("artifact.json"),
            qa_template_path=Path("qa.json"),
        )
        self.assertEqual(
            manifest["status"], "READY_FOR_LOCAL_WINDOWS_CONFIRMATION"
        )
        self.assertTrue(manifest["github_ci_is_primary"])
        self.assertFalse(manifest["local_full_test_suite_required"])
        self.assertEqual(
            manifest["store_actions"],
            {
                "package_upload": "NOT_EXECUTED",
                "certification": "NOT_EXECUTED",
                "publish": "NOT_EXECUTED",
            },
        )
        self.assertIn(
            "Windows Task Scheduler lifecycle",
            manifest["local_only_checks"],
        )

    def test_manifest_rejects_store_action_or_registry_mismatch(self):
        bad = artifact_receipt()
        bad["submitted_to_store"] = True
        with self.assertRaisesRegex(MODULE.LocalConfirmationError, "unsafe"):
            MODULE.build_workspace_manifest(
                bad,
                qa_template(),
                product_id="scheduled-api-runner",
                artifact_receipt_path=Path("artifact.json"),
                qa_template_path=Path("qa.json"),
            )

        bad = artifact_receipt()
        bad["central_registry_binding_verified"] = False
        with self.assertRaisesRegex(MODULE.LocalConfirmationError, "central registry"):
            MODULE.build_workspace_manifest(
                bad,
                qa_template(),
                product_id="scheduled-api-runner",
                artifact_receipt_path=Path("artifact.json"),
                qa_template_path=Path("qa.json"),
            )

    def test_manifest_rejects_duplicate_full_local_test_requirement(self):
        bad_qa = qa_template()
        bad_qa["local_full_test_suite_required"] = True
        with self.assertRaisesRegex(MODULE.LocalConfirmationError, "full test suite"):
            MODULE.build_workspace_manifest(
                artifact_receipt(),
                bad_qa,
                product_id="scheduled-api-runner",
                artifact_receipt_path=Path("artifact.json"),
                qa_template_path=Path("qa.json"),
            )

    def test_script_contains_no_partner_center_write_command(self):
        text = (
            ROOT / "scripts" / "prepare_group_b_local_confirmation.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "submit certification",
            "publish_approved",
            "confirm-live-draft",
            "upload-package",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
