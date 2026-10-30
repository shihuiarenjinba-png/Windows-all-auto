"""Offline guard tests for opt-in mixed APP executor (no browser or CAS)."""
from contextlib import redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch

from scripts import run_local_partner_center_batch as host


class MixedSerialExecutorContractTests(unittest.TestCase):
    def setUp(self):
        self.job = {"request_id": "app-text-123", "slug": "offline-text-diff-desk"}
        self.receipt = {
            "store_id": "9PTESTEXAMPLE", "package_family_name": "Test.App_abcdefghijklm",
        }
        self.ledger = {"rotation_cohorts": {
            "app_jobs": [
                dict(self.job),
                {"request_id": "app-focus-123", "identity_store_id": "9PFOCUS",
                 "identity_pfn": "Focus.App_abcdefghijklm"},
            ],
            "three_d_jobs": [
                {"request_id": "3d-prism-123", "identity_store_id": "9PPRISM",
                 "identity_pfn": "Prism.Game_abcdefghijklm"},
            ],
            "game_jobs": [],
        }}
        self.state = {"products": [
            {"request_id": "app-text-123", "result": None},
            {"request_id": "app-image-123", "result": {
                "store_id": "9PIMAGE", "pfn": "Image.App_abcdefghijklm",
            }},
        ]}

    def test_unique_identity_passes(self):
        host.reject_mixed_identity_collision(
            self.ledger, self.job, self.receipt, self.state
        )

    def test_duplicate_post_store_id_rejected_before_cas(self):
        self.receipt["store_id"] = "9PFOCUS"
        with self.assertRaisesRegex(host.RunnerHold, "HOLD_MIXED_CROSS_PRODUCT_IDENTITY"):
            host.reject_mixed_identity_collision(
                self.ledger, self.job, self.receipt, self.state
            )

    def test_cross_lane_pfn_rejected_before_cas(self):
        self.receipt["package_family_name"] = "Prism.Game_abcdefghijklm"
        with self.assertRaisesRegex(host.RunnerHold, "HOLD_MIXED_CROSS_PRODUCT_IDENTITY"):
            host.reject_mixed_identity_collision(
                self.ledger, self.job, self.receipt, self.state
            )

    def test_completed_pre_collision_rejected_before_cas(self):
        self.receipt["store_id"] = "9PIMAGE"
        with self.assertRaisesRegex(host.RunnerHold, "HOLD_MIXED_CROSS_PRODUCT_IDENTITY"):
            host.reject_mixed_identity_collision(
                self.ledger, self.job, self.receipt, self.state
            )

    def test_missing_identity_rejected(self):
        self.receipt["store_id"] = ""
        with self.assertRaisesRegex(host.RunnerHold, "HOLD_MIXED_IDENTITY_SCHEMA"):
            host.reject_mixed_identity_collision(
                self.ledger, self.job, self.receipt, self.state
            )

    def test_opt_in_executor_not_claimed_as_pass(self):
        output = StringIO()
        with patch.object(host, "execute_mixed_serial", return_value={
            "status": "MIXED_LOCAL_COMPLETE_AWAITING_HOST_ATTESTATION",
            "store_submission": "NOT_PERFORMED",
            "task_scheduler_registration_allowed": False,
        }) as run, redirect_stdout(output):
            code = host.main(["--execute-mixed"])
        self.assertEqual(code, 2)
        self.assertEqual(run.call_count, 1)
        self.assertFalse(json.loads(output.getvalue())["task_scheduler_registration_allowed"])

    def test_conflicting_modes_fail_before_browser(self):
        output = StringIO()
        with patch.object(host, "execute_mixed_serial") as run, redirect_stdout(output):
            code = host.main(["--execute-mixed", "--audit-queue"])
        self.assertEqual(code, 2)
        run.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["reason"],
                         "HOLD_CONFLICTING_READ_ONLY_MODES")


if __name__ == "__main__":
    unittest.main()
