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
        # This fixture uses a synthetic package, so do not carry the live DCA provenance conflict into unrelated tests.
        config.pop("source_package_provenance", None)
        if approved:
            config["runtime_qa_receipt"] = {
                "status": "WINDOWS_REAL_DEVICE_QA_PASS_EXACT_PACKAGE",
                "product_id": config["product_id"], "submission_id": config["submission_id"],
                "package_sha256": config["expected_sha256"],
                "identity": config["identity_name"], "version": config["version"],
                "architecture": config["architecture"],
            }
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

    def test_source_profile_sha_conflict_holds_before_package_runner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "DataContractSchemaDrift_1.0.0.0_x64.msix"
            make_exact_test_package(package)
            config_root = self._config(root / "config", package, approved=True)
            path = config_root / "test-store-product.job.json"
            config = json.loads(path.read_text(encoding="utf-8"))
            config["source_package_provenance"] = {
                "status": "MISMATCH", "formal_package_sha256": "4b373d2bc54ecbd3efa0a77a94005007777e66d641fa3908f523ac69fcd46984"}
            path.write_text(json.dumps(config), encoding="utf-8")
            result = run_approved_sections(product="test-store-product", config_root=config_root,
                                           package=package,
                                           ui_map_path=CONFIG_ROOT / "store_ui_maps" / "msix_pwa_app.v1.json",
                                           package_runner=lambda **_: self.fail("provenance mismatch must hold"))
            self.assertEqual(result["status"], "HOLD")
            self.assertEqual(result["actions"][0]["reason"], "SOURCE_PRODUCT_PROFILE_PACKAGE_SHA_MISMATCH")

    def test_fully_mock_approved_package_scope_dispatches_only_package_runner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "DataContractSchemaDrift_1.0.0.0_x64.msix"
            make_exact_test_package(package)
            config_root = self._config(root / "config", package, approved=True)
            calls = []
            def runner(**kwargs):
                calls.append(kwargs["product"])
                config = json.loads((config_root / "test-store-product.job.json").read_text(encoding="utf-8"))
                return {"status": "SUCCEEDED_RECONCILED", "writes_performed": True,
                        "product_id": config["product_id"], "submission_id": config["submission_id"],
                        "sha256": config["expected_sha256"]}
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
            config["section_completion_receipts"] = {"packages": {
                "status": "SUCCEEDED_RECONCILED", "product_id": config["product_id"],
                "submission_id": config["submission_id"], "package_sha256": config["expected_sha256"],
                "reconciled_at_utc": "2026-11-28T00:00:00Z"}}
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

    def test_already_matches_is_completed_and_next_independent_section_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "DataContractSchemaDrift_1.0.0.0_x64.msix"
            make_exact_test_package(package)
            config_root = self._config(root / "config", package, approved=True)
            path = config_root / "test-store-product.job.json"
            config = json.loads(path.read_text(encoding="utf-8"))
            config["execution_policy"]["approved_sections"] = ["properties", "pricing_availability"]
            approval_template = {"approved": True, "product_id": config["product_id"],
                                 "submission_id": config["submission_id"], "approval_ref": "section-approval",
                                 "approved_by": "test-owner", "approved_at": "2026-11-28",
                                 "sections": ["properties", "pricing_availability"]}
            config["approved_store_sections"] = {
                section: {"fields": [{"key": section, "kind": "text", "label": "Value", "value": section}],
                          "approval": {**approval_template, "sections": [section]}}
                for section in ("properties", "pricing_availability")}
            path.write_text(json.dumps(config), encoding="utf-8")
            ui_map = root / "ui-map.json"
            ui_map.write_text(json.dumps({"sections": {key: {"verified": True}
                                                         for key in ("properties", "pricing_availability")}}),
                              encoding="utf-8")
            calls = []
            def runner(**kwargs):
                calls.append(kwargs["section"])
                return ({"status": "ALREADY_MATCHES", "writes_performed": False,
                         "reload_reconciled": True}
                        if kwargs["section"] == "properties" else
                        {"status": "SAVED_AND_RECONCILED", "writes_performed": True})
            result = run_approved_sections(product="test-store-product", config_root=config_root,
                                           package=package, ui_map_path=ui_map, section_runner=runner)
            self.assertEqual(calls, ["properties", "pricing_availability"])
            self.assertEqual(result["status"], "EXECUTED")
            self.assertTrue(result["all_approved_sections_completed"])
            self.assertEqual(result["completed_sections"], calls)
            self.assertTrue(result["writes_performed"])

    def test_all_noop_approved_sections_are_success_but_not_a_full_draft_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "DataContractSchemaDrift_1.0.0.0_x64.msix"
            make_exact_test_package(package)
            config_root = self._config(root / "config", package, approved=True)
            path = config_root / "test-store-product.job.json"
            config = json.loads(path.read_text(encoding="utf-8"))
            config["execution_policy"]["approved_sections"] = ["properties"]
            config["approved_store_sections"] = {"properties": {"fields": [
                {"key": "x", "kind": "text", "label": "Value", "value": "x"}],
                "approval": {"approved": True, "product_id": config["product_id"],
                             "submission_id": config["submission_id"], "sections": ["properties"],
                             "approval_ref": "a", "approved_by": "owner", "approved_at": "2026-11-28"}}}
            path.write_text(json.dumps(config), encoding="utf-8")
            ui_map = root / "ui-map.json"
            ui_map.write_text(json.dumps({"sections": {"properties": {"verified": True}}}), encoding="utf-8")
            result = run_approved_sections(
                product="test-store-product", config_root=config_root, package=package, ui_map_path=ui_map,
                section_runner=lambda **_: {"status": "ALREADY_MATCHES", "writes_performed": False,
                                           "reload_reconciled": True})
            self.assertEqual(result["status"], "EXECUTED")
            self.assertFalse(result["writes_performed"])
            self.assertTrue(result["all_approved_sections_completed"])

    def test_store_listings_waits_for_packages_but_independent_section_continues(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "DataContractSchemaDrift_1.0.0.0_x64.msix"
            make_exact_test_package(package)
            config_root = self._config(root / "config", package, approved=True)
            path = config_root / "test-store-product.job.json"
            config = json.loads(path.read_text(encoding="utf-8"))
            config["execution_policy"]["approved_sections"] = ["properties", "store_listings"]
            fields = [{"key": "value", "kind": "text", "label": "Value", "value": "ok"}]
            config["approved_store_sections"] = {"properties": {"fields": fields,
                "approval": {"approved": True, "product_id": config["product_id"],
                             "submission_id": config["submission_id"], "sections": ["properties"],
                             "approval_ref": "a", "approved_by": "owner", "approved_at": "2026-11-28"}},
                "store_listings": {"fields": fields,
                "approval": {"approved": True, "product_id": config["product_id"],
                             "submission_id": config["submission_id"], "sections": ["store_listings"],
                             "approval_ref": "b", "approved_by": "owner", "approved_at": "2026-11-28"}}}
            path.write_text(json.dumps(config), encoding="utf-8")
            ui_map = root / "ui-map.json"
            ui_map.write_text(json.dumps({"sections": {key: {"verified": True}
                                                         for key in ("properties", "store_listings")}}),
                              encoding="utf-8")
            calls = []
            result = run_approved_sections(product="test-store-product", config_root=config_root,
                                           package=package, ui_map_path=ui_map,
                                           section_runner=lambda **kw: calls.append(kw["section"]) or
                                           {"status": "ALREADY_MATCHES", "writes_performed": False,
                                            "reload_reconciled": True})
            self.assertEqual(calls, ["properties"])
            self.assertEqual(result["status"], "HOLD")
            self.assertTrue(result["completed_sections"] == ["properties"])
            self.assertEqual(result["actions"][-1]["status"], "WAITING_DEPENDENCY")
            self.assertEqual(result["actions"][-1]["dependencies"], ["packages"])

    def test_packages_runs_before_listings_even_when_profile_lists_listings_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "DataContractSchemaDrift_1.0.0.0_x64.msix"
            make_exact_test_package(package)
            config_root = self._config(root / "config", package, approved=True)
            path = config_root / "test-store-product.job.json"
            config = json.loads(path.read_text(encoding="utf-8"))
            config["execution_policy"]["approved_sections"] = ["store_listings", "packages"]
            fields = [{"key": "value", "kind": "text", "label": "Value", "value": "ok"}]
            config["approved_store_sections"] = {"store_listings": {"fields": fields,
                "approval": {"approved": True, "product_id": config["product_id"],
                             "submission_id": config["submission_id"], "sections": ["store_listings"],
                             "approval_ref": "b", "approved_by": "owner", "approved_at": "2026-11-28"}}}
            path.write_text(json.dumps(config), encoding="utf-8")
            ui_map = root / "ui-map.json"
            ui_map.write_text(json.dumps({"sections": {"store_listings": {"verified": True}}}), encoding="utf-8")
            calls = []
            result = run_approved_sections(
                product="test-store-product", config_root=config_root, package=package, ui_map_path=ui_map,
                package_runner=lambda **_: calls.append("packages") or
                {"status": "SUCCEEDED_RECONCILED", "writes_performed": True,
                 "product_id": DCA_BINDING["product_id"], "submission_id": DCA_BINDING["submission_id"],
                 "sha256": make_exact_test_package(package)},
                section_runner=lambda **_: calls.append("store_listings") or
                {"status": "ALREADY_MATCHES", "writes_performed": False,
                 "reload_reconciled": True})
            self.assertEqual(calls, ["packages", "store_listings"])
            self.assertEqual(result["status"], "EXECUTED")
            self.assertTrue(result["all_approved_sections_completed"])


if __name__ == "__main__":
    unittest.main()
