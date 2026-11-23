from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from uploader.core import verify_file
from uploader.receipts import new_execution_receipt
from uploader.partner_center_browser import (
    FILE_INPUT, PACKAGES_COMPLETE, PACKAGE_NAME_SELECTOR, WARNING_SELECTOR,
    PartnerCenterBrowserPort,
)

KNOWN_WARNING = "Package acceptance validation warning: The following restricted capabilities require approval before you can use them in your app: runFullTrust."
CONFIG = {
    "product_name": "Folder Automation Engine",
    "product_id": "9P99MJX1R4V6",
    "submission_id": "1152921505702423660",
    "known_warnings": [KNOWN_WARNING],
    "upload_approved": False,
    "identity_name": "OkinawaDesktopTools.FolderAutomationEngine",
    "publisher": "CN=46263F21-A700-41DB-8C9B-114C22FB82FC",
}


class Locator:
    def __init__(self, page, selector, *, text="", role=""):
        self.page, self.selector, self.text, self.role = page, selector, text, role

    def count(self):
        p = self.page
        if self.selector == "input[type='password']": return 0
        if self.selector == FILE_INPUT: return 1 if p.is_packages else 0
        if self.selector == PACKAGE_NAME_SELECTOR: return 1 if p.package_present and p.is_packages else 0
        if self.selector == "table.package-table": return 1 if p.package_present and p.is_packages else 0
        if self.selector == WARNING_SELECTOR: return 1 if p.package_present and p.is_packages else 0
        if self.selector == ".alert.alert-danger .alert-string": return 0
        if self.selector == PACKAGES_COMPLETE: return 1 if p.saved and p.is_overview else 0
        if self.role == "checkbox": return 1
        if self.role == "button" and self.text == "Save": return 1 if p.is_packages else 0
        if self.role == "link" and self.text == CONFIG["product_name"]: return 1 if p.is_packages else 0
        if self.role == "heading" and self.text == CONFIG["product_name"]: return 1 if p.is_overview else 0
        if self.text in {"9P99MJX1R4V6", "OkinawaDesktopTools.FolderAutomationEngine", "CN=46263F21-A700-41DB-8C9B-114C22FB82FC"}:
            return 1 if "/identity" in p.url else 0
        if self.text == CONFIG["product_name"]: return 1 if "/identity" in p.url else 0
        if self.text == p.job.file_name: return int(p.package_present and (p.is_packages or p.is_overview))
        if self.text in {"Validated"}: return int(p.saved and p.is_overview)
        if self.text in {"Uploading", "Analyzing package"}: return 0
        return 0

    def all_text_contents(self):
        p = self.page
        if self.selector == PACKAGE_NAME_SELECTOR and self.count(): return [p.job.file_name]
        if self.selector == WARNING_SELECTOR and self.count(): return [KNOWN_WARNING]
        if self.selector == "table.package-table" and self.count(): return [f"{p.job.file_name} v{p.job.version} {p.job.architecture.upper()} Windows.Desktop"]
        if self.selector == ".alert.alert-danger .alert-string": return []
        return []

    def set_input_files(self, path):
        self.page.upload_calls += 1
        self.page.package_present = True
        self.page.upload_path = path

    def is_checked(self): return True
    def is_enabled(self): return True
    def click(self, timeout=None):
        self.page.save_calls += 1
        self.page.saved = True
        self.page.url = f"https://partner.microsoft.com/en-us/dashboard/products/{self.page.job.product_id}/overview"
    def wait_for(self, state=None, timeout=None):
        if self.count() != 1: raise TimeoutError("expected postcondition absent")
    def get_attribute(self, name):
        if name == "href" and self.selector == PACKAGES_COMPLETE:
            return f"/en-us/dashboard/products/{self.page.job.product_id}/submissions/{self.page.job.submission_id}/packages"
        return None


class FakePage:
    def __init__(self, job):
        self.job = job
        self.url = "https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview"
        self.package_present = False
        self.saved = False
        self.upload_calls = 0
        self.save_calls = 0
        self.upload_path = None

    @property
    def is_packages(self): return "/packages" in self.url
    @property
    def is_overview(self): return self.url.endswith("/overview")
    def locator(self, selector): return Locator(self, selector)
    def get_by_text(self, text, exact=True): return Locator(self, "text", text=text)
    def get_by_role(self, role, name="", exact=True): return Locator(self, "role", text=name, role=role)
    def goto(self, url, wait_until=None, timeout=None): self.url = url
    def reload(self, wait_until=None, timeout=None): pass
    def wait_for_timeout(self, milliseconds): pass


class PartnerCenterBrowserTests(unittest.TestCase):
    def make_package(self, path):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("AppxManifest.xml", '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="OkinawaDesktopTools.FolderAutomationEngine" Publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC" Version="1.0.0.0" ProcessorArchitecture="x64" /></Package>''')
            z.writestr("payload", b"fixture")

    def test_replays_successful_existing_draft_packages_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "FolderAutomationEngine_1.0.0.0_x64_StoreDraft_UNSIGNED.msix"
            self.make_package(package)
            job_config = {
                **CONFIG,
                "schema_version": 1,
                "repository": "owner/repo",
                "ref": "a" * 40,
                "path": package.name,
                "version": "1.0.0.0",
                "destination": "microsoft_partner_center_existing_draft",
                "identity_name": "OkinawaDesktopTools.FolderAutomationEngine",
                "publisher": "CN=46263F21-A700-41DB-8C9B-114C22FB82FC",
                "architecture": "x64",
                "upload_approved": False,
            }
            job = verify_file(job_config, package)
            page = FakePage(job)
            result = PartnerCenterBrowserPort(page, CONFIG).upload_save_and_reconcile(job, package)
            self.assertTrue(result["partner_center_confirmed"])
            self.assertEqual(result["method"], "authenticated_playwright_cdp_existing_draft_packages")
            self.assertEqual(result["package_validation"], "WARNING")
            self.assertEqual(page.upload_calls, 1)
            self.assertEqual(page.save_calls, 1)
            self.assertEqual(result["state_transitions"], [
                "PACKAGE_UPLOAD_REQUIRED", "PACKAGE_WARNING_REVIEW", "PACKAGE_SAVE_REQUIRED",
                "PACKAGES_SAVED", "OVERVIEW_RELOADED", "PACKAGES_REOPENED_RETAINED",
            ])

    def test_existing_filename_is_not_saved_again_without_hash_bound_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "FolderAutomationEngine_1.0.0.0_x64_StoreDraft_UNSIGNED.msix"
            self.make_package(package)
            job_config = {
                "schema_version": 1, **CONFIG, "repository": "owner/repo", "ref": "a" * 40,
                "path": package.name, "version": "1.0.0.0", "destination": "microsoft_partner_center_existing_draft",
                "identity_name": "OkinawaDesktopTools.FolderAutomationEngine",
                "publisher": "CN=46263F21-A700-41DB-8C9B-114C22FB82FC", "architecture": "x64",
                "upload_approved": False,
            }
            job = verify_file(job_config, package)
            page = FakePage(job)
            page.package_present = True
            from uploader.core import UploadError
            with self.assertRaisesRegex(UploadError, "prior SHA-bound receipt"):
                PartnerCenterBrowserPort(page, CONFIG).upload_save_and_reconcile(job, package)
            self.assertEqual(page.upload_calls, 0)
            self.assertEqual(page.save_calls, 0)

    def test_overview_filename_validated_and_complete_need_matching_prior_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "FolderAutomationEngine_1.0.0.0_x64_StoreDraft_UNSIGNED.msix"
            self.make_package(package)
            job_config = {
                "schema_version": 1, **CONFIG, "repository": "owner/repo", "ref": "a" * 40,
                "path": package.name, "version": "1.0.0.0", "destination": "microsoft_partner_center_existing_draft",
                "identity_name": "OkinawaDesktopTools.FolderAutomationEngine",
                "publisher": "CN=46263F21-A700-41DB-8C9B-114C22FB82FC", "architecture": "x64",
                "upload_approved": False,
            }
            job = verify_file(job_config, package)
            page = FakePage(job)
            page.package_present = True
            page.saved = True
            port = PartnerCenterBrowserPort(page, CONFIG)
            no_receipt = port.reconcile_ambiguous_upload(job, package)
            self.assertFalse(no_receipt["partner_center_confirmed"])
            self.assertFalse(no_receipt["safe_to_retry"])
            self.assertIsNone(no_receipt["partner_center_sha256"])

            prior = new_execution_receipt(
                product_id=job.product_id, submission_id=job.submission_id,
                package_file_name=job.file_name, sha256=job.sha256, result="SUCCEEDED",
                partner_center_confirmation="UI_VALIDATED_SHA_UNOBSERVABLE",
                details={"partner_center_confirmed": True, "partner_center_sha256": None},
            )
            confirmed = port.reconcile_ambiguous_upload(job, package, prior)
            self.assertTrue(confirmed["partner_center_confirmed"])
            self.assertTrue(confirmed["prior_receipt_sha256_match"])
            self.assertTrue(confirmed["no_reupload"])
            self.assertEqual(page.upload_calls, 0)


if __name__ == "__main__":
    unittest.main()
