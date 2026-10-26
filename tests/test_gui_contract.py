import unittest

from all_auto.gui import STRINGS, UI_CONTRACT, localized_text, status_summary


class GuiContractTests(unittest.TestCase):
    def test_01_four_operator_pages_are_fixed(self):
        self.assertEqual(
            UI_CONTRACT["pages"],
            ("products", "settings", "queue", "results"),
        )

    def test_02_required_windows_viewports_are_declared(self):
        self.assertIn((1024, 768), UI_CONTRACT["target_viewports"])
        self.assertIn((1280, 720), UI_CONTRACT["target_viewports"])

    def test_03_live_partner_center_is_fail_closed(self):
        self.assertFalse(UI_CONTRACT["live_partner_center_enabled"])
        for lang in ("ja", "en"):
            text = localized_text(lang, "queue_locked").lower()
            self.assertTrue("ロック" in text or "locked" in text)

    def test_04_bilingual_text_keys_match(self):
        self.assertEqual(set(STRINGS["ja"]), set(STRINGS["en"]))

    def test_05_status_summary_never_calls_ready_certified(self):
        report = {
            "total": 3,
            "counts": {
                "READY_FOR_WINDOWS_QA": 1,
                "HOLD": 1,
                "BLOCKED": 1,
            },
        }
        ja = status_summary(report, "ja")
        en = status_summary(report, "en")
        self.assertIn("QA", ja)
        self.assertIn("QA", en)
        self.assertNotIn("認定", ja)
        self.assertNotIn("certified", en.lower())

    def test_06_default_window_fits_both_target_viewports(self):
        width, height = (int(x) for x in UI_CONTRACT["default_geometry"].split("x"))
        for viewport_width, viewport_height in UI_CONTRACT["target_viewports"]:
            self.assertLessEqual(width, viewport_width)
            self.assertLessEqual(height, viewport_height)


if __name__ == "__main__":
    unittest.main()
