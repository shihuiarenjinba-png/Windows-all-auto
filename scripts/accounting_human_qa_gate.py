"""Pure fail-closed human-usability QA contract for four accounting SKUs.

Only an independent, reviewed physical-Windows reader may supply evidence.
This validates evidence structure; it NEVER certifies real GUI/install/E2E PASS.
No Partner Center, Store, CAS, package or installation writes occur here.
"""
from __future__ import annotations

import re
from typing import Callable

from scripts.accounting_country_gate import FACTORY, SPECS

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
SCENARIO_ASSERTIONS = {
    "account_search_rent": frozenset({"account_candidates_visible", "usage_guidance_visible"}),
    "equipment_classification": frozenset({"expense_and_asset_choices_visible", "review_required_visible"}),
    "invoice_to_journal": frozenset({"invoice_or_receivable_path_visible", "journal_destination_visible"}),
    "owner_paid_expense": frozenset({"owner_paid_guidance_visible", "no_unconfirmed_post"}),
    "multi_receipt_queue": frozenset({"queue_count_visible", "failed_item_isolated", "duplicate_candidate_flagged"}),
}


class AccountingHumanQAHold(ValueError):
    """A fixed, non-secret HOLD code."""


def _need(ok: bool, code: str) -> None:
    if not ok:
        raise AccountingHumanQAHold(code)


def _sha64(value: object) -> bool:
    return type(value) is str and _SHA64.fullmatch(value) is not None


def validate_accounting_human_qa(
    job: dict, *,
    fetch_reviewed_windows_evidence: Callable[[dict], dict] | None = None,
) -> dict:
    """Validate five beginner scenarios against exact immutable product evidence.

    The trusted reader MUST inspect real Windows UI independently of queue data.
    Its assertions and screenshot hashes are not independently authenticated by
    this pure function. A separate human/engine/install review is still required.
    """
    _need(type(job) is dict, "HOLD_ACCOUNTING_HUMAN_QA_JOB_INVALID")
    slug = job.get("slug")
    _need(type(slug) is str, "HOLD_ACCOUNTING_HUMAN_QA_JOB_INVALID")
    if slug not in SPECS:
        return {"status": "NOT_APPLICABLE", "e2e_pass": False}
    market, locale, currency, _ = SPECS[slug]
    source_sha = job.get("source_sha")
    _need(
        job.get("source_repository") == FACTORY
        and type(source_sha) is str and _SHA40.fullmatch(source_sha) is not None
        and job.get("request_id") == f"app-{slug}-{source_sha[:12]}"
        and job.get("product_type") == "APP"
        and job.get("market") == market
        and job.get("locale") == locale
        and job.get("currency") == currency
        and type(job.get("factory_build_head")) is str
        and _SHA40.fullmatch(job["factory_build_head"]) is not None
        and _sha64(job.get("package_sha256"))
        and _sha64(job.get("checker_report_sha256"))
        and type(job.get("store_id")) is str and bool(job["store_id"]),
        "HOLD_ACCOUNTING_HUMAN_QA_BINDING",
    )
    _need(callable(fetch_reviewed_windows_evidence),
          "HOLD_ACCOUNTING_HUMAN_QA_TRUSTED_READER_MISSING")
    try:
        evidence = fetch_reviewed_windows_evidence(dict(job))
    except Exception:
        raise AccountingHumanQAHold("HOLD_ACCOUNTING_HUMAN_QA_READER_UNAVAILABLE") from None
    _need(type(evidence) is dict, "HOLD_ACCOUNTING_HUMAN_QA_EVIDENCE_INVALID")
    expected = {
        "verification_method": "INDEPENDENT_PHYSICAL_WINDOWS_REVIEW",
        "slug": slug, "request_id": job["request_id"],
        "source_sha": source_sha, "factory_build_head": job["factory_build_head"],
        "package_sha256": job["package_sha256"],
        "checker_report_sha256": job["checker_report_sha256"],
        "store_id": job["store_id"],
        "market": market, "locale": locale, "currency": currency,
        "platform": "PHYSICAL_WINDOWS", "resolution": [1024, 768],
        "advanced_accounts_hidden_by_default": True,
        "manual_posting_required": True,
    }
    optional = {"scenarios", "jp_ledger_explanation", "ocr_feature_present",
                "ocr_safeguards", "parallel_books_feature_present",
                "parallel_books_primary_unchanged"}
    _need(set(evidence) == set(expected) | optional,
          "HOLD_ACCOUNTING_HUMAN_QA_EVIDENCE_SCHEMA")
    _need(all(type(evidence[k]) is type(value) and evidence[k] == value
              for k, value in expected.items()),
          "HOLD_ACCOUNTING_HUMAN_QA_EVIDENCE_BINDING")
    _need(type(evidence["jp_ledger_explanation"]) is bool
          and evidence["jp_ledger_explanation"] == (market == "JP"),
          "HOLD_ACCOUNTING_HUMAN_QA_JP_LEDGERS")
    _need(type(evidence["ocr_feature_present"]) is bool
          and type(evidence["parallel_books_feature_present"]) is bool,
          "HOLD_ACCOUNTING_HUMAN_QA_FEATURE_FLAGS")
    _need(type(evidence["parallel_books_primary_unchanged"]) is bool
          and (not evidence["parallel_books_feature_present"]
               or evidence["parallel_books_primary_unchanged"]),
          "HOLD_ACCOUNTING_HUMAN_QA_PARALLEL_BOOK_ISOLATION")
    scenarios = evidence["scenarios"]
    _need(type(scenarios) is dict and set(scenarios) == set(SCENARIO_ASSERTIONS),
          "HOLD_ACCOUNTING_HUMAN_QA_SCENARIOS")
    for key, scenario in scenarios.items():
        _need(type(scenario) is dict and set(scenario) == {
            "status", "steps", "observed_result", "screenshot_sha256",
            "reviewed_on_windows", "beginner_can_complete", "assertions",
        }, "HOLD_ACCOUNTING_HUMAN_QA_SCENARIO_SCHEMA")
        _need(scenario["status"] == "PASS"
              and type(scenario["steps"]) is list and bool(scenario["steps"])
              and all(type(s) is str and bool(s.strip()) for s in scenario["steps"])
              and type(scenario["observed_result"]) is str
              and bool(scenario["observed_result"].strip())
              and _sha64(scenario["screenshot_sha256"])
              and scenario["reviewed_on_windows"] is True
              and scenario["beginner_can_complete"] is True,
              "HOLD_ACCOUNTING_HUMAN_QA_SCENARIO_UNVERIFIED")
        assertions = scenario["assertions"]
        _need(type(assertions) is dict
              and set(assertions) == SCENARIO_ASSERTIONS[key]
              and all(value is True for value in assertions.values()),
              "HOLD_ACCOUNTING_HUMAN_QA_BEHAVIOR_NOT_VERIFIED")
    receipt = scenarios["multi_receipt_queue"]
    _need("2" in receipt["observed_result"]
          or "multiple" in receipt["observed_result"].lower(),
          "HOLD_ACCOUNTING_HUMAN_QA_RECEIPT_BATCH_UNVERIFIED")
    ocr = evidence["ocr_safeguards"]
    _need(type(ocr) is dict, "HOLD_ACCOUNTING_HUMAN_QA_OCR_SCHEMA")
    if evidence["ocr_feature_present"]:
        _need(set(ocr) == {"confidence", "source_image_reference",
                           "no_unconfirmed_post", "duplicate_candidate_detection",
                           "partial_batch_failure_survives"}
              and all(ocr.get(k) is True for k in ocr),
              "HOLD_ACCOUNTING_HUMAN_QA_OCR_SAFETY")
    else:
        _need(not ocr, "HOLD_ACCOUNTING_HUMAN_QA_OCR_NOT_IMPLEMENTED")
    return {
        "status": "HUMAN_USABILITY_EVIDENCE_CONTRACT_VALIDATED",
        "requires_independent_gui_install_and_engine_review": True,
        "e2e_pass": False,
        "store_submission": "NOT_PERFORMED",
        "slug": slug, "request_id": job["request_id"],
    }
