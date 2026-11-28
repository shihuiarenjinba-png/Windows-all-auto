from __future__ import annotations

import json
import tempfile
import unittest
import hashlib
import zipfile
from pathlib import Path

from all_auto.windows_msix_qa import diagnose_msix_runtime
CONFIG_ROOT = Path(__file__).resolve().parents[1] / "uploader" / "config"


def make_exact_test_package(path: Path) -> str:
    manifest = '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="OkinawaDesktopTools.DataContractAuditor" Publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC" Version="1.0.0.0" ProcessorArchitecture="x64" /><Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.22621.0" /></Dependencies></Package>'''
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("AppxManifest.xml", manifest)
        package.writestr("payload.bin", b"synthetic exact QA fixture")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WindowsMsixDiagnosticTests(unittest.TestCase):
    def test_diagnostic_verifies_static_tuple_and_never_claims_runtime_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "candidate.msix"
            digest = make_exact_test_package(package)
            config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
            config["expected_sha256"] = digest
            report = diagnose_msix_runtime(config=config, package=package,
                                           prior_install_result="ACCESS_DENIED",
                                           prior_launch_result="TIMEOUT")
            self.assertTrue(report["diagnostic_only"])
            self.assertFalse(report["install_attempted"])
            self.assertFalse(report["launch_attempted"])
            self.assertTrue(report["package"]["exact_identity_sha_match"])
            self.assertEqual(report["assessment"], "RUNTIME_QA_UNRESOLVED")
            self.assertFalse(report["package"]["appx_signature_file_present"])

    def test_diagnostic_rejects_changed_fixed_sha(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "candidate.msix"
            digest = make_exact_test_package(package)
            config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
            config["expected_sha256"] = "0" * 64
            with self.assertRaises(Exception):
                diagnose_msix_runtime(config=config, package=package)

    def test_companion_script_is_explicitly_read_only(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_msix_runtime.ps1"
        source = script.read_text(encoding="utf-8")
        self.assertIn("InstallAttempted = $false", source)
        self.assertIn("LaunchAttempted = $false", source)
        self.assertNotIn("Add-AppxPackage", source)
        self.assertNotIn("Set-ExecutionPolicy", source)

    def test_test_sign_lane_is_ephemeral_and_separate_from_store_candidate(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "test_sign_msix_copy.ps1").read_text(encoding="utf-8")
        for required in ("$env:GITHUB_ACTIONS -ne 'true'", "System.IO.Compression.FileSystem",
                         "New-SelfSignedCertificate",
                         "Cert:\\LocalMachine\\TrustedPeople", "& $signTool sign /fd SHA256",
                         "Add-AppxPackage -Path $derived", "IApplicationActivationManager",
                         "ActivateApplication", "installed-package-executable",
                         "UNCONFIRMED_IN_HOSTED_RUNNER", "Remove-AppxPackage",
                         "store_candidate_unchanged=$true", "diagnostic_only=$true"):
            self.assertIn(required, source)
        self.assertNotIn("Set-ExecutionPolicy", source)
        self.assertLess(source.index("Import-Certificate -FilePath $publicCert"),
                        source.index("& $signTool verify /pa /v $derived"))
        workflow = (root / ".github" / "workflows" / "offline-qa.yml").read_text(encoding="utf-8")
        self.assertIn("synthetic-msix-test-signing-receipt", workflow)
        self.assertIn('"STARTED"', workflow)
        self.assertIn("WindowsApplication", workflow)
        self.assertIn("*.json", workflow)
        self.assertIn("Test-sign, install, and smoke-test a synthetic MSIX", workflow)


if __name__ == "__main__":
    unittest.main()
