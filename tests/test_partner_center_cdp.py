import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts import partner_center_cdp as cdp
from scripts.partner_center_cdp import (
    CdpPage, PARTNER_PRODUCTS_URL, PartnerCenterHold, _is_products_overview,
)


class PartnerCenterReadinessTests(unittest.TestCase):
    def test_create_product_rechecks_overview_without_repeating_reserve(self):
        page = CdpPage("target", None)
        page.open_product_create_menu = MagicMock()
        page._wait_not_busy = MagicMock()
        page.fill_textbox = MagicMock()
        page.click_exact = MagicMock()
        page.evaluate = MagicMock(return_value={
            "available": True, "unavailable": False,
        })
        page._wait_product_creation_outcome = MagicMock(
            side_effect=PartnerCenterHold("HOLD_PRODUCT_CREATE_NOT_CONFIRMED")
        )
        page.search_product = MagicMock(return_value=1)

        page._create_product("File Integrity Ledger")

        page.search_product.assert_called_once_with("File Integrity Ledger")
        reserve_calls = [
            call for call in page.click_exact.call_args_list
            if call.args == (["Reserve product name"],)
        ]
        self.assertEqual(len(reserve_calls), 1)

    def test_create_product_still_holds_when_overview_has_no_match(self):
        page = CdpPage("target", None)
        page.open_product_create_menu = MagicMock()
        page._wait_not_busy = MagicMock()
        page.fill_textbox = MagicMock()
        page.click_exact = MagicMock()
        page.evaluate = MagicMock(return_value={
            "available": True, "unavailable": False,
        })
        page._wait_product_creation_outcome = MagicMock(
            side_effect=PartnerCenterHold("HOLD_PRODUCT_CREATE_NOT_CONFIRMED")
        )
        page.search_product = MagicMock(return_value=0)

        with self.assertRaisesRegex(
                PartnerCenterHold, "HOLD_PRODUCT_CREATE_NOT_CONFIRMED"):
            page._create_product("File Integrity Ledger")

    def test_open_identity_reuses_already_visible_identity(self):
        page = CdpPage("target", None)
        identity = {"store_id": "9P6452C61N7B"}
        page._open_exact_product = MagicMock()
        page._wait_not_busy = MagicMock()
        page._identity_values = MagicMock(return_value=identity)
        page.safe_snapshot = MagicMock(return_value={})
        page.click_exact = MagicMock()

        self.assertEqual(page.open_identity("Focus Session Desk"), identity)

        page.click_exact.assert_not_called()
        page._identity_values.assert_called_once_with("Focus Session Desk")

    def test_open_identity_expands_only_when_values_are_not_visible(self):
        page = CdpPage("target", None)
        identity = {"store_id": "9P6452C61N7B"}
        page._open_exact_product = MagicMock()
        page._wait_not_busy = MagicMock()
        page._identity_values = MagicMock(side_effect=[
            PartnerCenterHold("HOLD_IDENTITY_DETAILS_AMBIGUOUS"), identity,
        ])
        page.safe_snapshot = MagicMock(return_value={})
        page.wait_for_exact_control = MagicMock(
            return_value="Toggle Product identity"
        )
        page.click_exact = MagicMock(return_value="Toggle Product identity")

        self.assertEqual(page.open_identity("Focus Session Desk"), identity)

        page.click_exact.assert_called_once_with(["Toggle Product identity"])
        self.assertEqual(page._identity_values.call_count, 2)

    def test_open_identity_does_not_mask_post_toggle_load_hold(self):
        page = CdpPage("target", None)
        page._open_exact_product = MagicMock()
        page._wait_not_busy = MagicMock(side_effect=[
            None, PartnerCenterHold("HOLD_BROWSER_LOAD_TIMEOUT"),
        ])
        page._identity_values = MagicMock(
            side_effect=PartnerCenterHold("HOLD_IDENTITY_DETAILS_AMBIGUOUS")
        )
        page.wait_for_exact_control = MagicMock(
            return_value="Toggle Product identity"
        )
        page.click_exact = MagicMock(return_value="Toggle Product identity")

        with self.assertRaisesRegex(PartnerCenterHold,
                                    "HOLD_BROWSER_LOAD_TIMEOUT"):
            page.open_identity("Focus Session Desk")

        page.click_exact.assert_called_once_with(["Toggle Product identity"])

    def test_submission_draft_reuses_existing_same_product_link(self):
        page = CdpPage("target", None)
        page._open_exact_product = MagicMock()
        page._wait_not_busy = MagicMock()
        page._submission_draft_state = MagicMock(return_value={
            "product_id": "9P6452C61N7B",
            "current_submission_id": None,
            "submission_links": [{"name": "242", "href": "same-product"}],
            "start_submission_count": 0,
        })
        page.click_exact = MagicMock()

        self.assertEqual(
            page.ensure_submission_draft_open("Focus Session Desk"),
            "ALREADY_OPEN",
        )
        page.click_exact.assert_not_called()

    def test_submission_draft_clicks_start_only_once_then_confirms(self):
        page = CdpPage("target", None)
        page._open_exact_product = MagicMock()
        page._wait_not_busy = MagicMock()
        page._submission_draft_state = MagicMock(side_effect=[
            {
                "product_id": "9P6452C61N7B",
                "current_submission_id": None,
                "submission_links": [],
                "start_submission_count": 1,
            },
            {
                "product_id": "9P6452C61N7B",
                "current_submission_id": "1152921505702265161",
                "submission_links": [],
                "start_submission_count": 0,
            },
        ])
        page.click_exact = MagicMock()

        self.assertEqual(
            page.ensure_submission_draft_open("Focus Session Desk"), "OPENED"
        )
        page.click_exact.assert_called_once_with(["Start submission"])

    def test_identity_control_waits_for_async_render(self):
        page = CdpPage("target", None)
        page._visible_controls = MagicMock(side_effect=[
            [], [{"name": "Toggle Product identity"}],
        ])

        with patch("scripts.partner_center_cdp.time.sleep"), \
             patch("scripts.partner_center_cdp.time.monotonic",
                   side_effect=[0.0, 0.0, 0.1]):
            result = page.wait_for_exact_control(
                ["Toggle Product identity"], timeout=1.0
            )

        self.assertEqual(result, "Toggle Product identity")
        self.assertEqual(page._visible_controls.call_count, 2)

    def test_product_creation_waits_for_exact_product_overview(self):
        page = CdpPage("target", None)
        state = json.dumps({
            "url": "https://partner.microsoft.com/en-us/dashboard/products/9P6452C61N7B/overview",
            "title": "Application overview | Focus Session Desk | Partner Center",
            "ready": "complete",
        })
        page.evaluate = MagicMock(return_value=state)
        with patch("scripts.partner_center_cdp.time.sleep"):
            page._wait_product_creation_outcome("Focus Session Desk")

    def test_current_identity_card_maps_seven_exact_fields(self):
        page = CdpPage("target", None)
        values = {
            "store_id": ["9P6452C61N7B"],
            "reserved_display_name": ["Focus Session Desk"],
            "identity_name": ["OkinawaDesktopTools.FocusSessionDesk"],
            "publisher": ["CN=46263F21-A700-41DB-8C9B-114C22FB82FC"],
            "publisher_display_name": ["Okinawa Desktop Tools"],
            "package_family_name": [
                "OkinawaDesktopTools.FocusSessionDesk_j8yefg9jgfh58"
            ],
            "package_sid": [
                "S-1-15-2-2225260970-543926136-1440257008-848151149-"
                "3671298483-3004677799-2420668959"
            ],
        }
        page.evaluate = MagicMock(return_value=json.dumps(values))
        result = page._identity_values("Focus Session Desk")
        self.assertEqual(result["store_id"], "9P6452C61N7B")
        self.assertEqual(result["reserved_display_name"], "Focus Session Desk")
        script = page.evaluate.call_args.args[0]
        self.assertIn("Package/Identity/Name", script)
        self.assertIn("Package/Properties/PublisherDisplayName", script)
        self.assertIn("Package Family Name (PFN)", script)

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
        self.assertTrue(page.evaluate.call_args.kwargs["user_gesture"])

    def test_navigation_uses_same_host_location_assignment(self):
        page = CdpPage("target", None)
        page.command = MagicMock(return_value={})
        state = json.dumps({
            "u": "https://partner.microsoft.com/dashboard/products",
            "t": "Overview", "r": "complete",
        })
        page.current_target_url = MagicMock(return_value=(
            "https://partner.microsoft.com/dashboard/v2/home"
        ))
        page.evaluate = MagicMock(side_effect=[
            True,
            state, state, state, state,
        ])
        with patch("scripts.partner_center_cdp.time.sleep"):
            page.navigate(
                "https://partner.microsoft.com/dashboard/products", timeout=45.0
            )
        page.command.assert_not_called()
        assignment = page.evaluate.call_args_list[0].args[0]
        self.assertIn("location.assign", assignment)
        self.assertIn(PARTNER_PRODUCTS_URL, assignment)

    def test_open_product_uses_unique_validated_overview_href(self):
        page = CdpPage("target", None)
        target = (
            "https://partner.microsoft.com/en-us/dashboard/products/"
            "9PGZ445SR5GM/overview"
        )
        page._visible_controls = MagicMock(return_value=[{
            "tag": "a", "name": "File Integrity Ledger",
            "href": "/en-us/dashboard/products/9PGZ445SR5GM/overview",
        }])
        page.pointer_click_exact_link = MagicMock()
        page._wait_product_creation_outcome = MagicMock()
        page._wait_not_busy = MagicMock()

        page._open_exact_product("File Integrity Ledger")

        page.pointer_click_exact_link.assert_called_once_with(
            "File Integrity Ledger"
        )
        page._wait_product_creation_outcome.assert_called_once_with(
            "File Integrity Ledger", timeout=90.0,
            failure_code="HOLD_PRODUCT_OPEN_NOT_CONFIRMED",
        )

    def test_open_product_rejects_cross_host_href(self):
        page = CdpPage("target", None)
        page._visible_controls = MagicMock(return_value=[{
            "tag": "a", "name": "File Integrity Ledger",
            "href": "https://example.invalid/products/9PGZ445SR5GM/overview",
        }])
        with self.assertRaisesRegex(PartnerCenterHold,
                                    "HOLD_PRODUCT_LINK_AMBIGUOUS"):
            page._open_exact_product("File Integrity Ledger")

    def test_pointer_link_click_dispatches_one_trusted_click(self):
        page = CdpPage("target", None)
        page.evaluate = MagicMock(return_value=json.dumps({
            "ok": True, "x": 120.5, "y": 240.25,
        }))
        page.command = MagicMock(return_value={})

        page.pointer_click_exact_link("File Integrity Ledger")

        self.assertEqual(page.command.call_count, 2)
        self.assertEqual(
            [call.args[1]["type"] for call in page.command.call_args_list],
            ["mousePressed", "mouseReleased"],
        )

    def test_current_localized_overview_is_not_reloaded(self):
        page = CdpPage("target", None)
        page.command = MagicMock(return_value={})
        page.current_target_url = MagicMock(return_value=(
            "https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview"
        ))
        page.navigate(PARTNER_PRODUCTS_URL)
        page.command.assert_not_called()

    def test_product_page_returns_via_trusted_apps_breadcrumb(self):
        page = CdpPage("target", None)
        overview = json.dumps({
            "u": "https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview",
            "t": "Overview | Apps and games | Partner Center",
            "r": "complete",
        })
        page.current_target_url = MagicMock(return_value=(
            "https://partner.microsoft.com/en-us/dashboard/products/"
            "9PGZ445SR5GM/overview"
        ))
        page.evaluate = MagicMock(side_effect=[
            overview, overview, overview, overview,
        ])
        page.pointer_click_exact_link = MagicMock()
        with patch("scripts.partner_center_cdp.time.sleep"):
            page.navigate(PARTNER_PRODUCTS_URL)

        page.pointer_click_exact_link.assert_called_once_with("Apps and games")

    def test_navigation_does_not_accept_stable_previous_page(self):
        page = CdpPage("target", None)
        target = (
            "https://partner.microsoft.com/en-us/dashboard/products/"
            "9PGZ445SR5GM/overview"
        )
        old = json.dumps({
            "u": "https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview",
            "t": "Overview", "r": "complete",
        })
        reached = json.dumps({
            "u": target,
            "t": "Application overview | File Integrity Ledger | Partner Center",
            "r": "complete",
        })
        page.current_target_url = MagicMock(return_value=(
            "https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview"
        ))
        page.evaluate = MagicMock(side_effect=[
            True, old, old, old, reached, reached, reached, reached,
        ])
        with patch("scripts.partner_center_cdp.time.sleep"):
            page.navigate(target)

        self.assertGreaterEqual(page.evaluate.call_count, 8)

    def test_only_known_products_overview_paths_are_equivalent(self):
        self.assertTrue(_is_products_overview(PARTNER_PRODUCTS_URL))
        self.assertTrue(_is_products_overview(
            "https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview"
        ))
        self.assertFalse(_is_products_overview(
            "https://partner.microsoft.com/en-us/dashboard/products/ABC/overview"
        ))
        self.assertFalse(_is_products_overview(
            "https://login.microsoftonline.com/common/oauth2/authorize"
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
                    PartnerCenterHold,
                    "HOLD_BROWSER_COMMAND_TIMEOUT:Page.navigate"):
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
