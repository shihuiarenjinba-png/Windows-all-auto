"""Factory-authenticated MARKET_FIT gate for APP package eligibility.

This is a read-only decision, not an Identity, Version, MSIX or Store approval.
The caller must use an authenticated GitHub reader for the exact immutable
source SHA; a local/operator assertion is never sufficient.
"""
from __future__ import annotations

import json


class MarketFitHold(ValueError):
    pass


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MarketFitHold("HOLD_MARKET_FIT_DUPLICATE_KEY")
        result[key] = value
    return result


def assess_market_fit(job: dict, fetch_factory_evidence=None) -> tuple[str, str]:
    """Return (MARKET_FIT_PASS|MARKET_FIT_HOLD, reason).

    fetch_factory_evidence(repository, path, immutable_source_sha) must read
    authenticated GitHub contents at that SHA, returning None only for a real
    404. Other transport/auth failures must propagate to the caller.
    """
    if job.get("product_type") != "APP":
        return "NOT_APPLICABLE", "NON_APP"
    if not callable(fetch_factory_evidence):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_FACTORY_READER_MISSING"
    path = f"products/{job['slug']}/market-fit.json"
    raw = fetch_factory_evidence(job["source_repository"], path, job["source_sha"])
    if raw is None:
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_FACTORY_EVIDENCE_MISSING"
    if not isinstance(raw, str) or not 0 < len(raw) <= 65536:
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_EVIDENCE_INVALID"
    try:
        evidence = json.loads(raw, object_pairs_hook=_unique_pairs)
    except MarketFitHold as exc:
        return "MARKET_FIT_HOLD", str(exc)
    except (ValueError, TypeError):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_JSON_INVALID"
    if not isinstance(evidence, dict):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SCHEMA"
    for field in ("slug", "request_id", "source_repository", "source_branch",
                  "source_sha"):
        if evidence.get(field) != job.get(field):
            return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SOURCE_CONFLICT"
    if evidence.get("reviewed") is not True or evidence.get("status") != "MARKET_FIT_PASS":
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_NOT_REVIEWED_PASS"
    score = evidence.get("score")
    if type(score) is not int or not 0 <= score <= 100 or score < 70:
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SCORE_BELOW_70_OR_INVALID"
    if not isinstance(evidence.get("why_pay"), str) or not evidence["why_pay"].strip():
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_WHY_PAY_UNCLEAR"
    if (not isinstance(evidence.get("free_alternative_difference"), str)
            or not evidence["free_alternative_difference"].strip()):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_NO_FREE_ALTERNATIVE_DIFFERENCE"
    competitors = evidence.get("competitor_research")
    if (not isinstance(competitors, list) or not competitors
            or any(not isinstance(c, dict)
                   or not isinstance(c.get("competitor"), str)
                   or not c["competitor"].strip()
                   or not isinstance(c.get("difference"), str)
                   or not c["difference"].strip() for c in competitors)):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_COMPETITOR_RESEARCH_MISSING"
    return "MARKET_FIT_PASS", "FACTORY_SOURCE_SHA_BOUND_REVIEWED_EVIDENCE"
