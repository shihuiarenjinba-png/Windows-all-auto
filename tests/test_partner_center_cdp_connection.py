from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from uploader.core import UploadError
from uploader.partner_center_browser import (
    PARTNER_ORIGIN,
    PartnerCenterBrowserPort,
    PartnerCenterCDPConnection,
)


class FakeChromium:
    def __init__(self, *, contexts=None, error=None):
        self.contexts = contexts or []
        self.error = error

    def connect_over_cdp(self, _url):
        if self.error is not None:
            raise self.error
        return types.SimpleNamespace(contexts=self.contexts)


class FakeRuntime:
    def __init__(self, chromium):
        self.chromium = chromium
        self.stopped = False

    def stop(self):
        self.stopped = True


class FakeManager:
    def __init__(self, runtime):
        self.runtime = runtime

    def start(self):
        return self.runtime


class PartnerCenterCDPConnectionDiagnosticsTests(unittest.TestCase):
    def _playwright_modules(self, runtime):
        package = types.ModuleType("playwright")
        package.__path__ = []
        api = types.ModuleType("playwright.sync_api")
        api.sync_playwright = lambda: FakeManager(runtime)
        return {"playwright": package, "playwright.sync_api": api}

    def test_tab_count_error_is_not_masked_as_browser_connection_failure(self):
        runtime = FakeRuntime(FakeChromium(contexts=[]))
        modules = self._playwright_modules(runtime)
        with patch.dict(sys.modules, modules):
            with self.assertRaises(UploadError) as caught:
                PartnerCenterCDPConnection("http://127.0.0.1:9223", {}).\
                    __enter__()

        self.assertEqual(caught.exception.code, "PARTNER_CENTER_TAB_AMBIGUOUS")
        self.assertIn("found 0", str(caught.exception))
        self.assertTrue(runtime.stopped)

    def test_cdp_exception_is_included_but_websocket_identifier_is_redacted(self):
        failure = RuntimeError(
            "WebSocket handshake failed at "
            "ws://127.0.0.1:9223/devtools/browser/private-debug-id"
        )
        runtime = FakeRuntime(FakeChromium(error=failure))
        modules = self._playwright_modules(runtime)
        with patch.dict(sys.modules, modules):
            with self.assertRaises(UploadError) as caught:
                PartnerCenterCDPConnection("http://127.0.0.1:9223", {}).\
                    __enter__()

        self.assertEqual(caught.exception.code, "BROWSER_CONNECTION_FAILED")
        self.assertIn("RuntimeError", str(caught.exception))
        self.assertIn("<CDP WebSocket URL redacted>", str(caught.exception))
        self.assertNotIn("private-debug-id", str(caught.exception))
        self.assertNotIn("127.0.0.1:9223", str(caught.exception))
        self.assertTrue(runtime.stopped)

    def test_one_partner_center_tab_attaches_successfully(self):
        page = types.SimpleNamespace(url=f"{PARTNER_ORIGIN}/en-us/dashboard/apps-and-games/overview")
        runtime = FakeRuntime(FakeChromium(
            contexts=[types.SimpleNamespace(pages=[page])]
        ))
        modules = self._playwright_modules(runtime)
        with patch.dict(sys.modules, modules):
            port = PartnerCenterCDPConnection("http://127.0.0.1:9223", {}).__enter__()

        self.assertIsInstance(port, PartnerCenterBrowserPort)
        self.assertIs(port.page, page)


if __name__ == "__main__":
    unittest.main()
