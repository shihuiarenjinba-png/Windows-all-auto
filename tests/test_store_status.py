from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from all_auto.store_status import (
    SECTION_ROUTES,
    _local_package,
    _partner_center,
    _upload_history,
)
from uploader.partner_center_browser import FILE_INPUT


CONFIG_ROOT = Path(__file__).resolve().parents[1] / "uploader" / "config"
REPO_ROOT = Path(__file__).resolve().parents[1]


def synthetic_msix(path: Path) -> str:
    manifest = '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="OkinawaDesktopTools.DataContractAuditor" Publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC" Version="1.0.0.0" ProcessorArchitecture="x64" /></Package>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AppxManifest.xml", manifest)
        archive.writestr("payload.bin", b"synthetic")
    return sha256(path.read_bytes()).hexdigest()


class StoreStatusTests(unittest.TestCase):
    def test_live_packages_file_selector_matches_observed_partner_center_input(self):
        # Observed on the exact DCA existing-Draft Packages page on 2026-11-28.
        self.assertEqual(FILE_INPUT, "input[name='fileuploader'][type='file'][multiple]")

    def test_live_observed_routes_are_recorded_but_write_map_stays_unverified(self):
        expected = {
            "pricing_availability": ("Pricing and availability", "/availability"),
            "properties": ("Properties", "/properties"),
            "age_ratings": ("Age ratings", "/ageratings"),
            "packages": ("Packages", "/packages"),
            "store_listings": ("Store listings", "/managelanguages"),
            "submission_options": ("Submission Options", "/options"),
        }
        self.assertEqual(SECTION_ROUTES, expected)
        route_map = json.loads((CONFIG_ROOT / "store_ui_maps" / "msix_pwa_app.v1.json").read_text(encoding="utf-8"))
        observed = route_map["evidence"]["current_live_link_observation"]
        self.assertEqual(observed["package_file_input"], FILE_INPUT)
        self.assertFalse(observed["device_family_state"]["Windows 10/11 Desktop"])
        for key, (_, token) in expected.items():
            if key == "packages":
                self.assertEqual(route_map["sections"][key]["delegated_adapter"], "uploader.partner_center_browser")
            else:
                self.assertEqual(route_map["sections"][key]["path_token"], token)
                self.assertFalse(route_map["sections"][key]["verified"])

    def test_package_search_is_read_only_and_reports_exact_manifest(self):
        config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / ".store-artifacts" / "data-contract-auditor" / Path(config["path"]).name
            package.parent.mkdir(parents=True)
            digest = synthetic_msix(package)
            config["expected_sha256"] = digest
            before = package.stat().st_mtime_ns
            with patch("all_auto.store_status.Path.home", return_value=root):
                result = _local_package(config, root)
            self.assertEqual(result["status"], "EXACT_PACKAGE_VERIFIED")
            self.assertEqual(result["sha256"], digest)
            self.assertEqual(result["identity"], config["identity_name"])
            self.assertEqual(result["version"], config["version"])
            self.assertEqual(result["architecture"], config["architecture"])
            self.assertEqual(result["signature_state"], "UNSIGNED")
            self.assertEqual(package.stat().st_mtime_ns, before)

    def test_upload_history_deduplicates_receipt_copies_and_does_not_mutate_sqlite(self):
        config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            product_dir = root / ".uploader-run" / "data-contract-auditor"
            (product_dir / "durable-ledger" / "receipts" / config["product_id"]).mkdir(parents=True)
            (product_dir / "durable-ledger" / "receipts" / config["product_id"] / "receipt-1.json").write_text(
                json.dumps({"receipt_id": "receipt-1", "product_id": config["product_id"],
                            "submission_id": config["submission_id"], "package_file_name": Path(config["path"]).name,
                            "sha256": config["expected_sha256"], "result": "FAILED",
                            "partner_center_confirmation": "NOT_CONFIRMED", "executed_at": "2026-11-25T00:00:00Z",
                            "details": {"error_code": "AUTH_FAILED"}}), encoding="utf-8")
            (product_dir / "receipt-1.json").write_text(
                json.dumps({"receipt_id": "receipt-1", "product_id": config["product_id"],
                            "submission_id": config["submission_id"], "package_file_name": Path(config["path"]).name,
                            "sha256": config["expected_sha256"], "result": "FAILED",
                            "partner_center_confirmation": "NOT_CONFIRMED", "executed_at": "2026-11-25T00:00:00Z",
                            "details": {"error_code": "AUTH_FAILED"}}), encoding="utf-8")
            with patch("all_auto.store_status.Path.home", return_value=root):
                history = _upload_history(config, root, "data-contract-auditor")
            self.assertEqual(history["durable_receipt_count"], 1)
            self.assertEqual(history["successful_receipt_count"], 0)
            self.assertEqual(history["upload_started_evidence_count"], 0)
            self.assertFalse(history["partner_center_save_confirmed"])

    def test_local_cdp_discovery_is_bounded_to_known_edge_port_and_checks_browser(self):
        from all_auto.cdp_discovery import discover_local_edge_cdp, resolve_local_edge_cdp
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self): return b'{"Browser":"Edg/140.0"}'
        with patch("all_auto.cdp_discovery.urlopen", return_value=Response()) as open_url:
            result = discover_local_edge_cdp()
        self.assertEqual(result.status, "CDP_CONNECTED")
        self.assertEqual(result.endpoint, "http://127.0.0.1:9223")
        self.assertEqual(open_url.call_args.args[0], "http://127.0.0.1:9223/json/version")
        with patch("all_auto.cdp_discovery.urlopen", return_value=Response()) as open_url:
            explicit = resolve_local_edge_cdp("http://127.0.0.1:9333")
        self.assertEqual(explicit.endpoint, "http://127.0.0.1:9333")
        open_url.assert_not_called()

    def test_auto_discovery_rejects_non_edge_and_unavailable_without_launching_browser(self):
        from all_auto.cdp_discovery import discover_local_edge_cdp
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self): return b'{"Browser":"Chrome/140.0"}'
        with patch("all_auto.cdp_discovery.urlopen", return_value=Response()):
            self.assertEqual(discover_local_edge_cdp().status, "CDP_BROWSER_NOT_EDGE")
        with patch("all_auto.cdp_discovery.urlopen", side_effect=OSError("unavailable")):
            self.assertEqual(discover_local_edge_cdp().status, "CDP_NOT_AVAILABLE")

    def test_invalid_cdp_is_rejected_without_opening_browser(self):
        config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
        result = _partner_center(config, "https://example.com")
        self.assertEqual(result["status"], "CDP_ENDPOINT_REJECTED")
        self.assertFalse(result["writes_performed"])


if __name__ == "__main__":
    unittest.main()

