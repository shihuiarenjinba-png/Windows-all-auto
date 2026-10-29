"""Offline CDP contract regressions: no Edge, network, credentials, or CAS."""
import json
import unittest
from unittest.mock import MagicMock

from scripts.partner_center_cdp import (
    CdpPage, PartnerCenterDriver, PartnerCenterHold, REGISTRATION_LABELS,
)


def job(lane, registration):
    return {
        "display_name": "Sample Product",
        "product_type": lane,
        "registration_type": registration,
        "partner_center_selection": REGISTRATION_LABELS[registration],
        "request_id": "sample-123",
        "slug": "sample-product",
        "source_repository": "owner/factory",
        "source_branch": "codex/sample",
        "source_sha": "a" * 40,
        "identity_return_target": "products/sample-product/store/approved-identity.json",
        "allow_local_product_creation": True,
    }


class PartnerCenterRegistrationTests(unittest.TestCase):
    def driver(self):
        driver = PartnerCenterDriver.__new__(PartnerCenterDriver)
        driver.page = MagicMock()
        driver.page.target_id = "target"
        driver.page.search_product.side_effect = [0, 1]
        driver.page.open_identity.return_value = {
            "store_id": "9NTEST", "reserved_display_name": "Sample Product",
            "identity_name": "Publisher.Sample",
            "publisher": "CN=Publisher",
            "publisher_display_name": "Publisher",
            "package_family_name": "Publisher.Sample_abcdef",
            "package_sid": "S-1-15-2-1",
        }
        driver.page.safe_snapshot.return_value = {
            "url": "https://partner.microsoft.com/dashboard/products/sample",
            "title": "Product identity",
        }
        return driver

    def test_each_registration_label_routes_exactly(self):
        cases = [
            ("APP", "MSIX_OR_PWA_APP"),
            ("APP", "EXE_OR_MSI_APP"),
            ("GAME", "GDK_GAME"),
            ("GAME_3D", "MSIX_OR_PWA_GAME"),
        ]
        for lane, registration in cases:
            with self.subTest(lane=lane, registration=registration):
                driver = self.driver()
                receipt, observation = driver.process(job(lane, registration))
                driver.page._create_product.assert_called_once_with(
                    "Sample Product", REGISTRATION_LABELS[registration]
                )
                self.assertEqual(receipt["registration_type"], registration)
                self.assertEqual(observation.creation_status, "CREATED")

    def test_cross_lane_or_wrong_label_fails_before_browser(self):
        for lane, registration in [
            ("APP", "GDK_GAME"),
            ("GAME_3D", "EXE_OR_MSI_APP"),
            ("UNKNOWN", "MSIX_OR_PWA_APP"),
        ]:
            with self.subTest(lane=lane, registration=registration):
                driver = self.driver()
                with self.assertRaisesRegex(
                    PartnerCenterHold, "HOLD_REGISTRATION_TYPE_UNRESOLVED"
                ):
                    driver.process(job(lane, registration))
                driver.page.search_product.assert_not_called()
                driver.page._create_product.assert_not_called()
        driver = self.driver()
        wrong = job("APP", "MSIX_OR_PWA_APP")
        wrong["partner_center_selection"] = "GDK game"
        with self.assertRaisesRegex(
            PartnerCenterHold, "HOLD_REGISTRATION_TYPE_UNRESOLVED"
        ):
            driver.process(wrong)
        driver.page.search_product.assert_not_called()

    def test_diagnostic_strips_url_tokens_links_and_password_fields(self):
        page = CdpPage("target", None)
        raw = {
            "url": "https://partner.microsoft.com/dashboard/products?access_token=secret#fragment",
            "title": "Products",
            "ready": "complete",
            "controls": [
                {"tag": "a", "name": "Products", "type": "", "role": "",
                 "placeholder": "", "href": "https://example.com/?token=secret"},
                {"tag": "input", "name": "secret", "type": "password",
                 "placeholder": "secret"},
                {"tag": "input", "name": "Search", "type": "search",
                 "placeholder": "Search"},
            ],
        }
        page.evaluate = MagicMock(return_value=json.dumps(raw))
        snapshot = page.safe_snapshot()
        serialized = json.dumps(snapshot)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("access_token", serialized)
        self.assertNotIn("href", serialized)
        self.assertEqual(snapshot["url"],
                         "https://partner.microsoft.com/dashboard/products")
        self.assertEqual(len(snapshot["controls"]), 2)

    def test_non_partner_host_is_not_authenticated(self):
        page = CdpPage("target", None)
        page.evaluate = MagicMock(return_value=json.dumps({
            "url": "https://login.microsoftonline.com/", "controls": []
        }))
        with self.assertRaisesRegex(
            PartnerCenterHold, "HOLD_PARTNER_CENTER_AUTH_REQUIRED"
        ):
            page.safe_snapshot()


    def test_search_control_ambiguity_does_not_submit_enter(self):
        page = CdpPage("target", None)
        page.navigate = MagicMock()
        page.safe_snapshot = MagicMock(return_value={"controls": []})
        page._wait_not_busy = MagicMock()
        page.fill_textbox = MagicMock()
        page.click_exact = MagicMock(side_effect=PartnerCenterHold(
            "HOLD_BROWSER_STATE_AMBIGUOUS"
        ))
        page.press_enter = MagicMock()
        page.exact_product_count = MagicMock(return_value=0)
        with self.assertRaisesRegex(
            PartnerCenterHold, "HOLD_BROWSER_STATE_AMBIGUOUS"
        ):
            page.search_product("Sample Product")
        page.press_enter.assert_not_called()
        page.exact_product_count.assert_not_called()

    def test_reservation_requires_explicit_availability_click(self):
        page = CdpPage("target", None)
        page.click_exact = MagicMock(side_effect=[
            "New product", "MSIX or PWA app",
            PartnerCenterHold("HOLD_BROWSER_STATE_AMBIGUOUS"),
        ])
        page._wait_not_busy = MagicMock()
        page.fill_textbox = MagicMock()
        page.evaluate = MagicMock()
        with self.assertRaisesRegex(
            PartnerCenterHold, "HOLD_BROWSER_STATE_AMBIGUOUS"
        ):
            page._create_product("Sample Product", "MSIX or PWA app")
        self.assertEqual(page.click_exact.call_count, 3)
        page.evaluate.assert_not_called()

    def test_malformed_registration_metadata_fails_closed(self):
        driver = self.driver()
        invalid = job("APP", "MSIX_OR_PWA_APP")
        invalid["registration_type"] = {"unexpected": "mapping"}
        with self.assertRaisesRegex(
            PartnerCenterHold, "HOLD_REGISTRATION_TYPE_UNRESOLVED"
        ):
            driver.process(invalid)
        driver.page.search_product.assert_not_called()

if __name__ == "__main__":
    unittest.main()
