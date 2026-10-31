"""Fail-closed country/Store-market gate for four distinct accounting SKUs.

Pure checks only. Callers must supply authenticated, immutable Factory reads and
verified Partner Center Pricing and availability evidence. A JSON file on disk,
Factory market-scope.json, or an operator assertion alone NEVER proves Store
availability. This module does not create products, CAS, upload or submit.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Iterable

FACTORY = "shihuiarenjinba-png/AI-App-Factory"
SPECS = {
    "jp-freelance-ledger": ("JP", "ja-JP", "JPY", "Japan"),
    "jp-bookkeeping-desk": ("JP", "ja-JP", "JPY", "Japan"),
    "us-freelance-ledger": ("US", "en-US", "USD", "United States"),
    "us-bookkeeping-desk": ("US", "en-US", "USD", "United States"),
}
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SCOPE_FIELDS = frozenset({"store_markets", "store_language", "currency",
                           "country_profile", "cross_market_sale"})
_US_EXTRA_FIELDS = frozenset({
    "federal_scope", "state_local_tax_automation", "tax_filing",
    "deductibility_determination", "compliance_claim",
})
_US_FEDERAL_SCOPES = {
    "us-freelance-ledger":
        "sole_proprietor_recordkeeping_and_schedule_c_preparation_support",
    "us-bookkeeping-desk":
        "general_business_bookkeeping_records_not_tax_return_preparation",
}


class CountryMarketHold(ValueError):
    """Only fixed, non-secret HOLD codes may escape this gate."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise CountryMarketHold(code)


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value, "HOLD_ACCOUNTING_SCOPE_DUPLICATE_KEY")
        value[key] = item
    return value


def _reject_constant(_):
    raise CountryMarketHold("HOLD_ACCOUNTING_SCOPE_JSON_INVALID")


def _parse_scope(raw: str, slug: str) -> dict:
    _require(isinstance(raw, str) and 0 < len(raw.encode("utf-8")) <= 8192,
             "HOLD_ACCOUNTING_SCOPE_MISSING_OR_OVERSIZE")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
    except CountryMarketHold:
        raise
    except (ValueError, TypeError, UnicodeError) as exc:
        raise CountryMarketHold("HOLD_ACCOUNTING_SCOPE_JSON_INVALID") from exc
    expected_fields = (_SCOPE_FIELDS | _US_EXTRA_FIELDS
                       if slug in _US_FEDERAL_SCOPES else _SCOPE_FIELDS)
    _require(isinstance(data, dict) and set(data) == expected_fields,
             "HOLD_ACCOUNTING_SCOPE_SCHEMA_INVALID")
    return data


def check_accounting_country_gate(
    job: dict, *, phase: str,
    fetch_immutable_scope: Callable[[str, str, str], str] | None = None,
    fetch_verified_store_availability: Callable[[dict], dict] | None = None,
    other_jobs: Iterable[dict] = (),
) -> tuple[str, str]:
    """Return a country gate state and the exact permitted market.

    PRE_IDENTITY checks only immutable Factory scope and promotion/market-fit
    bindings. PACKAGE additionally requires an authenticated Partner Center
    observation of Pricing and availability restricted to that single market.
    A PASS here is NOT a Version, signature, Store-submit or GUI QA PASS.

    Injected readers are trust boundaries: Factory reader must fetch contents
    at exact immutable source_sha, and Store reader must inspect authenticated
    Partner Center, not load user-authored evidence.
    """
    _require(isinstance(job, dict), "HOLD_ACCOUNTING_JOB_INVALID")
    slug = job.get("slug")
    _require(isinstance(slug, str), "HOLD_ACCOUNTING_JOB_INVALID")
    if slug not in SPECS:
        return "NOT_APPLICABLE", "NON_ACCOUNTING_SKU"
    _require(phase == "PRE_IDENTITY" or phase == "PACKAGE",
             "HOLD_ACCOUNTING_PHASE_INVALID")
    market, language, currency, country = SPECS[slug]
    _require(job.get("product_type") == "APP"
             and job.get("source_repository") == FACTORY
             and isinstance(job.get("source_branch"), str)
             and job["source_branch"].startswith("codex/")
             and ".." not in job["source_branch"]
             and isinstance(job.get("source_sha"), str)
             and _SHA.fullmatch(job["source_sha"]) is not None
             and isinstance(job.get("request_id"), str)
             and job["request_id"] == f"app-{slug}-{job['source_sha'][:12]}"
             and job.get("identity_return_target") ==
             f"products/{slug}/store/approved-identity.json"
             and job.get("registration_type") == "MSIX_OR_PWA_APP"
             and job.get("partner_center_selection") == "MSIX or PWA app",
             "HOLD_ACCOUNTING_PROMOTION_BINDING_INVALID")
    _require(job.get("market_fit_gate") == "MARKET_FIT_PASS"
             and job.get("market_fit_evidence_verified") is True,
             "HOLD_ACCOUNTING_MARKET_FIT_NOT_VERIFIED")
    _require(job.get("status") in {"PRE_IDENTITY_READY", "POST_IDENTITY_READY"},
             "HOLD_ACCOUNTING_NOT_PROMOTED")
    _require(callable(fetch_immutable_scope),
             "HOLD_ACCOUNTING_IMMUTABLE_SCOPE_READER_MISSING")
    try:
        raw = fetch_immutable_scope(FACTORY, f"products/{slug}/market-scope.json",
                                    job["source_sha"])
    except CountryMarketHold:
        raise
    except Exception as exc:
        raise CountryMarketHold("HOLD_ACCOUNTING_IMMUTABLE_SCOPE_READ_FAILED") from exc
    scope = _parse_scope(raw, slug)
    expected_scope = {
        "store_markets": [market], "store_language": language,
        "currency": currency, "country_profile": country,
        "cross_market_sale": False,
    }
    if slug in _US_FEDERAL_SCOPES:
        expected_scope.update({
            "federal_scope": _US_FEDERAL_SCOPES[slug],
            "state_local_tax_automation": False,
            "tax_filing": False,
            "deductibility_determination": False,
            "compliance_claim": False,
        })
    # JSON 0 == False in Python; do not accept integer stand-ins for safety
    # booleans in the country/US compliance policy contract.
    boolean_fields = {"cross_market_sale"}
    if slug in _US_FEDERAL_SCOPES:
        boolean_fields.update({"state_local_tax_automation", "tax_filing",
                               "deductibility_determination", "compliance_claim"})
    _require(all(type(scope[field]) is bool for field in boolean_fields),
             "HOLD_ACCOUNTING_COUNTRY_SCOPE_BOOLEAN_INVALID")
    _require(scope == expected_scope,
             "HOLD_ACCOUNTING_COUNTRY_SCOPE_MISMATCH")
    for other in other_jobs:
        _require(isinstance(other, dict), "HOLD_ACCOUNTING_COHORT_INVALID")
        if other is job:
            continue
        _require(other.get("slug") != slug
                 and other.get("request_id") != job["request_id"],
                 "HOLD_ACCOUNTING_CROSS_PRODUCT_BINDING")
        for key in ("identity_store_id", "identity_pfn"):
            if job.get(key):
                _require(job[key] != other.get(key),
                         "HOLD_ACCOUNTING_CROSS_MARKET_IDENTITY_REUSE")
    if phase == "PRE_IDENTITY":
        return "ACCOUNTING_PRE_IDENTITY_COUNTRY_SCOPE_PASS", market
    _require(job["status"] == "POST_IDENTITY_READY"
             and isinstance(job.get("identity_store_id"), str)
             and bool(job["identity_store_id"].strip())
             and isinstance(job.get("identity_pfn"), str)
             and bool(job["identity_pfn"].strip()),
             "HOLD_ACCOUNTING_STORE_IDENTITY_NOT_RETURNED")
    _require(callable(fetch_verified_store_availability),
             "HOLD_ACCOUNTING_STORE_MARKETS_UNVERIFIED")
    try:
        observed = fetch_verified_store_availability(job)
    except CountryMarketHold:
        raise
    except Exception as exc:
        raise CountryMarketHold("HOLD_ACCOUNTING_STORE_MARKETS_READ_FAILED") from exc
    _require(isinstance(observed, dict)
             and observed.get("verification_method") == "AUTHENTICATED_PARTNER_CENTER_PRICING_AVAILABILITY"
             and observed.get("verified") is True
             and observed.get("request_id") == job["request_id"]
             and observed.get("source_sha") == job["source_sha"]
             and observed.get("slug") == slug
             and observed.get("store_id") == job["identity_store_id"]
             and observed.get("markets") == [market]
             and observed.get("all_markets_default") is False,
             "HOLD_ACCOUNTING_STORE_MARKET_EVIDENCE_CONFLICT")
    return "ACCOUNTING_COUNTRY_STORE_MARKET_PASS", market
