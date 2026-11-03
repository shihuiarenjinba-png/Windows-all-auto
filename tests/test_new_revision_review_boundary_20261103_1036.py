"""Fail-closed checks for new review revisions, separate from immutable provenance."""
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"


class NewRevisionEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.review = cls.data["revision_review_reconciliation"]
        cls.current = cls.review["current_four_lane_observation"]
        cls.new = cls.review["latest_20261103_1036_new_product_revision_observation"]

    def test_current_review_heads_not_old(self):
        self.assertEqual(self.current["app"]["us_freelance_ledger_product_review_pr"], 84)
        self.assertEqual(self.current["game"]["factory_review_pr"], 20)
        self.assertEqual(self.current["three_d"]["factory_pr"], 23)
        self.assertNotEqual(self.new["app"]["head_prefix"], self.new["app"]["previous_review_head"][:8])
        self.assertNotEqual(self.new["three_d"]["head_prefix"], self.new["three_d"]["previous_source_sha"][:7])

    def test_qa_only_not_promoted_or_store_package(self):
        self.assertFalse(self.new["guards"]["qa_only_artifacts_are_store_packages"])
        self.assertFalse(self.current["app"]["us_freelance_ledger_qa_zip_independent_36_verified"])
        self.assertFalse(self.current["game"]["new_qa_independent_36_rehash"])
        self.assertFalse(self.current["three_d"]["new_revision_independent_36_byte_rehash"])

    def test_no_cross_lane_registration_or_source_rebind(self):
        self.assertEqual(self.new["game"]["registration_type"], "GDK_GAME")
        self.assertEqual(self.new["game"]["immutable_source_sha"], self.current["game"]["original_source_sha"])
        self.assertNotEqual(self.new["three_d"]["head_prefix"], self.new["game"]["head_prefix"])
        self.assertNotEqual(self.new["app"]["head_prefix"], self.new["three_d"]["head_prefix"])
        self.assertFalse(self.new["guards"]["approved_identity_rebind"])

    def test_legacy_identity_cannot_be_new_cas(self):
        self.assertFalse(self.new["three_d"]["legacy_identity_is_new_revision_cas"])
        self.assertFalse(self.new["guards"]["cas_applied"])
        self.assertFalse(self.current["three_d"]["new_revision_cas"])

    def test_no_false_physical_or_package_pass(self):
        for key in ("physical_windows", "real_signed_msix", "gdk_msixvc", "package_version_approved"):
            self.assertFalse(self.new["guards"][key])
        self.assertEqual(self.new["guards"]["local_code_sync"], "CLOUD_PASS_ONLY")

    def test_historical_observation_retained(self):
        old = self.review["historical_four_lane_observation_before_20261103_1036"]
        self.assertEqual(old["app"]["us_freelance_ledger_product_review_pr"], 82)
        self.assertEqual(old["game"]["factory_review_pr"], 18)
        self.assertEqual(old["three_d"]["factory_pr"], 22)

if __name__ == "__main__":
    unittest.main()
