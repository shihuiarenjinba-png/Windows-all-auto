import unittest
from pathlib import Path


class LocalExactPackagePreflightContractTests(unittest.TestCase):
    def test_script_is_fail_closed_on_source_package_identity_and_security(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "scripts" / "run_local_exact_package_preflight.ps1").read_text(encoding="utf-8")
        for required in (
            "Local product repository HEAD does not match handoff source SHA",
            "MSIX SHA256 does not match handoff",
            "Manifest Identity Name mismatch",
            "Manifest Publisher mismatch",
            "Manifest Version mismatch",
            "Unpacked main EXE SHA256 mismatch",
            'package_rebuilt = $false',
            'security_bypass_used = $false',
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
