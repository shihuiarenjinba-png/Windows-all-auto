"""Identity state machine regression for the central E2E ledger."""
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"


class IdentityStateSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.summary = cls.data["identity_state_summary_20261105"]
        cls.states = cls.summary["states"]

    def names(self, state):
        return {item["product"] for item in self.states[state]}

    def test_exact_three_state_schema_and_no_overlap(self):
        self.assertEqual(
            set(self.states),
            {"POST_IDENTITY_UPGRADE", "PRE_IDENTITY_FIX_REQUIRED", "WAITING_USER_IDENTITY"},
        )
        groups = [self.names(key) for key in self.states]
        self.assertEqual(len(set().union(*groups)), sum(len(group) for group in groups))

    def test_known_identity_products_never_regress_to_waiting(self):
        post = self.names("POST_IDENTITY_UPGRADE")
        waiting = self.names("WAITING_USER_IDENTITY")
        for product in (
            "Focus Session Desk",
            "File Integrity Ledger",
            "Signal Sprint",
            "Prism Route 3D",
        ):
            self.assertIn(product, post)
            self.assertNotIn(product, waiting)

    def test_current_non_identity_products_are_not_falsely_marked_waiting(self):
        fix = self.names("PRE_IDENTITY_FIX_REQUIRED")
        for product in (
            "Offline Text Diff Desk",
            "Offline Image Inventory Desk",
            "Offline Notes Canary",
            "Freelance Ledger JP",
            "US Freelance Ledger",
            "Double-Entry Bookkeeping Desk JP",
            "Double-Entry Bookkeeping Desk US",
        ):
            self.assertIn(product, fix)

    def test_waiting_identity_is_empty_until_identity_is_only_blocker(self):
        self.assertEqual(self.states["WAITING_USER_IDENTITY"], [])
        invariants = " ".join(self.summary["invariants"])
        self.assertIn("sole remaining PRE blocker", invariants)

    def test_store_safety_and_sale_gate_remain_separate(self):
        invariants = " ".join(self.summary["invariants"])
        self.assertIn("Store upload/final submit/publish/pricing remain prohibited", invariants)
        self.assertIn("below 80/100", invariants)


if __name__ == "__main__":
    unittest.main()
