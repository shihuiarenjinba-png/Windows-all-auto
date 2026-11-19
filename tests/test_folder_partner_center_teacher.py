from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FolderPartnerCenterTeacherTests(unittest.TestCase):
    def setUp(self):
        self.receipt = json.loads(
            (
                ROOT
                / "ops"
                / "folder_engine_partner_center_teacher_20261118.json"
            ).read_text(encoding="utf-8")
        )

    def test_exact_product_and_pricing_postconditions_are_fixed(self):
        self.assertEqual(
            self.receipt["schema_version"],
            "partner-center-teacher-receipt/1",
        )
        self.assertEqual(self.receipt["product"]["store_id"], "9P99MJX1R4V6")
        self.assertEqual(
            self.receipt["product"]["draft_id"], "1152921505702423660"
        )
        pricing = self.receipt["page_models"]["pricing"]
        self.assertEqual(pricing["expected"]["model"], "paid_one_time")
        self.assertEqual(pricing["expected"]["currency"], "JPY - Japan")
        self.assertEqual(pricing["expected"]["retail_price"], "360")
        self.assertEqual(pricing["expected"]["free_trial"], "none")
        self.assertTrue(pricing["save_performed"])
        self.assertEqual(
            pricing["reload_postconditions"]["overview_section_state"],
            "Complete",
        )
        self.assertEqual(
            pricing["reload_postconditions"]["audience"], "Private audience"
        )
        self.assertEqual(
            pricing["reload_postconditions"]["known_user_group"],
            "Folder Automation Engine Private QA",
        )

    def test_customer_group_page_is_deterministic_and_redacts_member(self):
        group = self.receipt["page_models"]["customer_group_create"]
        self.assertEqual(group["fields"]["group_name"], "groupName")
        self.assertEqual(group["fields"]["members"], "NewFlightGroup_Emails")
        self.assertEqual(group["save_button"], "createNewFlightGroupSubmit")
        self.assertTrue(group["create_new_group_must_not_repeat"])
        self.assertEqual(group["member_source"], "CURRENT_PARTNER_CENTER_ACCOUNT")
        self.assertFalse(group["persist_member_value"])
        self.assertTrue(group["member_transmission_confirmed"])
        self.assertTrue(group["create_save_performed"])
        self.assertEqual(group["reload_postconditions"]["customer_count"], 1)
        self.assertFalse(
            group["reload_postconditions"]["duplicate_group_detected"]
        )
        serialized = json.dumps(self.receipt)
        self.assertNotIn("@", serialized)

    def test_private_audience_save_and_reload_are_fixed(self):
        audience = self.receipt["page_models"]["private_audience"]
        self.assertEqual(
            audience["private_radio_id"],
            "radioDistribution_PrivateBetaAudience",
        )
        self.assertEqual(
            audience["expected_group"], "Folder Automation Engine Private QA"
        )
        self.assertTrue(audience["save_performed"])
        self.assertTrue(
            audience["reload_postconditions"]["private_audience_selected"]
        )
        self.assertTrue(
            audience["reload_postconditions"]["expected_group_checked"]
        )
        self.assertEqual(
            audience["reload_postconditions"]["retail_price"], "360"
        )

    def test_current_hold_prevents_upload_and_certification(self):
        self.assertEqual(
            self.receipt["current_state"],
            "OWNER_VISUAL_APPROVAL_REQUIRED",
        )
        safety = self.receipt["safety"]
        self.assertFalse(safety["start_submission_repeated"])
        self.assertFalse(safety["old_msix_used"])
        self.assertFalse(safety["package_uploaded"])
        self.assertFalse(safety["certification_executed"])
        self.assertFalse(safety["publish_executed"])


if __name__ == "__main__":
    unittest.main()
