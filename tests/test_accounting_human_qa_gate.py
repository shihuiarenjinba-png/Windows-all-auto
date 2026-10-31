"""Offline contract regressions; mocked readers never prove physical Windows QA."""
import copy
import unittest

from scripts.accounting_human_qa_gate import (
    AccountingHumanQAHold, SCENARIO_ASSERTIONS, validate_accounting_human_qa,
)


def fixture(slug="jp-freelance-ledger"):
    jp = slug.startswith("jp-")
    source = "a" * 40
    job = {
        "slug": slug, "source_repository": "shihuiarenjinba-png/AI-App-Factory",
        "request_id": f"app-{slug}-{source[:12]}", "source_sha": source,
        "product_type": "APP", "market": "JP" if jp else "US",
        "locale": "ja-JP" if jp else "en-US", "currency": "JPY" if jp else "USD",
        "factory_build_head": "b" * 40, "package_sha256": "c" * 64,
        "checker_report_sha256": "d" * 64, "store_id": "9ABC12345678",
    }
    scenario = {
        "status": "PASS", "steps": ["Open search", "Review result"],
        "observed_result": "Completed 2 items; one error isolated, other retained",
        "screenshot_sha256": "e" * 64, "reviewed_on_windows": True,
        "beginner_can_complete": True, "assertions": {},
    }
    ev = {
        "verification_method": "INDEPENDENT_PHYSICAL_WINDOWS_REVIEW",
        "slug": slug, "request_id": job["request_id"],
        "source_sha": source, "factory_build_head": job["factory_build_head"],
        "package_sha256": job["package_sha256"],
        "checker_report_sha256": job["checker_report_sha256"],
        "store_id": job["store_id"], "market": job["market"],
        "locale": job["locale"], "currency": job["currency"],
        "platform": "PHYSICAL_WINDOWS", "resolution": [1024, 768],
        "advanced_accounts_hidden_by_default": True,
        "manual_posting_required": True,
        "scenarios": {
            s: {**copy.deepcopy(scenario),
                "assertions": {a: True for a in SCENARIO_ASSERTIONS[s]}}
            for s in SCENARIO_ASSERTIONS
        },
        "jp_ledger_explanation": jp, "ocr_feature_present": False,
        "ocr_safeguards": {}, "parallel_books_feature_present": False,
        "parallel_books_primary_unchanged": True,
    }
    return job, ev


class ContractTests(unittest.TestCase):
    def check_hold(self, job, ev, code):
        with self.assertRaisesRegex(AccountingHumanQAHold, code):
            validate_accounting_human_qa(
                job, fetch_reviewed_windows_evidence=lambda _: ev)

    def test_four_country_skus_contract_only(self):
        for slug in ("jp-freelance-ledger", "jp-bookkeeping-desk",
                     "us-freelance-ledger", "us-bookkeeping-desk"):
            job, ev = fixture(slug)
            result = validate_accounting_human_qa(
                job, fetch_reviewed_windows_evidence=lambda _: ev)
            self.assertFalse(result["e2e_pass"])
            self.assertTrue(result["requires_independent_gui_install_and_engine_review"])

    def test_untrusted_queue_pass_cannot_bypass_reader(self):
        job, _ = fixture()
        job["human_qa_pass"] = True
        with self.assertRaisesRegex(AccountingHumanQAHold, "TRUSTED_READER_MISSING"):
            validate_accounting_human_qa(job)

    def test_missing_scenario(self):
        job, ev = fixture()
        del ev["scenarios"]["owner_paid_expense"]
        self.check_hold(job, ev, "SCENARIOS")

    def test_cross_product_and_country_binding(self):
        job, ev = fixture()
        ev["slug"] = "us-freelance-ledger"
        self.check_hold(job, ev, "EVIDENCE_BINDING")
        job, ev = fixture("us-bookkeeping-desk")
        ev["market"] = "JP"
        self.check_hold(job, ev, "EVIDENCE_BINDING")

    def test_bool_spoof_and_unsafe_ocr(self):
        job, ev = fixture()
        ev["advanced_accounts_hidden_by_default"] = 1
        self.check_hold(job, ev, "EVIDENCE_BINDING")
        ev["advanced_accounts_hidden_by_default"] = True
        ev["ocr_feature_present"] = True
        self.check_hold(job, ev, "OCR_SAFETY")

    def test_jp_five_ledgers_and_receipt_batch(self):
        job, ev = fixture()
        ev["jp_ledger_explanation"] = False
        self.check_hold(job, ev, "JP_LEDGERS")
        ev["jp_ledger_explanation"] = True
        ev["scenarios"]["multi_receipt_queue"]["observed_result"] = "Single receipt"
        self.check_hold(job, ev, "RECEIPT_BATCH")

    def test_parallel_book_isolation_and_screenshot(self):
        job, ev = fixture("us-bookkeeping-desk")
        ev["parallel_books_feature_present"] = True
        ev["parallel_books_primary_unchanged"] = False
        self.check_hold(job, ev, "PARALLEL_BOOK_ISOLATION")
        ev["parallel_books_primary_unchanged"] = True
        ev["scenarios"]["invoice_to_journal"]["screenshot_sha256"] = ""
        self.check_hold(job, ev, "SCENARIO_UNVERIFIED")

    def test_equipment_review_is_mandatory(self):
        job, ev = fixture()
        ev["scenarios"]["equipment_classification"]["assertions"]["review_required_visible"] = False
        self.check_hold(job, ev, "BEHAVIOR_NOT_VERIFIED")

    def test_reader_failure_sanitized(self):
        job, _ = fixture()
        def broken(_):
            raise RuntimeError("sensitive exception")
        with self.assertRaisesRegex(AccountingHumanQAHold, "READER_UNAVAILABLE"):
            validate_accounting_human_qa(job, fetch_reviewed_windows_evidence=broken)

    def test_non_accounting_never_passes_e2e(self):
        self.assertFalse(validate_accounting_human_qa({"slug": "other-app"})["e2e_pass"])


if __name__ == "__main__":
    unittest.main()
