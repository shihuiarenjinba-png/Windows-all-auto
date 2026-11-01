"""Read-only, revision-aware Factory APP MARKET_FIT package gate.

Mirrors AI-App-Factory/tools/market_fit_gate.py (PR #45): reviewed
docs/market/<slug>.market-fit.json, >=80, sum-checked component scores,
all GO criteria and explicit commercial permission. Adds immutable
request/source binding for the central E2E handoff. Never grants Version,
Identity, MSIX, local QA or Store approval.
"""
from __future__ import annotations

import json
import re

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
MIN_CANDIDATE_SCORE = 80
SCORE_MAX = {
    "problem_severity": 20, "differentiation": 20,
    "willingness_to_pay": 20, "usability": 15,
    "trust_privacy": 10, "discoverability": 10,
    "implementation_risk": 5,
}
GO_KEYS = (
    "one_sentence_why_pay", "two_distinctions_from_free_alternatives",
    "addresses_review_complaint", "feasible_windows_local",
    "no_saas_dependency", "minimum_score_70",
)


class MarketFitHold(ValueError):
    pass


def _unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise MarketFitHold("HOLD_MARKET_FIT_DUPLICATE_KEY")
        obj[key] = value
    return obj


def assess_market_fit(job, fetch_factory_evidence=None, verify_source_ancestry=None):
    """Read-only classification; authenticated readers must pin review commit.

    The review SHA is separate from source_sha: a file cannot contain its own
    Git commit SHA. Ancestry must prove review commit descends from source.
    """
    if not isinstance(job, dict):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_JOB_SCHEMA"
    if job.get("product_type") != "APP":
        return "NOT_APPLICABLE", "NON_APP"
    if not callable(fetch_factory_evidence) or not callable(verify_source_ancestry):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_AUTHENTICATED_READERS_MISSING"
    slug, source, review = job.get("slug"), job.get("source_sha"), job.get("market_fit_review_sha")
    if (not isinstance(slug, str) or not SLUG.fullmatch(slug)
            or not isinstance(source, str) or not SHA40.fullmatch(source)
            or not isinstance(review, str) or not SHA40.fullmatch(review)
            or review == source):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_IMMUTABLE_REVISION_MISSING"
    for field in ("request_id", "source_repository", "source_branch"):
        if not isinstance(job.get(field), str) or not job[field].strip():
            return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SOURCE_BINDING"
    if verify_source_ancestry(job["source_repository"], source, review, slug) is not True:
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_REVIEW_ANCESTRY"
    path = f"docs/market/{slug}.market-fit.json"
    raw = fetch_factory_evidence(job["source_repository"], path, review)
    if raw is None:
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_FACTORY_EVIDENCE_MISSING"
    if not isinstance(raw, str) or not 0 < len(raw.encode("utf-8")) <= 65536:
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_EVIDENCE_INVALID"
    try:
        evidence = json.loads(raw, object_pairs_hook=_unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except MarketFitHold as exc:
        return "MARKET_FIT_HOLD", str(exc)
    except (ValueError, TypeError, UnicodeError):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_JSON_INVALID"
    if not isinstance(evidence, dict) or evidence.get("schema_version") != "app5-market-fit-v1":
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SCHEMA"
    bindings = {
        "slug": slug, "request_id": job["request_id"],
        "repo": job["source_repository"], "source_branch": job["source_branch"],
        "baseline_sha": source,
    }
    if any(evidence.get(field) != value for field, value in bindings.items()):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SOURCE_CONFLICT"
    if (evidence.get("decision") != "MARKET_FIT_PASS"
            or evidence.get("commercial_msix_allowed") is not True
            or evidence.get("feature_expansion_allowed") is not True
            or evidence.get("review_status") != "APPROVED"):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_REVIEW_NOT_APPROVED"
    scoring = evidence.get("scoring")
    if not isinstance(scoring, dict) or set(scoring) != set(SCORE_MAX) | {"total", "max"}:
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SCORE_SCHEMA"
    points = 0
    for name, maximum in SCORE_MAX.items():
        part = scoring.get(name)
        if (not isinstance(part, dict) or type(part.get("score")) is not int
                or type(part.get("max")) is not int or part["max"] != maximum
                or not 0 <= part["score"] <= maximum):
            return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SCORE_SCHEMA"
        points += part["score"]
    if (type(scoring.get("total")) is not int or type(scoring.get("max")) is not int
            or scoring["max"] != 100 or scoring["total"] != points):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SCORE_SUM_MISMATCH"
    if points < MIN_CANDIDATE_SCORE:
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SCORE_BELOW_80"
    why = evidence.get("why_pay_statement")
    if (not isinstance(why, str) or len(why.strip()) < 10
            or "NOT PROVEN" in why.upper()):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_WHY_PAY_UNCLEAR"
    for field in ("direct_competitors", "free_alternatives"):
        if not isinstance(evidence.get(field), list) or len(evidence[field]) < 3:
            return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_RESEARCH_MISSING"
    for field in ("common_review_complaints", "store_search_keywords"):
        if not isinstance(evidence.get(field), list) or not evidence[field]:
            return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_RESEARCH_MISSING"
    for field in ("paid_price_range", "buyer_persona"):
        if not isinstance(evidence.get(field), str) or len(evidence[field].strip()) < 10:
            return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_RESEARCH_MISSING"
    if not isinstance(evidence.get("price_hypothesis"), dict):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_RESEARCH_MISSING"
    differences = evidence.get("free_alternative_differences")
    if (not isinstance(differences, list) or len(differences) < 2
            or any(not isinstance(x, dict)
                   or not isinstance(x.get("alternative"), str) or not x["alternative"].strip()
                   or not isinstance(x.get("difference"), str) or not x["difference"].strip()
                   for x in differences)
            or len({x["alternative"].strip().casefold() for x in differences}) < 2):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_FREE_ALTERNATIVE_PROOF"
    go = evidence.get("go_criteria")
    if not isinstance(go, dict) or any(go.get(k) is not True for k in GO_KEYS):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_GO_CRITERIA"
    return "MARKET_FIT_PASS", "FACTORY_REVIEW_SHA_BOUND_SCORE_80_ALL_GO"
