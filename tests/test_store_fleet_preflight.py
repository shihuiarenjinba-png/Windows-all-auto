from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from uploader.core import validate_config
from uploader.fleet_preflight import PRODUCT_KEYS, build_fleet_preflight, verify_local_product


class StoreFleetPreflightTests(unittest.TestCase):
    def test_six_existing_draft_configs_are_exact_sha_pinned_and_fail_closed(self):
        config_root = Path(__file__).resolve().parents[1] / "uploader" / "config"
        store_ids = set()
        submission_ids = set()
        for key in PRODUCT_KEYS:
            config = validate_config(json.loads((config_root / f"{key}.job.json").read_text(encoding="utf-8")))
            self.assertRegex(config["expected_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(config["source_sha"], r"^[0-9a-f]{40}$")
            self.assertEqual(config["ref"], config["source_sha"])
            self.assertFalse(config["upload_approved"])
            self.assertTrue(config["upload_hold_reasons"])
            self.assertNotIn(config["product_id"], store_ids)
            self.assertNotIn(config["submission_id"], submission_ids)
            store_ids.add(config["product_id"])
            submission_ids.add(config["submission_id"])
        self.assertEqual(len(PRODUCT_KEYS), 6)

    def test_exact_package_sha_and_manifest_are_checked_without_partner_center(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = root / "packages"
            package_root.mkdir()
            config_root = root / "config"
            config_root.mkdir()
            package = package_root / "Exact.msix"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(
                    "AppxManifest.xml",
                    '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
                    <Identity Name="Example.Identity" Publisher="CN=Example" Version="1.2.3.4" ProcessorArchitecture="x64" />
                    </Package>''',
                )
                archive.writestr("payload.bin", b"exact-msix")
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            config = {
                "schema_version": 1, "product_name": "Example",
                "product_id": "9P1234567890", "submission_id": "1152921505700000000",
                "repository": "owner/repo", "ref": "a" * 40,
                "path": "store-output/Exact.msix", "version": "1.2.3.4",
                "destination": "microsoft_partner_center_existing_draft",
                "submission_route": "msix_pwa_app", "identity_name": "Example.Identity",
                "publisher": "CN=Example", "architecture": "x64",
                "known_warnings": [], "expected_existing_package_names": [],
                "expected_replaced_package_names": [], "upload_approved": False,
                "expected_sha256": digest, "max_bytes": 1000000,
                "upload_hold_reasons": ["OWNER_APPROVAL_PENDING"],
            }
            (config_root / "fixture.job.json").write_text(json.dumps(config), encoding="utf-8")
            result = verify_local_product("fixture", package_root, config_root)
            self.assertEqual(result["status"], "STATIC_VERIFICATION_PASS_HELD")
            self.assertEqual(result["sha256"], digest)
            self.assertEqual(result["identity_name"], "Example.Identity")
            self.assertFalse(result["upload_approved"])
            self.assertIn("OWNER_APPROVAL_PENDING", result["hold_reasons"])

    def test_duplicate_exact_filename_is_ambiguous_and_never_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = root / "packages"
            (package_root / "one").mkdir(parents=True)
            (package_root / "two").mkdir(parents=True)
            config_root = root / "config"
            config_root.mkdir()
            for folder in ("one", "two"):
                (package_root / folder / "Exact.msix").write_bytes(b"not-parsed")
            config = {
                "schema_version": 1, "product_name": "Example",
                "product_id": "9P1234567890", "submission_id": "1152921505700000000",
                "repository": "owner/repo", "ref": "a" * 40,
                "path": "store-output/Exact.msix", "version": "1.2.3.4",
                "destination": "microsoft_partner_center_existing_draft",
                "submission_route": "msix_pwa_app", "identity_name": "Example.Identity",
                "publisher": "CN=Example", "architecture": "x64",
                "known_warnings": [], "expected_existing_package_names": [],
                "expected_replaced_package_names": [], "upload_approved": False,
                "expected_sha256": "a" * 64, "max_bytes": 1000000,
            }
            (config_root / "fixture.job.json").write_text(json.dumps(config), encoding="utf-8")
            result = verify_local_product("fixture", package_root, config_root)
            self.assertEqual(result["status"], "PACKAGE_PATH_AMBIGUOUS")
            self.assertEqual(len(result["matching_paths"]), 2)

    def test_fleet_report_keeps_workflow_automation_hub_out_of_existing_draft_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_root = root / "packages"
            package_root.mkdir()
            config_root = root / "config"
            config_root.mkdir()
            report = build_fleet_preflight(package_root, config_root)
            self.assertTrue(report["read_only"])
            self.assertFalse(report["partner_center_touched"])
            self.assertFalse(report["package_uploaded"])
            hub = next(x for x in report["products"] if x["product_key"] == "workflow-automation-hub")
            self.assertEqual(hub["status"], "NO_EXISTING_SUBMISSION")


if __name__ == "__main__":
    unittest.main()
