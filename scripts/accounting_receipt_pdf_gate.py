"""Fail-closed accounting receipt/OCR and JP month-end PDF QA evidence gate.

This is an independent evidence contract, not a Windows test runner. A real
reviewer/byte reader must supply observations. It never posts journals,
changes source documents, or upgrades a product to E2E_PASS.
"""
from __future__ import annotations

import re
from typing import Callable

from scripts.accounting_country_gate import FACTORY, SPECS

_CASES = (
    "low_resolution", "skewed", "mixed_tax_rates", "refund",
    "multi_item", "ambiguous_vendor", "personal_business_mixed", "duplicate_image",
)


class AccountingReceiptPDFHold(ValueError):
    """Stable non-secret HOLD code; never include raw receipt text in errors."""


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise AccountingReceiptPDFHold(code)


def _hash(value: object, size: int) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{%d}" % size, value) is not None


def validate_accounting_receipt_pdf_gate(
    job: dict, *, read_reviewed_evidence: Callable[[dict], dict] | None = None,
) -> dict:
    """Validate exact product binding; never imply physical QA or Store PASS."""
    _need(type(job) is dict, "HOLD_RECEIPT_PDF_JOB_INVALID")
    slug = job.get("slug")
    _need(type(slug) is str, "HOLD_RECEIPT_PDF_JOB_INVALID")
    if slug not in SPECS:
        return {"status": "NOT_APPLICABLE", "e2e_pass": False}
    market, locale, currency, _ = SPECS[slug]
    source = job.get("source_sha")
    _need(
        job.get("source_repository") == FACTORY
        and _hash(source, 40)
        and job.get("request_id") == f"app-{slug}-{source[:12]}"
        and job.get("product_type") == "APP"
        and job.get("market") == market
        and job.get("locale") == locale
        and job.get("currency") == currency
        and _hash(job.get("factory_build_head"), 40)
        and _hash(job.get("package_sha256"), 64)
        and _hash(job.get("checker_report_sha256"), 64)
        and type(job.get("store_id")) is str and bool(job["store_id"]),
        "HOLD_RECEIPT_PDF_PROVENANCE",
    )
    _need(callable(read_reviewed_evidence), "HOLD_RECEIPT_PDF_READER_MISSING")
    try:
        evidence = read_reviewed_evidence(dict(job))
    except Exception:
        raise AccountingReceiptPDFHold("HOLD_RECEIPT_PDF_READER_UNAVAILABLE") from None
    _need(type(evidence) is dict, "HOLD_RECEIPT_PDF_EVIDENCE_INVALID")
    expected = {
        "verification_method": "INDEPENDENT_PHYSICAL_WINDOWS_REVIEW",
        "platform": "PHYSICAL_WINDOWS",
        "slug": slug, "request_id": job["request_id"],
        "source_sha": source, "factory_build_head": job["factory_build_head"],
        "package_sha256": job["package_sha256"],
        "checker_report_sha256": job["checker_report_sha256"],
        "store_id": job["store_id"],
        "market": market, "locale": locale, "currency": currency,
    }
    required = set(expected) | {"ocr_present", "ocr_cases", "batch", "claims", "jp_month_end"}
    _need(set(evidence) == required, "HOLD_RECEIPT_PDF_EVIDENCE_SCHEMA")
    _need(all(type(evidence[k]) is type(v) and evidence[k] == v
              for k, v in expected.items()), "HOLD_RECEIPT_PDF_EVIDENCE_BINDING")
    _need(type(evidence["ocr_present"]) is bool, "HOLD_RECEIPT_PDF_OCR_FLAG")
    _need(type(evidence["claims"]) is dict
          and set(evidence["claims"]) == {"measured_accuracy_claim", "tax_filing_guarantee"}
          and evidence["claims"]["measured_accuracy_claim"] is False
          and evidence["claims"]["tax_filing_guarantee"] is False,
          "HOLD_RECEIPT_PDF_UNVERIFIED_CLAIM")
    batch = evidence["batch"]
    _need(type(batch) is dict and set(batch) == {
        "input_count", "accepted_count", "review_count", "failed_count",
        "duplicate_count", "unconfirmed_post_count", "failed_item_isolated",
        "source_documents_preserved", "queue_persisted_after_restart",
    }, "HOLD_RECEIPT_PDF_BATCH_SCHEMA")
    counts = ("input_count", "accepted_count", "review_count", "failed_count",
              "duplicate_count", "unconfirmed_post_count")
    _need(all(type(batch[k]) is int and batch[k] >= 0 for k in counts)
          and batch["input_count"] >= 2
          and batch["accepted_count"] + batch["review_count"] + batch["failed_count"] == batch["input_count"]
          and batch["duplicate_count"] <= batch["review_count"]
          and batch["unconfirmed_post_count"] == 0
          and all(batch[k] is True for k in (
              "failed_item_isolated", "source_documents_preserved", "queue_persisted_after_restart")),
          "HOLD_RECEIPT_PDF_BATCH_UNSAFE")
    cases = evidence["ocr_cases"]
    _need(type(cases) is dict, "HOLD_RECEIPT_PDF_OCR_CASES")
    if evidence["ocr_present"]:
        _need(set(cases) == set(_CASES), "HOLD_RECEIPT_PDF_OCR_CASES")
        for key in _CASES:
            case = cases[key]
            _need(type(case) is dict and set(case) == {
                "status", "source_image_sha256", "confidence_recorded",
                "original_image_linked", "manual_review_required", "no_auto_post",
            } and case["status"] == "REVIEW_REQUIRED"
                and _hash(case["source_image_sha256"], 64)
                and all(case[k] is True for k in (
                    "confidence_recorded", "original_image_linked",
                    "manual_review_required", "no_auto_post")),
                "HOLD_RECEIPT_PDF_OCR_CASE_UNSAFE")
        # Eight distinct high-risk observations are required. Reusing one
        # screenshot/image digest for every named case is not an eight-case QA.
        # The duplicate-image case itself must demonstrate duplicates inside
        # that test; it must not borrow another case\'s entire fixture.
        _need(len({cases[key]["source_image_sha256"] for key in _CASES}) == len(_CASES),
              "HOLD_RECEIPT_PDF_OCR_FIXTURE_REUSED")
    else:
        _need(not cases, "HOLD_RECEIPT_PDF_OCR_NOT_IMPLEMENTED")
    monthly = evidence["jp_month_end"]
    _need(type(monthly) is dict, "HOLD_RECEIPT_PDF_MONTHLY_SCHEMA")
    if market == "JP":
        _need(set(monthly) == {
            "status", "edge_headless_pdf", "a4_japanese_visual_review",
            "html_sha256", "csv_sha256", "json_sha256", "pdf_sha256",
            "source_receipts_preserved", "unprocessed_receipts_listed",
            "source_references_valid", "monthly_yearly_totals_equal",
            "html_csv_json_totals_equal", "pdf_amounts_equal",
        } and monthly["status"] == "REVIEWED"
            and all(_hash(monthly[k], 64) for k in (
                "html_sha256", "csv_sha256", "json_sha256", "pdf_sha256"))
            and all(monthly[k] is True for k in (
                "edge_headless_pdf", "a4_japanese_visual_review",
                "source_receipts_preserved", "unprocessed_receipts_listed",
                "source_references_valid", "monthly_yearly_totals_equal",
                "html_csv_json_totals_equal", "pdf_amounts_equal")),
            "HOLD_RECEIPT_PDF_JP_MONTH_END_UNVERIFIED")
    else:
        _need(not monthly, "HOLD_RECEIPT_PDF_CROSS_MARKET_MONTH_END")
    return {
        "status": "RECEIPT_PDF_EVIDENCE_CONTRACT_VALIDATED",
        "slug": slug, "request_id": job["request_id"],
        "requires_independent_bytes_and_gui_review": True,
        "e2e_pass": False, "store_submission": "NOT_PERFORMED",
    }
