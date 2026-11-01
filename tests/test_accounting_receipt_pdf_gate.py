"""Mocked evidence contract only: not physical Windows/Store QA."""
import unittest

from scripts.accounting_country_gate import FACTORY, SPECS
from scripts.accounting_receipt_pdf_gate import (
    AccountingReceiptPDFHold, validate_accounting_receipt_pdf_gate,
)


def fixture(slug):
    market, locale, currency, _ = SPECS[slug]
    job = {
        "slug": slug, "source_repository": FACTORY, "source_sha": "a" * 40,
        "request_id": f"app-{slug}-" + "a" * 12, "product_type": "APP",
        "market": market, "locale": locale, "currency": currency,
        "factory_build_head": "b" * 40, "package_sha256": "c" * 64,
        "checker_report_sha256": "d" * 64, "store_id": "9TESTSTORE",
    }
    ev = {
        "verification_method": "INDEPENDENT_PHYSICAL_WINDOWS_REVIEW",
        "platform": "PHYSICAL_WINDOWS", "slug": slug, "request_id": job["request_id"],
        "source_sha": job["source_sha"], "factory_build_head": job["factory_build_head"],
        "package_sha256": job["package_sha256"],
        "checker_report_sha256": job["checker_report_sha256"],
        "store_id": job["store_id"], "market": market, "locale": locale,
        "currency": currency, "ocr_present": True,
        "ocr_cases": {k: {"status": "REVIEW_REQUIRED", "source_image_sha256": "e" * 64,
                          "confidence_recorded": True, "original_image_linked": True,
                          "manual_review_required": True, "no_auto_post": True}
                      for k in ("low_resolution", "skewed", "mixed_tax_rates", "refund",
                                "multi_item", "ambiguous_vendor", "personal_business_mixed", "duplicate_image")},
        "batch": {"input_count": 4, "accepted_count": 0, "review_count": 3,
                  "failed_count": 1, "duplicate_count": 1,
                  "unconfirmed_post_count": 0, "failed_item_isolated": True,
                  "source_documents_preserved": True,
                  "queue_persisted_after_restart": True},
        "claims": {"measured_accuracy_claim": False, "tax_filing_guarantee": False},
        "jp_month_end": {},
    }
    if market == "JP":
        ev["jp_month_end"] = {
            "status": "REVIEWED", "edge_headless_pdf": True,
            "a4_japanese_visual_review": True,
            "html_sha256": "1" * 64, "csv_sha256": "2" * 64,
            "json_sha256": "3" * 64, "pdf_sha256": "4" * 64,
            "source_receipts_preserved": True, "unprocessed_receipts_listed": True,
            "source_references_valid": True, "monthly_yearly_totals_equal": True,
            "html_csv_json_totals_equal": True, "pdf_amounts_equal": True,
        }
    return job, ev


class ReceiptPDFGateTests(unittest.TestCase):
    def check_hold(self, job, ev, code):
        with self.assertRaisesRegex(AccountingReceiptPDFHold, code):
            validate_accounting_receipt_pdf_gate(job, read_reviewed_evidence=lambda _: ev)

    def test_four_skus_contract_only_never_e2e(self):
        for slug in SPECS:
            with self.subTest(slug=slug):
                job, ev = fixture(slug)
                result = validate_accounting_receipt_pdf_gate(job, read_reviewed_evidence=lambda _: ev)
                self.assertFalse(result["e2e_pass"])
                self.assertEqual(result["status"], "RECEIPT_PDF_EVIDENCE_CONTRACT_VALIDATED")

    def test_no_reader_or_untrusted_claim(self):
        job, ev = fixture("jp-freelance-ledger")
        with self.assertRaisesRegex(AccountingReceiptPDFHold, "READER_MISSING"):
            validate_accounting_receipt_pdf_gate(job)
        ev["claims"]["measured_accuracy_claim"] = True
        self.check_hold(job, ev, "UNVERIFIED_CLAIM")

    def test_unconfirmed_post_or_batch_drop_is_hold(self):
        job, ev = fixture("us-bookkeeping-desk")
        ev["batch"]["unconfirmed_post_count"] = 1
        self.check_hold(job, ev, "BATCH_UNSAFE")
        ev["batch"]["unconfirmed_post_count"] = 0
        ev["batch"]["accepted_count"] = 1
        self.check_hold(job, ev, "BATCH_UNSAFE")

    def test_ocr_unsafe_review_and_missing_case_hold(self):
        job, ev = fixture("jp-bookkeeping-desk")
        ev["ocr_cases"]["ambiguous_vendor"]["manual_review_required"] = False
        self.check_hold(job, ev, "OCR_CASE_UNSAFE")
        del ev["ocr_cases"]["ambiguous_vendor"]
        self.check_hold(job, ev, "OCR_CASES")

    def test_no_ocr_feature_is_allowed_but_not_fake_cases(self):
        job, ev = fixture("us-freelance-ledger")
        ev["ocr_present"] = False
        ev["ocr_cases"] = {}
        self.assertFalse(validate_accounting_receipt_pdf_gate(
            job, read_reviewed_evidence=lambda _: ev)["e2e_pass"])
        ev["ocr_cases"] = {"fake": True}
        self.check_hold(job, ev, "OCR_NOT_IMPLEMENTED")

    def test_jp_pdf_missing_visual_or_totals_hold(self):
        job, ev = fixture("jp-freelance-ledger")
        ev["jp_month_end"]["a4_japanese_visual_review"] = False
        self.check_hold(job, ev, "JP_MONTH_END_UNVERIFIED")
        ev["jp_month_end"]["a4_japanese_visual_review"] = True
        ev["jp_month_end"]["monthly_yearly_totals_equal"] = False
        self.check_hold(job, ev, "JP_MONTH_END_UNVERIFIED")

    def test_cross_market_and_source_conflict(self):
        job, ev = fixture("us-freelance-ledger")
        ev["jp_month_end"] = {"status": "REVIEWED"}
        self.check_hold(job, ev, "CROSS_MARKET_MONTH_END")
        job["source_sha"] = "f" * 40
        self.check_hold(job, ev, "PROVENANCE")

    def test_reader_exception_redacted(self):
        job, _ = fixture("jp-bookkeeping-desk")
        def fail(_):
            raise RuntimeError("receipt contains private vendor data")
        with self.assertRaisesRegex(AccountingReceiptPDFHold, "READER_UNAVAILABLE") as cm:
            validate_accounting_receipt_pdf_gate(job, read_reviewed_evidence=fail)
        self.assertNotIn("private vendor", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
