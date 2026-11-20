from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from all_auto.store_product_handoff import (
    StoreHandoffError,
    apply_recovered_initial_submission_receipt,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "folder_engine_paid_trial_handoff_v2.json"
)


def load_handoff():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def recovered_receipt(**overrides):
    values = {
        "schema_version": "existing-store-initial-submission-reconcile-receipt/1",
        "status": "INITIAL_SUBMISSION_DRAFT_PRESENT_RECOVERED",
        "submission_state": "EXISTING_PRODUCT_DRAFT_PRESENT",
        "store_id": "9P99MJX1R4V6",
        "draft_id": "1152921505702999999",
        "draft_url": (
            "https://partner.microsoft.com/en-us/dashboard/products/"
            "9P99MJX1R4V6/submissions/1152921505702999999"
        ),
        "retry_candidate": False,
        "retry_authorized": False,
        "write_performed": False,
        "start_submission_clicked": False,
        "package_uploaded": False,
        "pricing_changed": False,
        "submitted": False,
        "published": False,
    }
    values.update(overrides)
    return values


class RecoveredInitialSubmissionReceiptTests(unittest.TestCase):
    def test_binds_manual_recovered_draft_without_claiming_automation_click(self):
        handoff = load_handoff()
        normalized = apply_recovered_initial_submission_receipt(
            handoff, recovered_receipt()
        )
        self.assertEqual(
            normalized["product"]["draft_id"], "1152921505702999999"
        )
        self.assertEqual(
            normalized["product"]["initial_submission_start_source"],
            "owner_manual_reconciled",
        )
        self.assertEqual(
            normalized["product"]["initial_submission_receipt_status"],
            "INITIAL_SUBMISSION_DRAFT_PRESENT_RECOVERED",
        )
        self.assertTrue(
            normalized["approvals"]["initial_submission_start_completed"]
        )

    def test_rejects_store_id_mismatch(self):
        with self.assertRaisesRegex(StoreHandoffError, "store_id mismatch"):
            apply_recovered_initial_submission_receipt(
                load_handoff(), recovered_receipt(store_id="WRONG")
            )

    def test_rejects_write_performed_true(self):
        with self.assertRaisesRegex(StoreHandoffError, "write_performed"):
            apply_recovered_initial_submission_receipt(
                load_handoff(), recovered_receipt(write_performed=True)
            )

    def test_rejects_start_submission_clicked_true(self):
        with self.assertRaisesRegex(StoreHandoffError, "start_submission_clicked"):
            apply_recovered_initial_submission_receipt(
                load_handoff(), recovered_receipt(start_submission_clicked=True)
            )

    def test_rejects_mismatched_draft_url(self):
        with self.assertRaisesRegex(StoreHandoffError, "draft_url mismatch"):
            apply_recovered_initial_submission_receipt(
                load_handoff(),
                recovered_receipt(
                    draft_url=(
                        "https://partner.microsoft.com/en-us/dashboard/products/"
                        "9P99MJX1R4V6/submissions/123"
                    )
                ),
            )

    def test_rejects_non_numeric_draft_id(self):
        with self.assertRaisesRegex(StoreHandoffError, "draft_id is invalid"):
            apply_recovered_initial_submission_receipt(
                load_handoff(),
                recovered_receipt(draft_id="not-a-draft"),
            )


if __name__ == "__main__":
    unittest.main()
