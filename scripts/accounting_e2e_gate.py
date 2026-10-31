"""Independent, fail-closed accounting pre-Identity and package gate.

Pure contract only: immutable Factory reader and authenticated Actions reader
must be implemented by trusted adapters. No Partner Center/CAS/Store writes.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Callable

from scripts.accounting_country_gate import SPECS, CountryMarketHold, check_accounting_country_gate

FACTORY = "shihuiarenjinba-png/AI-App-Factory"
US = frozenset({"us-freelance-ledger", "us-bookkeeping-desk"})
CASES = {
    "freelance": frozenset({"monthly_net", "annual_net", "negative_net", "decimal_rounding", "currency_scope"}),
    "bookkeeping": frozenset({"debit_equals_credit", "reject_unbalanced", "trial_balance", "profit_and_loss", "balance_sheet", "net_income", "currency_scope"}),
}
INFERENCE_CASES = frozenset({"candidate_only", "confidence_and_rationale", "explicit_user_confirmation", "ambiguous_fail_safe"})
US_CASES = frozenset({"cash_accrual_locked", "method_change_warning", "vehicle_review", "meals_review", "travel_review", "home_office_review", "depreciation_review", "cogs_review", "taxes_licenses_review", "no_tax_filing", "no_state_local_tax_automation"})
US_SOURCES = frozenset({
    "https://www.irs.gov/publications/p583",
    "https://www.irs.gov/publications/p538",
    "https://www.irs.gov/instructions/i3115",
    "https://www.irs.gov/instructions/i1040sc",
    "https://www.irs.gov/publications/p463",
    "https://www.irs.gov/publications/p587",
})
FORBIDDEN_STORE_CLAIMS = re.compile(r"\b(?:irs[ -]?compliant|tax[ -]?compliant|guaranteed[ -]?deduction|guaranteed[ -]?tax[ -]?saving|tax[ -]?filing[ -]?guaranteed)\b", re.I)
_SHA = re.compile(r"[0-9a-f]{40}\Z")


class AccountingE2EHold(ValueError):
    """Fixed non-secret HOLD code only."""


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise AccountingE2EHold(code)


def _unique(pairs):
    obj = {}
    for k, v in pairs:
        _require(k not in obj, "HOLD_ACCOUNTING_E2E_DUPLICATE_KEY")
        obj[k] = v
    return obj


def _bad_constant(_):
    raise AccountingE2EHold("HOLD_ACCOUNTING_E2E_INVALID_JSON")


def _parse(raw: str) -> dict:
    _require(isinstance(raw, str) and 0 < len(raw.encode("utf-8")) <= 16384,
             "HOLD_ACCOUNTING_E2E_MISSING_OR_OVERSIZE")
    try:
        obj = json.loads(raw, object_pairs_hook=_unique, parse_constant=_bad_constant)
    except AccountingE2EHold:
        raise
    except (TypeError, ValueError, UnicodeError) as exc:
        raise AccountingE2EHold("HOLD_ACCOUNTING_E2E_INVALID_JSON") from exc
    _require(type(obj) is dict, "HOLD_ACCOUNTING_E2E_SCHEMA")
    return obj


def _read(reader, path, sha):
    _require(callable(reader), "HOLD_ACCOUNTING_E2E_IMMUTABLE_READER_MISSING")
    try:
        return reader(FACTORY, path, sha)
    except AccountingE2EHold:
        raise
    except Exception as exc:
        raise AccountingE2EHold("HOLD_ACCOUNTING_E2E_IMMUTABLE_READ_FAILED") from exc


def check_accounting_e2e_gate(
    job: dict, *, phase: str,
    fetch_immutable_text: Callable[[str, str, str], str] | None = None,
    fetch_verified_ci: Callable[[dict], dict] | None = None,
    fetch_official_review: Callable[[dict], dict] | None = None,
    fetch_verified_store_availability: Callable[[dict], dict] | None = None,
    other_jobs=(),
) -> tuple[str, str]:
    """Pure checks. PASS from a mocked reader is NOT an authenticated product PASS."""
    _require(type(job) is dict and isinstance(job.get("slug"), str),
             "HOLD_ACCOUNTING_E2E_JOB_INVALID")
    slug = job["slug"]
    if slug not in SPECS:
        return "NOT_APPLICABLE", "NON_ACCOUNTING_SKU"
    _require(phase in {"PRE_IDENTITY", "PACKAGE"}, "HOLD_ACCOUNTING_E2E_PHASE_INVALID")
    sha = job.get("source_sha")
    _require(isinstance(sha, str) and _SHA.fullmatch(sha) is not None,
             "HOLD_ACCOUNTING_E2E_SOURCE_NOT_PINNED")
    try:
        _, market = check_accounting_country_gate(
            job, phase=phase, fetch_immutable_scope=fetch_immutable_text,
            fetch_verified_store_availability=fetch_verified_store_availability,
            other_jobs=other_jobs)
    except CountryMarketHold as exc:
        raise AccountingE2EHold(str(exc)) from exc
    locale, currency = SPECS[slug][1:3]
    contract = _parse(_read(fetch_immutable_text, f"products/{slug}/accounting-validation.json", sha))
    _require(set(contract) == {"schema_version", "slug", "market", "locale", "currency",
                              "tax_filing", "compliance_claim", "category_suggestions_only",
                              "user_confirmation_required", "confidence_and_rationale_required",
                              "ambiguous_input_fail_safe", "fixture_names"},
             "HOLD_ACCOUNTING_E2E_SCHEMA")
    kind = "freelance" if "freelance" in slug else "bookkeeping"
    required = CASES[kind] | INFERENCE_CASES | (US_CASES if slug in US else frozenset())
    _require(type(contract["schema_version"]) is int and contract["schema_version"] == 1
             and contract["slug"] == slug and contract["market"] == market
             and contract["locale"] == locale and contract["currency"] == currency
             and contract["tax_filing"] is False and contract["compliance_claim"] is False
             and contract["category_suggestions_only"] is True
             and contract["user_confirmation_required"] is True
             and contract["confidence_and_rationale_required"] is True
             and contract["ambiguous_input_fail_safe"] is True
             and type(contract["fixture_names"]) is list
             and all(type(name) is str for name in contract["fixture_names"])
             and len(contract["fixture_names"]) == len(set(contract["fixture_names"]))
             and set(contract["fixture_names"]) == required,
             "HOLD_ACCOUNTING_E2E_CONTRACT_MISMATCH")
    _require(callable(fetch_verified_ci), "HOLD_ACCOUNTING_E2E_CI_NOT_VERIFIED")
    try:
        ci = fetch_verified_ci(job)
    except Exception as exc:
        raise AccountingE2EHold("HOLD_ACCOUNTING_E2E_CI_READ_FAILED") from exc
    _require(type(ci) is dict and ci.get("verification_method") == "AUTHENTICATED_GITHUB_ACTIONS_EXACT_SHA"
             and ci.get("verified") is True and ci.get("conclusion") == "success"
             and ci.get("repository") == FACTORY and ci.get("source_sha") == sha
             and ci.get("request_id") == job.get("request_id")
             and ci.get("slug") == slug and type(ci.get("run_id")) is int
             and ci["run_id"] > 0 and type(ci.get("test_results")) is dict
             and set(ci["test_results"]) == required
             and all(v == "PASS" for v in ci["test_results"].values()),
             "HOLD_ACCOUNTING_E2E_CI_EVIDENCE_CONFLICT")
    if slug in US:
        doc = _read(fetch_immutable_text, f"products/{slug}/US_COMPLIANCE_SCOPE.md", sha)
        _require(isinstance(doc, str) and 0 < len(doc) <= 65536
                 and all(source in doc for source in US_SOURCES)
                 and "Form 3115" in doc and "cash" in doc.lower()
                 and "accrual" in doc.lower(),
                 "HOLD_US_COMPLIANCE_SCOPE_INCOMPLETE")
        policy = _parse(_read(fetch_immutable_text, f"products/{slug}/us-compliance-policy.json", sha))
        _require(set(policy) == {"schema_version", "market", "locale", "currency",
                                  "cash_accrual_is_cosmetic", "method_change_warning",
                                  "special_rule_categories", "state_local_tax_automation",
                                  "tax_filing", "compliance_claim", "deduction_auto_approval"},
                 "HOLD_US_COMPLIANCE_POLICY_SCHEMA")
        _require(type(policy["schema_version"]) is int and policy["schema_version"] == 1
                 and policy["market"] == "US" and policy["locale"] == "en-US"
                 and policy["currency"] == "USD"
                 and policy["cash_accrual_is_cosmetic"] is False
                 and policy["method_change_warning"] is True
                 and policy["state_local_tax_automation"] is False
                 and policy["tax_filing"] is False and policy["compliance_claim"] is False
                 and policy["deduction_auto_approval"] is False
                 and type(policy["special_rule_categories"]) is list
                 and all(type(x) is str for x in policy["special_rule_categories"])
                 and len(policy["special_rule_categories"]) == 7
                 and set(policy["special_rule_categories"]) == {
                     "vehicle", "meals", "travel", "home_office", "depreciation",
                     "cogs", "taxes_licenses"},
                 "HOLD_US_COMPLIANCE_POLICY_UNSAFE")
        store_copy = _read(fetch_immutable_text, f"products/{slug}/store-description.txt", sha)
        _require(isinstance(store_copy, str) and 0 < len(store_copy) <= 16384
                 and not FORBIDDEN_STORE_CLAIMS.search(store_copy),
                 "HOLD_US_STORE_CLAIM_UNSAFE")
        _require(callable(fetch_official_review), "HOLD_US_OFFICIAL_REVIEW_MISSING")
        try:
            review = fetch_official_review(job)
        except Exception as exc:
            raise AccountingE2EHold("HOLD_US_OFFICIAL_REVIEW_READ_FAILED") from exc
        _require(type(review) is dict
                 and review.get("verification_method") == "INDEPENDENT_IRS_PRIMARY_SOURCE_REVIEW"
                 and review.get("verified") is True and review.get("source_sha") == sha
                 and review.get("slug") == slug and review.get("request_id") == job["request_id"]
                 and review.get("change_detected") is False
                 and type(review.get("reviewed_at_utc")) is str
                 and type(review.get("source_urls")) is list
                 and all(type(url) is str for url in review["source_urls"])
                 and set(review["source_urls"]) >= US_SOURCES,
                 "HOLD_US_OFFICIAL_REVIEW_UNVERIFIED")
        try:
            reviewed = datetime.fromisoformat(review["reviewed_at_utc"].replace("Z", "+00:00"))
            _require(reviewed.tzinfo is not None and reviewed.utcoffset() is not None
                     and 0 <= (datetime.now(timezone.utc) - reviewed.astimezone(timezone.utc)).total_seconds() <= 7 * 86400,
                     "HOLD_US_OFFICIAL_REVIEW_STALE")
        except (ValueError, TypeError, OverflowError) as exc:
            raise AccountingE2EHold("HOLD_US_OFFICIAL_REVIEW_STALE") from exc
    return ("ACCOUNTING_E2E_PRE_IDENTITY_PASS" if phase == "PRE_IDENTITY"
            else "ACCOUNTING_E2E_PACKAGE_PRECHECK_PASS", market)
