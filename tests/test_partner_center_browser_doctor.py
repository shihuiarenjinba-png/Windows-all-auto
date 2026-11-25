from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import patch

from uploader.core import UploadError
from uploader.partner_center_browser import (
    PARTNER_ORIGIN,
    PartnerCenterCDPConnection,
    safe_page_metadata,
    select_partner_center_page,
)


CONFIG = {"product_id": "9PDL4ZWSB45P", "submission_id": "1152921505702212222"}
EXACT = f"{PARTNER_ORIGIN}/en-us/dashboard/products/{CONFIG['product_id']}/submissions/{CONFIG['submission_id']}/packages"
OVERVIEW = f"{PARTNER_ORIGIN}/en-us/dashboard/products/{CONFIG['product_id']}/overview"


class Page:
    def __init__(self, url: str, title: str = "Partner Center"):
        self.url = url
        self._title = title
        self.goto_calls = 0
        self.click_calls = 0
        self.file_calls = 0

    def title(self):
        return self._title

    def locator(self, _selector):
        return types.SimpleNamespace(count=lambda: 0)

    def goto(self, *_args, **_kwargs):
        self.goto_calls += 1

    def click(self, *_args, **_kwargs):
        self.click_calls += 1

    def set_input_files(self, *_args, **_kwargs):
        self.file_calls += 1


class DoctorSelectionTests(unittest.TestCase):
    def test_exact_draft_selected_among_other_partner_center_and_cloudflare_pages(self):
        unrelated = Page(f"{PARTNER_ORIGIN}/en-us/dashboard/products/OTHER/overview")
        cloudflare = Page("https://dash.cloudflare.com/account/workers")
        selected, status, _ = select_partner_center_page([unrelated, cloudflare, Page(EXACT)], CONFIG)
        self.assertEqual(status, "READY_EXACT_DRAFT_TAB")
        self.assertEqual(selected.url.split("?")[0], EXACT)

    def test_exact_packages_is_preferred_over_dca_overview(self):
        overview = Page(OVERVIEW)
        packages = Page(EXACT)
        selected, status, _ = select_partner_center_page([overview, packages], CONFIG)
        self.assertIs(selected, packages)
        self.assertEqual(status, "READY_EXACT_DRAFT_TAB")

    def test_unique_dca_product_selected_despite_unrelated_partner_tabs(self):
        target = Page(OVERVIEW)
        selected, status, _ = select_partner_center_page([
            Page(f"{PARTNER_ORIGIN}/en-us/dashboard/products/OTHER/overview"), target,
            Page("https://dash.cloudflare.com/account/workers")], CONFIG)
        self.assertIs(selected, target)
        self.assertEqual(status, "READY_UNIQUE_PRODUCT_TAB")

    def test_two_exact_draft_tabs_fail_closed(self):
        with self.assertRaises(UploadError) as caught:
            select_partner_center_page([Page(EXACT), Page(EXACT + "?view=2")], CONFIG)
        self.assertEqual(caught.exception.code, "PARTNER_CENTER_TAB_AMBIGUOUS")

    def test_no_matching_target_ignores_non_partner_origins(self):
        pages = [Page("https://dash.cloudflare.com/account"),
                 Page("chrome-extension://abcdef/options"),
                 Page("https://unrelated.example/path"),
                 Page("https://partner.microsoft.com.evil.invalid/en-us/dashboard/products/9PDL4ZWSB45P/overview")]
        with self.assertRaises(UploadError) as caught:
            select_partner_center_page(pages, CONFIG)
        self.assertEqual(caught.exception.code, "HOLD_NO_MATCHING_PRODUCT_TAB")

    def test_query_fragment_and_path_secrets_are_not_reported(self):
        page = Page(EXACT + "?access_token=DO_NOT_LOG#private-fragment", "DCA https://example.test/?code=secret")
        meta = safe_page_metadata(page)
        rendered = json.dumps(meta)
        self.assertEqual(meta["path"], EXACT.removeprefix(PARTNER_ORIGIN))
        self.assertNotIn("DO_NOT_LOG", rendered)
        self.assertNotIn("private-fragment", rendered)
        self.assertNotIn("secret", rendered)

    def test_read_only_doctor_uses_same_selector_without_page_mutation(self):
        target = Page(EXACT + "?session=secret", "Data Contract Auditor | Partner Center")
        other = Page("https://dash.cloudflare.com/account", "Cloudflare")
        context = types.SimpleNamespace(pages=[target, other])
        browser = types.SimpleNamespace(contexts=[context], version="Edg/157.0.4341.46")
        runtime = types.SimpleNamespace(stop=lambda: None, chromium=types.SimpleNamespace(
            connect_over_cdp=lambda _url, **_kwargs: browser))
        package = types.ModuleType("playwright"); package.__path__ = []
        api = types.ModuleType("playwright.sync_api")
        api.sync_playwright = lambda: types.SimpleNamespace(start=lambda: runtime)
        connection = PartnerCenterCDPConnection("http://127.0.0.1:9223", CONFIG)
        connection._fetch_cdp_version = lambda: {"Browser": "Edg/157.0.4341.46"}
        with patch.dict(sys.modules, {"playwright": package, "playwright.sync_api": api}):
            report = connection.doctor()
        self.assertEqual(report["status"], "READY_EXACT_DRAFT_TAB")
        self.assertEqual(report["context_count"], 1)
        self.assertEqual(report["page_count"], 2)
        self.assertEqual(report["partner_center_page_count"], 1)
        self.assertFalse(report["navigation_performed"])
        self.assertFalse(report["clicks_performed"])
        self.assertFalse(report["save_performed"])
        self.assertEqual(target.goto_calls, target.click_calls)
        self.assertEqual(target.file_calls, 0)
        self.assertNotIn("secret", json.dumps(report))
        connection.__exit__(None, None, None)


if __name__ == "__main__":
    unittest.main()
