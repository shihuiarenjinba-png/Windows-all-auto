from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StoreMsixScriptTests(unittest.TestCase):
    def test_upload_script_checks_exact_approval_hash_and_filename_before_edge(self):
        script = (ROOT / "scripts" / "upload_store_msix.ps1").read_text(encoding="utf-8")
        approval = script.index("$jobConfig.upload_approved -ne $true")
        expected_hash = script.index("expected_sha256 -notmatch")
        filename = script.index("Local MSIX filename does not match")
        cdp = script.index("/json/version")
        execute = script.index("$arguments += '--execute'")
        self.assertLess(approval, cdp)
        self.assertLess(expected_hash, cdp)
        self.assertLess(filename, cdp)
        self.assertLess(cdp, execute)
        self.assertIn("$uri.IsLoopback", script)
        self.assertIn("^Edg/", script)
        self.assertIn("ONE_EXACT_MSIX_TO_EXISTING_DRAFT_PACKAGES_ONLY", script)
        self.assertIn("certification_submission_authorized", script)
        self.assertIn("publish_authorized", script)

    def test_upload_script_has_no_certification_or_publish_action(self):
        script = (ROOT / "scripts" / "upload_store_msix.ps1").read_text(encoding="utf-8").casefold()
        self.assertNotIn("submit to the store", script)
        self.assertNotIn("submit for certification", script)
        self.assertNotIn("publish now", script)
        self.assertIn("existing draft", script)

    def test_bootstrap_pins_playwright_and_uses_isolated_venv(self):
        requirements = (ROOT / "requirements-store-uploader.txt").read_text(encoding="utf-8")
        bootstrap = (ROOT / "scripts" / "bootstrap_store_uploader.ps1").read_text(encoding="utf-8")
        self.assertIn("playwright==1.56.0", requirements)
        self.assertIn(".venv-store-uploader", bootstrap)
        self.assertIn("requirements-store-uploader.txt", bootstrap)

    def test_edge_bootstrap_is_loopback_only_and_manual_login(self):
        script = (ROOT / "scripts" / "start_partner_center_edge_cdp.ps1").read_text(encoding="utf-8")
        self.assertIn("$uri.IsLoopback", script)
        self.assertIn("--remote-debugging-port=9223", script)
        self.assertIn("Sign in to Partner Center manually", script)
        self.assertNotIn("password", script.casefold())


if __name__ == "__main__":
    unittest.main()
