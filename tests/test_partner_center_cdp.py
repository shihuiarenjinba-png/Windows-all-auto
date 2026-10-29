import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, call, patch

from scripts import partner_center_cdp as cdp
from scripts.partner_center_cdp import CdpPage, PartnerCenterHold


class PartnerCenterReadinessTests(unittest.TestCase):
    def test_product_search_excludes_global_header_shadow_host(self):
        page = CdpPage("target", None)
        page.evaluate = MagicMock(return_value=json.dumps({"ok": True}))
        page.fill_textbox(["search", "search products"], "Focus Session Desk")
        script = page.evaluate.call_args.args[0]
        self.assertIn("shadowRoot", script)
        self.assertIn("pc-header-search-box", script)
        self.assertIn("wantsSearch", script)

    def test_create_menu_requires_unique_product_table_control(self):
        page = CdpPage("target", None)
        page.evaluate = MagicMock(return_value=json.dumps({"ok": True}))
        page.open_product_create_menu()
        script = page.evaluate.call_args.args[0]
        self.assertIn("offers-table lib-table-command-bar", script)
        self.assertIn("items.length!==1", script)

    def test_msix_selection_uses_exact_menuitem_label(self):
        page = CdpPage("target", None)
        page.evaluate = MagicMock(return_value=json.dumps({
            "ok": True, "name": "MSIX or PWA app",
        }))
        self.assertEqual(
            page.click_exact(["MSIX or PWA app"]), "MSIX or PWA app"
        )
        script = page.evaluate.call_args.args[0]
        self.assertIn('[role="menuitem"]', script)
        self.assertIn("info-tooltip-container", script)

    def test_navigation_timeout_is_forwarded_to_cdp_command(self):
        page = CdpPage("target", None)
        page.command = MagicMock(return_value={})
        state = json.dumps({
            "u": "https://partner.microsoft.com/dashboard/products",
            "t": "Overview", "r": "complete",
        })
        page.evaluate = MagicMock(return_value=state)
        with patch("scripts.partner_center_cdp.time.sleep"):
            page.navigate(
                "https://partner.microsoft.com/dashboard/products", timeout=45.0
            )
        self.assertEqual(page.command.call_args_list[1], call(
            "Page.navigate",
            {"url": "https://partner.microsoft.com/dashboard/products"},
            timeout=45.0,
        ))

    def test_websocket_timeout_becomes_fail_closed_hold(self):
        class FakeWebSocketException(Exception):
            pass

        class FakeWebSocketTimeoutException(FakeWebSocketException):
            pass

        socket = MagicMock()
        socket.recv.side_effect = FakeWebSocketTimeoutException("timeout")
        page = CdpPage("target", socket)
        fake_websocket = SimpleNamespace(
            WebSocketException=FakeWebSocketException,
            WebSocketTimeoutException=FakeWebSocketTimeoutException,
        )
        with patch.object(cdp, "websocket", fake_websocket):
            with self.assertRaisesRegex(
                    PartnerCenterHold, "HOLD_BROWSER_COMMAND_TIMEOUT"):
                page.command("Page.navigate", {"url": "https://example.invalid"})

    def test_stable_nonblocking_controls_are_ready(self):
        page = CdpPage("target", None)
        sample = json.dumps({
            "ready": "complete", "blocking": 0,
            "signature": "overview-with-products",
        })
        with patch.object(page, "evaluate", return_value=sample), \
             patch("scripts.partner_center_cdp.time.sleep"), \
             patch("scripts.partner_center_cdp.time.monotonic",
                   side_effect=[0.0, 0.0, 0.01, 0.02]):
            page._wait_not_busy(timeout=1.0)

    def test_real_busy_indicator_still_times_out(self):
        page = CdpPage("target", None)
        sample = json.dumps({
            "ready": "complete", "blocking": 1,
            "signature": "still-loading",
        })
        with patch.object(page, "evaluate", return_value=sample), \
             patch("scripts.partner_center_cdp.time.sleep"), \
             patch("scripts.partner_center_cdp.time.monotonic",
                   side_effect=[0.0, 0.0, 0.6, 1.1]):
            with self.assertRaisesRegex(
                    PartnerCenterHold, "HOLD_BROWSER_LOAD_TIMEOUT"):
                page._wait_not_busy(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
