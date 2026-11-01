"""Read-only Factory MARKET_FIT contract for an immutable APP source revision.

The Factory's Image Inventory policy is >=80 plus every GO condition; 70-79
is redesign, not package approval. Identity, Version and Store gates remain
independent. Evidence is committed AFTER the source commit and is pinned by a
separate immutable review SHA to avoid a self-referential Git commit hash.
"""
from __future__ import annotations

import json
import re

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
MIN_CANDIDATE_SCORE = 80
GO_KEYS = (
    "one_sentence_why_pay", "two_distinctions_from_free_alternatives",
    "addresses_review_complaint", "feasible_windows_local",
    "no_saas_dependency",
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
    """Return (MARKET_FIT_PASS|MARKET_FIT_HOLD|NOT_APPLICABLE, reason).

    Both injected readers MUST use authenticated GitHub and immutable commit
    SHAs. No local operator assertion, moving branch, or candidate-only file
    can be used to pass this gate.
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
    if verify_source_ancestry(job["source_repository"], source, review) is not True:
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_REVIEW_ANCESTRY"
    path = f"products/{slug}/market-fit.json"
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
    if not isinstance(evidence, dict) or type(evidence.get("schema_version")) is not int or evidence["schema_version"] != 1:
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SCHEMA"
    for field in ("slug", "request_id", "source_repository", "source_branch", "source_sha"):
        if evidence.get(field) != job.get(field):
            return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SOURCE_CONFLICT"
    if (evidence.get("reviewed") is not True or evidence.get("review_status") != "APPROVED"
            or evidence.get("status") != "MARKET_FIT_PASS"):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_REVIEW_NOT_APPROVED"
    score = evidence.get("score")
    if type(score) is not int or not 0 <= score <= 100 or score < MIN_CANDIDATE_SCORE:
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_SCORE_BELOW_80_OR_INVALID"
    why = evidence.get("why_pay")
    if not isinstance(why, str) or not why.strip():
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_WHY_PAY_UNCLEAR"
    alternatives = evidence.get("free_alternative_differences")
    if (not isinstance(alternatives, list) or len(alternatives) < 2
            or any(not isinstance(x, dict)
                   or not isinstance(x.get("alternative"), str) or not x["alternative"].strip()
                   or not isinstance(x.get("difference"), str) or not x["difference"].strip()
                   for x in alternatives)
            or len({x["alternative"].strip().casefold() for x in alternatives}) < 2):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_FREE_ALTERNATIVE_PROOF"
    competitors = evidence.get("competitor_research")
    if (not isinstance(competitors, list) or not competitors
            or any(not isinstance(x, dict)
                   or not isinstance(x.get("competitor"), str) or not x["competitor"].strip()
                   or not isinstance(x.get("difference"), str) or not x["difference"].strip()
                   for x in competitors)):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_COMPETITOR_RESEARCH_MISSING"
    go = evidence.get("go_criteria")
    if not isinstance(go, dict) or any(go.get(k) is not True for k in GO_KEYS):
        return "MARKET_FIT_HOLD", "HOLD_MARKET_FIT_GO_CRITERIA"
    return "MARKET_FIT_PASS", "FACTORY_REVIEW_SHA_BOUND_SCORE_80_ALL_GO"
