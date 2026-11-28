from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from all_auto.artifact_archive import archive_verified_package


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


if __name__ == "__main__":
    unittest.main()
