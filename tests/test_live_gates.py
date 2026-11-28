from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from uploader.core import JobLedger, UploadError, process_job, verify_file


class SharedLiveGateTests(unittest.TestCase):
    def test_process_job_direct_call_cannot_bypass_run_approval_gate_or_reserve_upload(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            package = root / "Exact_1.0.0.0_x64.msix"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("AppxManifest.xml", '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="Example.Identity" Publisher="CN=Example" Version="1.0.0.0" ProcessorArchitecture="x64" /><Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.0.0" MaxVersionTested="10.0.0.0" /></Dependencies></Package>''')
                archive.writestr("payload.bin", b"fixture")
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            config = {"schema_version": 1, "product_name": "Example", "product_id": "9P1234567890",
                      "submission_id": "1152921505700000000", "repository": "owner/repo",
                      "ref": "a" * 40, "path": package.name, "version": "1.0.0.0",
                      "destination": "microsoft_partner_center_existing_draft",
                      "identity_name": "Example.Identity", "publisher": "CN=Example",
                      "architecture": "x64", "upload_approved": True,
                      "upload_scope": "ONE_EXACT_MSIX_TO_EXISTING_DRAFT_PACKAGES_ONLY",
                      "expected_sha256": digest, "certification_submission_authorized": False,
                      "publish_authorized": False, "known_warnings": [],
                      "expected_existing_package_names": [], "expected_replaced_package_names": []}
            ledger = JobLedger(root / "ledger.sqlite")
            calls = []
            try:
                with self.assertRaises(UploadError) as caught:
                    process_job(config, package, ledger, expected_sha256=digest, dry_run=False,
                                live_adapter=lambda *_: calls.append("write") or {"partner_center_confirmed": True})
                self.assertEqual(caught.exception.code, "PERSISTED_PACKAGE_EXECUTION_APPROVAL_REQUIRED")
                self.assertEqual(calls, [])
                self.assertEqual(ledger.state_for(verify_file(config, package, expected_sha256=digest)), None)
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
