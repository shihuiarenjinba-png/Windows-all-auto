from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from all_auto.store_run import run_approved_sections
from all_auto.store_workflow import DCA_BINDING, _sha256_path

CONFIG_ROOT = Path(__file__).resolve().parents[1] / "uploader" / "config"


def make_exact_test_package(path: Path) -> str:
    import zipfile
    manifest = '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="OkinawaDesktopTools.DataContractAuditor" Publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC" Version="1.0.0.0" ProcessorArchitecture="x64" /><Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.22621.0" /></Dependencies></Package>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AppxManifest.xml", manifest)
        archive.writestr("payload.bin", b"synthetic fixed-source package")
    return _sha256_path(path)


class StoreRunTests(unittest.TestCase):
    def _config(self, root: Path, package: Path, *, approved: bool) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
        config.update({**DCA_BINDING, "expected_sha256": make_exact_test_package(package),
                      "local_runtime_qa_status": "WINDOWS_REAL_DEVICE_QA_PASS_EXACT_PACKAGE" if approved else "SOURCE_QA_PASS_PACKAGED_EXE_RUNTIME_UNVERIFIED_INSTALL_ACCESS_DENIED_AND_TIMEOUT"})
        if approved:
            config["device_family_settings"] = {
                "status": "OWNER_APPROVED", "manifest_target_device_families": ["Windows.Desktop"],
                "approved_store_device_families": ["Windows 10/11 Desktop"],
                "approval": {"product_id": config["product_id"], "submission_id": config["submission_id"],
                             "approval_ref": "fixture-approval", "approved_by": "test-owner", "approved_at": "2026-11-28"}}
            config["execution_policy"] = {
                "status": "OWNER_APPROVED", "auto_execute_approved_sections": True,
                "approved_sections": ["packages"],
                "approval": {"product_id": config["product_id"], "submission_id": config["submission_id"],
                             "approval_ref": "fixture-run-approval", "approved_by": "test-owner", "approved_at": "2026-11-28"}}
        (root / "test-store-product.job.json").write_text(json.dumps(config), encoding="utf-8")
        return root

    def test_missing_persisted_execution_approval_is_plan_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "DataContractSchemaDrift_1.0.0.0_x64.msix"
            make_exact_test_package(package)
            config_root = self._config(root / "config", package, approved=False)
            result = run_approved_sections(product="test-store-product", config_root=config_root,
                                           package=package, ui_map_path=CONFIG_ROOT / "store_ui_maps" / "msix_pwa_app.v1.json",
                                           package_runner=lambda **_: self.fail("must not dispatch"))
            self.assertEqual(result["status"], "PLAN_ONLY")
            self.assertFalse(result["writes_performed"])
            self.assertFalse(result["certification_executed"])
            self.assertFalse(result["publish_executed"])

    def test_package_approval_still_holds_until_exact_runtime_qa_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "DataContractSchemaDrift_1.0.0.0_x64.msix"
            make_exact_test_package(package)
            config_root = self._config(root / "config", package, approved=True)
            config_path = config_root / "test-store-product.job.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["local_runtime_qa_status"] = "NOT_VERIFIED"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            result = run_approved_sections(product="test-store-product", config_root=config_root,
                                           package=package, ui_map_path=CONFIG_ROOT / "store_ui_maps" / "msix_pwa_app.v1.json",
                                           package_runner=lambda **_: self.fail("must hold before upload"))
            self.assertEqual(result["status"], "HOLD")
            self.assertEqual(result["actions"][0]["reason"], "EXACT_PACKAGE_RUNTIME_QA_REQUIRED")

    def test_fully_mock_approved_package_scope_dispatches_only_package_runner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "DataContractSchemaDrift_1.0.0.0_x64.msix"
            make_exact_test_package(package)
            config_root = self._config(root / "config", package, approved=True)
            calls = []
            def runner(**kwargs):
                calls.append(kwargs["product"])
                return {"status": "SUCCEEDED_RECONCILED", "writes_performed": True}
            result = run_approved_sections(product="test-store-product", config_root=config_root,
                                           package=package, ui_map_path=CONFIG_ROOT / "store_ui_maps" / "msix_pwa_app.v1.json",
                                           package_runner=runner)
            self.assertEqual(calls, ["test-store-product"])
            self.assertEqual(result["status"], "EXECUTED")
            self.assertEqual([item["section"] for item in result["actions"]], ["packages"])
            self.assertTrue(result["writes_performed"])
            self.assertFalse(result["certification_executed"])
            self.assertFalse(result["publish_executed"])

    def test_nonpackage_scope_requires_verified_ui_map_and_exact_section_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "DataContractSchemaDrift_1.0.0.0_x64.msix"
            make_exact_test_package(package)
            config_root = self._config(root / "config", package, approved=True)
            config_path = config_root / "test-store-product.job.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["execution_policy"]["approved_sections"] = ["properties"]
            config["approved_store_sections"] = {"properties": {"fields": [
                {"key": "category", "kind": "select", "label": "Category", "value": "productivity"}],
                "approval": {"approved": True, "product_id": config["product_id"],
                             "submission_id": config["submission_id"], "sections": ["properties"],
                             "approval_ref": "property-approval", "approved_by": "test-owner", "approved_at": "2026-11-28"}}}
            config_path.write_text(json.dumps(config), encoding="utf-8")
            ui_map = root / "ui-map.json"
            ui_map.write_text(json.dumps({"sections": {"properties": {"verified": False}}}), encoding="utf-8")
            result = run_approved_sections(product="test-store-product", config_root=config_root,
                                           package=package, ui_map_path=ui_map,
                                           section_runner=lambda **_: self.fail("unverified route must not dispatch"))
            self.assertEqual(result["status"], "HOLD")
            self.assertEqual(result["actions"][0]["reason"], "ACTION_TIME_VERIFIED_UI_MAP_REQUIRED")

    def test_later_section_hold_after_a_write_is_reported_as_partial_reconcile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "DataContractSchemaDrift_1.0.0.0_x64.msix"
            make_exact_test_package(package)
            config_root = self._config(root / "config", package, approved=True)
            config_path = config_root / "test-store-product.job.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["execution_policy"]["approved_sections"] = ["properties", "store_listings"]
            fields = [{"key": "category", "kind": "select", "label": "Category", "value": "productivity"}]
            approval = {"approved": True, "product_id": config["product_id"],
                        "submission_id": config["submission_id"], "sections": ["properties"],
                        "approval_ref": "property-approval", "approved_by": "test-owner", "approved_at": "2026-11-28"}
            config["approved_store_sections"] = {"properties": {"fields": fields, "approval": approval}}
            config_path.write_text(json.dumps(config), encoding="utf-8")
            ui_map = root / "ui-map.json"
            ui_map.write_text(json.dumps({"sections": {"properties": {"verified": True}}}), encoding="utf-8")
            result = run_approved_sections(
                product="test-store-product", config_root=config_root, package=package, ui_map_path=ui_map,
                section_runner=lambda **_: {"status": "SAVED_AND_RECONCILED", "writes_performed": True})
            self.assertEqual(result["status"], "PARTIAL_RECONCILE_REQUIRED")
            self.assertTrue(result["writes_performed"])
            self.assertEqual(result["actions"][0]["status"], "SAVED_AND_RECONCILED")
            self.assertEqual(result["actions"][1]["reason"], "APPROVED_SECTION_VALUES_MISSING")


if __name__ == "__main__":
    unittest.main()
