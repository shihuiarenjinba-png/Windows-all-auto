"""Expiry regression: GitHub flag alone cannot authorize local artifact IO."""
from datetime import datetime, timezone
import unittest

from scripts import mixed_artifact_expiry as expiry


class MixedArtifactExpiryTests(unittest.TestCase):
    def setUp(self):
        self.job = {"factory_artifact_expiry_utc": "2026-11-02T12:15:44Z"}
        self.artifact = {
            "expires_at": "2026-11-02T12:15:44Z",
            "expired": False,
        }
        self.before = datetime(2026, 10, 30, 0, 0, tzinfo=timezone.utc)

    def test_exact_future_expiry_passes(self):
        self.assertEqual(
            expiry.validate(self.job, self.artifact, now=self.before),
            "2026-11-02T12:15:44+00:00",
        )

    def test_missing_central_expiry_holds(self):
        with self.assertRaisesRegex(expiry.ExpiryHold, "UNVERIFIED"):
            expiry.validate({}, self.artifact, now=self.before)

    def test_missing_remote_expiry_holds(self):
        with self.assertRaisesRegex(expiry.ExpiryHold, "UNVERIFIED"):
            expiry.validate(self.job, {"expired": False}, now=self.before)

    def test_mismatched_expiry_holds(self):
        self.artifact["expires_at"] = "2026-11-03T12:15:44Z"
        with self.assertRaisesRegex(expiry.ExpiryHold, "CONFLICT"):
            expiry.validate(self.job, self.artifact, now=self.before)

    def test_expired_flag_holds_even_before_deadline(self):
        self.artifact["expired"] = True
        with self.assertRaisesRegex(expiry.ExpiryHold, "EXPIRED"):
            expiry.validate(self.job, self.artifact, now=self.before)

    def test_clock_expiry_holds_even_if_flag_is_false(self):
        now = datetime(2026, 11, 2, 12, 15, 44, tzinfo=timezone.utc)
        with self.assertRaisesRegex(expiry.ExpiryHold, "EXPIRED"):
            expiry.validate(self.job, self.artifact, now=now)

    def test_malformed_and_naive_expiry_holds(self):
        for value in ("not-a-date", "2026-11-02T12:15:44", None):
            with self.subTest(value=value):
                self.artifact["expires_at"] = value
                with self.assertRaisesRegex(expiry.ExpiryHold, "UNVERIFIED"):
                    expiry.validate(self.job, self.artifact, now=self.before)


if __name__ == "__main__":
    unittest.main()
