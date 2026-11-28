from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from all_auto.artifact_archive import (ArtifactArchiveError, archive_verified_package,
                                       copy_to_approved_external_backup)


class ArtifactArchiveTests(unittest.TestCase):
    def test_archive_is_sha_addressed_and_idempotent_without_overwriting(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            package = root / "Exact_1.0.0.0_x64.msix"
            manifest = '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="Example.Identity" Publisher="CN=Example" Version="1.0.0.0" ProcessorArchitecture="x64" /><Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.0.0" MaxVersionTested="10.0.0.0" /></Dependencies></Package>'''
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("AppxManifest.xml", manifest)
                archive.writestr("payload.bin", b"exact bytes")
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            config = {"schema_version": 1, "product_name": "Example", "product_id": "9P1234567890",
                      "submission_id": "1152921505700000000", "repository": "owner/repo",
                      "ref": "a" * 40, "source_sha": "a" * 40, "artifact_id": 123, "artifact_run_id": 456,
                      "path": package.name, "expected_sha256": digest, "version": "1.0.0.0",
                      "identity_name": "Example.Identity", "publisher": "CN=Example",
                      "architecture": "x64", "destination": "microsoft_partner_center_existing_draft",
                      "upload_approved": False,
                      "max_bytes": 1000000}
            output = root / "archive"
            first = archive_verified_package(config, package, output)
            second = archive_verified_package(config, package, output)
            self.assertEqual(first["status"], "ARCHIVED_VERIFIED")
            self.assertEqual(second["status"], "ARCHIVE_ALREADY_PRESENT")
            self.assertEqual(Path(first["path"]).read_bytes(), package.read_bytes())
            self.assertEqual(Path(first["receipt"]).is_file(), True)
            self.assertIn(digest, first["path"])

    def test_external_backup_does_not_transfer_without_destination_approval(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            package, config = self._example_package_and_config(root)
            archive = archive_verified_package(config, package, root / "archive")
            with self.assertRaisesRegex(ArtifactArchiveError, "requires a Product/Draft-bound owner approval"):
                copy_to_approved_external_backup(config, Path(archive["path"]),
                                                 Path(archive["receipt"]), root / "external")
            self.assertFalse((root / "external").exists())

    def test_external_backup_is_exact_path_scoped_and_idempotent(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            package, config = self._example_package_and_config(root)
            archive = archive_verified_package(config, package, root / "archive")
            approved = root / "approved-destination"
            config["external_backup_approval"] = {
                "status": "OWNER_APPROVED", "product_id": config["product_id"],
                "submission_id": config["submission_id"], "approval_ref": "owner-ticket-1",
                "approved_at": "2026-11-28", "destination_root": str(approved.resolve()),
            }
            with self.assertRaisesRegex(ArtifactArchiveError, "does not match"):
                copy_to_approved_external_backup(config, Path(archive["path"]),
                                                 Path(archive["receipt"]), root / "other")
            first = copy_to_approved_external_backup(config, Path(archive["path"]),
                                                     Path(archive["receipt"]), approved)
            second = copy_to_approved_external_backup(config, Path(archive["path"]),
                                                      Path(archive["receipt"]), approved)
            self.assertEqual(first["status"], "BACKUP_COPIED_AND_VERIFIED")
            self.assertEqual(second["status"], "BACKUP_ALREADY_VERIFIED")
            self.assertEqual(Path(first["path"]).read_bytes(), Path(archive["path"]).read_bytes())

    @staticmethod
    def _example_package_and_config(root: Path):
        package = root / "Exact_1.0.0.0_x64.msix"
        manifest = '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="Example.Identity" Publisher="CN=Example" Version="1.0.0.0" ProcessorArchitecture="x64" /><Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.0.0" MaxVersionTested="10.0.0.0" /></Dependencies></Package>'''
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("AppxManifest.xml", manifest)
            archive.writestr("payload.bin", b"exact bytes")
        digest = hashlib.sha256(package.read_bytes()).hexdigest()
        config = {"schema_version": 1, "product_name": "Example", "product_id": "9P1234567890",
                  "submission_id": "1152921505700000000", "repository": "owner/repo",
                  "ref": "a" * 40, "source_sha": "a" * 40, "artifact_id": 123, "artifact_run_id": 456,
                  "path": package.name, "expected_sha256": digest, "version": "1.0.0.0",
                  "identity_name": "Example.Identity", "publisher": "CN=Example",
                  "architecture": "x64", "destination": "microsoft_partner_center_existing_draft",
                  "upload_approved": False, "max_bytes": 1000000}
        return package, config


if __name__ == "__main__":
    unittest.main()
