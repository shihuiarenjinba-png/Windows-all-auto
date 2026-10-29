import json
import unittest
from unittest.mock import patch

from scripts.partner_center_cdp import CdpPage, PartnerCenterHold


class PartnerCenterReadinessTests(unittest.TestCase):
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
