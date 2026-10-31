"""Fail-closed accounting review boundary before authenticated Factory reads."""
import unittest
from unittest.mock import patch

from scripts.accounting_immutable_github_reader import (
    AccountingImmutableReadHold,
    check_accounting_e2e_with_authenticated_factory,
)


class AccountingReviewBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.job = {
            "slug": "jp-freelance-ledger",
            "product_type": "APP",
            "source_repository": "shihuiarenjinba-png/AI-App-Factory",
            "source_branch": "codex/promoted-accounting",
            "source_sha": "a" * 40,
            "request_id": "app-jp-freelance-ledger-" + "a" * 12,
            "identity_return_target":
                "products/jp-freelance-ledger/store/approved-identity.json",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "market_fit_gate": "MARKET_FIT_PASS",
            "market_fit_evidence_verified": True,
            "status": "PRE_IDENTITY_READY",
        }

    @patch("scripts.accounting_immutable_github_reader.subprocess.run")
    @patch("scripts.market_fit_review_reader.assess_reviewed_market_fit",
           return_value=("MARKET_FIT_HOLD", "HOLD_MARKET_FIT_REVIEW_REF_INVALID"))
    def test_self_attested_job_pass_does_not_bypass_review(self, review, run):
        with self.assertRaisesRegex(
            AccountingImmutableReadHold,
            "^HOLD_ACCOUNTING_MARKET_FIT_REVIEW_UNVERIFIED$",
        ):
            check_accounting_e2e_with_authenticated_factory(
                self.job, phase="PRE_IDENTITY",
            )
        review.assert_called_once_with(self.job)
        run.assert_not_called()

    @patch("scripts.accounting_immutable_github_reader.subprocess.run")
    @patch("scripts.market_fit_review_reader.assess_reviewed_market_fit",
           side_effect=RuntimeError("token=DO_NOT_LOG"))
    def test_review_reader_failure_is_secret_safe(self, review, run):
        with self.assertRaises(AccountingImmutableReadHold) as caught:
            check_accounting_e2e_with_authenticated_factory(
                self.job, phase="PACKAGE",
            )
        self.assertEqual(
            str(caught.exception),
            "HOLD_ACCOUNTING_MARKET_FIT_REVIEW_UNAVAILABLE",
        )
        self.assertNotIn("DO_NOT_LOG", str(caught.exception))
        run.assert_not_called()

    @patch("scripts.market_fit_review_reader.assess_reviewed_market_fit")
    def test_other_products_do_not_require_accounting_review(self, review):
        status, reason = check_accounting_e2e_with_authenticated_factory(
            {"slug": "offline-notes-canary"}, phase="PRE_IDENTITY",
        )
        self.assertEqual((status, reason),
                         ("NOT_APPLICABLE", "NON_ACCOUNTING_SKU"))
        review.assert_not_called()


if __name__ == "__main__":
    unittest.main()
