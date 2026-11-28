from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from all_auto.package_candidates import (
    load_candidate_source_gui_receipt,
    load_candidate_installed_msix_qa_receipt,
    load_package_candidate,
    runtime_package_binding,
)
from all_auto.runtime_qa import build_runtime_qa_report
from all_auto.store_workflow import StoreWorkflowError

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT / "uploader" / "config"
PROFILE_ROOT = CONFIG_ROOT / "runtime_qa_profiles"
FORMAL_SHA = "e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05"
CANDIDATE_SHA = "5e21356f6e589cc1075099887b44b63a69d7f6b44742d39a43c6f256ab5a361a"
SOURCE_SHA = "4ae2574982adf0cfd5aabc31f55f27b555283904"
DRIVER_SHA = "e54ee38d42dd6f38f95119afbf50522d972821c2247628e71b0e9c36a6630782"


def candidate_record(relative_path: str) -> dict:
    return {
        "candidate_id": "dca-provisional-1.0.1.0-4ae2574",
        "product_id": "9PDL4ZWSB45P", "submission_id": "1152921505702212222",
        "artifact_id": "15267053130", "actions_run_id": "46154390667",
        "repository": "shihuiarenjinba-png/csv-import-validator",
        "source_commit": SOURCE_SHA, "gui_qa_source_commit": SOURCE_SHA,
        "source_gui_driver_sha256": DRIVER_SHA,
        "source_gui_receipt_relative_path": relative_path,
        "filename": "DataContractSchemaDrift_1.0.1.0_x64.msix",
        "version": "1.0.1.0", "sha256": CANDIDATE_SHA,
        "identity_name": "OkinawaDesktopTools.DataContractAuditor",
        "publisher": "CN=46263F21-A700-41DB-8C9B-114C22FB82FC",
        "architecture": "x64", "application_id": "DataContractSchemaDrift",
        "target_device_families": ["Windows.Desktop"],
        "archive_relative_path": "candidate/package.msix",
        "candidate_status": "PROVISIONAL_NOT_OWNER_APPROVED",
        "owner_version_approval": False, "upload_approved": False,
        "certification_authorized": False, "publish_authorized": False,
        "installed_msix_functional_qa": "NOT_RUN",
    }


class PackageCandidateTests(unittest.TestCase):
    def test_candidate_does_not_mutate_formal_package_config_or_qa_profile(self):
        candidate = candidate_record("source.json")
        before = json.loads((PROFILE_ROOT / "data-contract-auditor.json").read_text(encoding="utf-8"))
        report = build_runtime_qa_report(
            product="data-contract-auditor", config_root=CONFIG_ROOT,
            profile_root=PROFILE_ROOT, package=None,
            package_binding_override=runtime_package_binding(candidate), candidate_metadata=candidate)
        after = json.loads((PROFILE_ROOT / "data-contract-auditor.json").read_text(encoding="utf-8"))
        config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
        self.assertEqual(before, after)
        self.assertEqual(config["expected_sha256"], FORMAL_SHA)
        self.assertEqual(report["candidate"]["sha256"], CANDIDATE_SHA)
        self.assertTrue(report["formal_package_reference_unchanged"])
        self.assertFalse(report["qa_pass"])

    def test_candidate_product_submission_and_false_approval_boundaries_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "registry"
            archive = root / "archive"
            registry.mkdir()
            package = archive / "candidate" / "package.msix"
            package.parent.mkdir(parents=True)
            package.write_bytes(b"candidate bytes")
            record = candidate_record("source.json")
            (registry / "data-contract-auditor.json").write_text(json.dumps({
                "schema_version": "all-auto-package-candidates/1",
                "product_key": "data-contract-auditor", "candidates": [record]}, indent=2), encoding="utf-8")
            config = {"product_id": "9PDL4ZWSB45P", "submission_id": "1152921505702212222"}
            with patch("all_auto.package_candidates._load_job", return_value=(config, Path("job.json"))):
                loaded, path = load_package_candidate(product="data-contract-auditor",
                    candidate_id=record["candidate_id"], config_root=Path("unused"),
                    registry_root=registry, archive_root=archive)
            self.assertEqual(loaded["sha256"], CANDIDATE_SHA)
            self.assertEqual(path, package.resolve())
            record["upload_approved"] = True
            (registry / "data-contract-auditor.json").write_text(json.dumps({
                "schema_version": "all-auto-package-candidates/1",
                "product_key": "data-contract-auditor", "candidates": [record]}), encoding="utf-8")
            with patch("all_auto.package_candidates._load_job", return_value=(config, Path("job.json"))):
                with self.assertRaisesRegex(StoreWorkflowError, "approval boundary"):
                    load_package_candidate(product="data-contract-auditor",
                        candidate_id=record["candidate_id"], config_root=Path("unused"),
                        registry_root=registry, archive_root=archive)

    def test_source_gui_receipt_is_bound_to_new_source_and_stays_nonpackaged_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt_path = root / "source.json"
            required = ["core_csv_drift", "csv_xlsx_compare", "invalid_input_rejected", "outputs_reopen",
                        "inputs_unchanged", "writable_default_output", "default_output_files_written",
                        "ui_language_and_scaling", "ui_compare_workflow", "ui_error_path", "close_relaunch"]
            receipt_path.write_text(json.dumps({
                "schema_version": "data-contract-local-real-device-qa/1",
                "product": "Data Contract Auditor", "source_sha": SOURCE_SHA,
                "driver_sha256": DRIVER_SHA, "execution_type": "SOURCE_GUI_DRIVER_SYNTHETIC_DATA",
                "source_worktree_clean": True, "status": "PASS",
                "checks": [{"name": name, "status": "PASS"} for name in required],
            }), encoding="utf-8")
            candidate = candidate_record("source.json")
            result = load_candidate_source_gui_receipt(candidate, root)
            self.assertEqual(result["status"], "SOURCE_GUI_DRIVER_PASS")
            self.assertFalse(result["packaged_runtime_proven"])
            self.assertFalse(result["visual_dpi_proven"])
            candidate["gui_qa_source_commit"] = "e27f7b9dc117bee65525d11024dccaf9615021bd"
            with self.assertRaisesRegex(StoreWorkflowError, "does not match"):
                load_candidate_source_gui_receipt(candidate, root)


    def _candidate_qa_receipt_fixture(self, root: Path):
        import hashlib
        evidence = root / "qa" / "run"
        screenshots = evidence / "screenshots"
        screenshots.mkdir(parents=True)
        image = screenshots / "main.png"
        image.write_bytes(b"verified-image")
        identity = {"Name": "OkinawaDesktopTools.DataContractAuditor",
                    "Publisher": "CN=46263F21-A700-41DB-8C9B-114C22FB82FC",
                    "Version": "1.0.1.0", "ProcessorArchitecture": "x64"}
        functional = {"schema_version": "dca-installed-msix-gui-qa/1", "product": "Data Contract Auditor",
            "execution_type": "INSTALLED_TEST_SIGNED_MSIX_GUI", "candidate_package_sha256": CANDIDATE_SHA,
            "status": "INSTALLED_PACKAGE_FUNCTIONAL_QA_PASS",
            "checks": [{"id": name, "status": "PASS"} for name in (
                "language_switch", "csv_compare_anomaly_detection", "xlsx_compare_anomaly_detection",
                "default_output_and_reopened_files", "invalid_csv_error", "normal_exit", "aumid_relaunch")],
            "screenshots": [{"artifact_path": "screenshots/main.png", "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}],
            "store_write_performed": False, "certification_executed": False, "publish_executed": False}
        derivative = {"schema_version": "all-auto-msix-test-signature-derivative/1",
            "status": "SIGNATURE_ONLY_DERIVATIVE_VERIFIED", "diagnostic_only": True,
            "source": {"sha256": CANDIDATE_SHA, "identity": identity},
            "derived": {"sha256": "a" * 64, "identity": identity},
            "changed_payload_members": [], "added_members": ["AppxMetadata/CodeIntegrity.cat", "AppxSignature.p7x"]}
        install = {"schema_version": "all-auto-msix-test-sign-install/2",
            "status": "TEST_SIGNED_DERIVATIVE_INSTALL_FUNCTIONAL_GUI_QA_PASS", "diagnostic_only": True,
            "install": "PASS", "launch": "PASS", "source_sha256": CANDIDATE_SHA,
            "derived_sha256": "a" * 64, "identity": identity["Name"], "publisher": identity["Publisher"],
            "version": identity["Version"], "architecture": identity["ProcessorArchitecture"]}
        candidate = candidate_record("source.json")
        records = ((functional, "qa/run/functional.json", "installed_msix_qa_receipt_relative_path", "installed_msix_qa_receipt_sha256"),
                   (derivative, "qa/run/derivative.json", "test_signature_derivative_receipt_relative_path", "test_signature_derivative_receipt_sha256"),
                   (install, "qa/run/install.json", "test_signature_install_receipt_relative_path", "test_signature_install_receipt_sha256"))
        for obj, rel, path_key, sha_key in records:
            raw = json.dumps(obj).encode("utf-8")
            path = root / rel
            path.write_bytes(raw)
            candidate[path_key] = rel
            candidate[sha_key] = hashlib.sha256(raw).hexdigest()
        return candidate, root / "qa/run/functional.json"

    def test_installed_candidate_qa_receipt_chain_and_screenshot_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, receipt_path = self._candidate_qa_receipt_fixture(root)
            result = load_candidate_installed_msix_qa_receipt(candidate, root)
            self.assertEqual(result["status"], "INSTALLED_TEST_SIGNED_DERIVATIVE_QA_PASS_PROVISIONAL")
            self.assertEqual(result["screenshot_count"], 1)
            self.assertFalse(result["formal_package_promoted"])
            self.assertFalse(result["store_write_performed"])
            candidate["installed_msix_qa_receipt_sha256"] = "0" * 64
            with self.assertRaisesRegex(StoreWorkflowError, "receipt hash differs"):
                load_candidate_installed_msix_qa_receipt(candidate, root)
            candidate["installed_msix_qa_receipt_sha256"] = __import__("hashlib").sha256(receipt_path.read_bytes()).hexdigest()
            shot = root / "qa/run/screenshots/main.png"
            shot.write_bytes(b"changed-image")
            with self.assertRaisesRegex(StoreWorkflowError, "screenshot hash mismatch"):
                load_candidate_installed_msix_qa_receipt(candidate, root)

    def test_installed_candidate_qa_rejects_package_mismatch_and_failed_check(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate, receipt_path = self._candidate_qa_receipt_fixture(root)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["candidate_package_sha256"] = "0" * 64
            raw = json.dumps(receipt).encode("utf-8")
            receipt_path.write_bytes(raw)
            candidate["installed_msix_qa_receipt_sha256"] = hashlib.sha256(raw).hexdigest()
            with self.assertRaisesRegex(StoreWorkflowError, "does not match the exact candidate"):
                load_candidate_installed_msix_qa_receipt(candidate, root)
            receipt["candidate_package_sha256"] = CANDIDATE_SHA
            receipt["checks"][0]["status"] = "FAIL"
            raw = json.dumps(receipt).encode("utf-8")
            receipt_path.write_bytes(raw)
            candidate["installed_msix_qa_receipt_sha256"] = hashlib.sha256(raw).hexdigest()
            with self.assertRaisesRegex(StoreWorkflowError, "does not match the exact candidate"):
                load_candidate_installed_msix_qa_receipt(candidate, root)


if __name__ == "__main__":
    unittest.main()
