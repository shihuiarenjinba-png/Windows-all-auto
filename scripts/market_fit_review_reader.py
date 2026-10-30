"""Read immutable Factory MARKET_FIT evidence from a separate review-only commit.

Existing Factory source SHAs predate MARKET_FIT files and must never be rewritten.
A single-file descendant review commit is evidence, not a replacement source SHA
or package-build authorization. Read-only; never touches Partner Center or CAS.
"""
from __future__ import annotations

import json
import re
import subprocess

from scripts.market_fit_gate import assess_market_fit
from scripts.market_fit_github_reader import MarketFitReadHold, read_factory_market_fit

_SHA = re.compile(r"[0-9a-f]{40}\\Z")
_REPO = "shihuiarenjinba-png/AI-App-Factory"
_MAX_COMPARE_RESPONSE = 256 * 1024


def _check_review_commit(job: dict) -> tuple[str, str, str]:
    """Verify a pinned one-commit descendant adds only this job's market-fit.json."""
    if not isinstance(job, dict) or job.get("product_type") != "APP":
        raise MarketFitReadHold("HOLD_MARKET_FIT_REVIEW_JOB_INVALID")
    slug = job.get("slug")
    source = job.get("source_sha")
    review = job.get("market_fit_review_commit_sha")
    if (job.get("source_repository") != _REPO
            or not isinstance(slug, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)
            or not isinstance(source, str) or not _SHA.fullmatch(source)
            or not isinstance(review, str) or not _SHA.fullmatch(review)
            or review == source
            or not isinstance(job.get("request_id"), str)
            or not job["request_id"]
            or not isinstance(job.get("source_branch"), str)
            or not job["source_branch"].startswith("codex/")):
        raise MarketFitReadHold("HOLD_MARKET_FIT_REVIEW_REF_INVALID")
    path = f"products/{slug}/market-fit.json"
    try:
        proc = subprocess.run(
            ["gh", "api", "--method", "GET",
             f"repos/{_REPO}/compare/{source}...{review}"],
            capture_output=True, text=True, encoding="utf-8", timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MarketFitReadHold("HOLD_MARKET_FIT_REVIEW_COMPARE_UNAVAILABLE") from exc
    if proc.returncode != 0:
        raise MarketFitReadHold("HOLD_MARKET_FIT_REVIEW_COMPARE_UNAVAILABLE")
    if len(proc.stdout.encode("utf-8")) > _MAX_COMPARE_RESPONSE:
        raise MarketFitReadHold("HOLD_MARKET_FIT_REVIEW_COMPARE_INVALID")
    try:
        data = json.loads(proc.stdout)
    except (ValueError, TypeError) as exc:
        raise MarketFitReadHold("HOLD_MARKET_FIT_REVIEW_COMPARE_INVALID") from exc
    if (not isinstance(data, dict)
            or data.get("status") != "ahead"
            or type(data.get("ahead_by")) is not int or data["ahead_by"] != 1
            or type(data.get("behind_by")) is not int or data["behind_by"] != 0
            or type(data.get("total_commits")) is not int or data["total_commits"] != 1
            or not isinstance(data.get("merge_base_commit"), dict)
            or data["merge_base_commit"].get("sha") != source
            or not isinstance(data.get("base_commit"), dict)
            or data["base_commit"].get("sha") != source
            or not isinstance(data.get("commits"), list)
            or len(data["commits"]) != 1
            or not isinstance(data["commits"][0], dict)
            or data["commits"][0].get("sha") != review
            or not isinstance(data.get("files"), list)
            or len(data["files"]) != 1
            or not isinstance(data["files"][0], dict)
            or data["files"][0].get("filename") != path
            or data["files"][0].get("status") != "added"):
        raise MarketFitReadHold("HOLD_MARKET_FIT_REVIEW_COMMIT_CONFLICT")
    return _REPO, path, review


def read_reviewed_market_fit(job: dict) -> str:
    """Read review SHA bytes while the evidence payload binds original source_sha."""
    repo, path, review = _check_review_commit(job)
    raw = read_factory_market_fit(repo, path, review)
    if raw is None:
        raise MarketFitReadHold("HOLD_MARKET_FIT_REVIEW_FILE_MISSING")
    return raw


def assess_reviewed_market_fit(job: dict) -> tuple[str, str]:
    if not isinstance(job, dict) or job.get("product_type") != "APP":
        return "NOT_APPLICABLE", "NON_APP"
    try:
        raw = read_reviewed_market_fit(job)
        return assess_market_fit(job, lambda repository, path, source_sha: raw)
    except MarketFitReadHold as exc:
        return "MARKET_FIT_HOLD", str(exc)


def reconcile_with_reviewed_market_fit(
    ledger: dict, slug: str, *, fetch_branch_head, fetch_approved_file,
    verify_source_ancestry,
) -> tuple[dict, str]:
    """Propose a ledger copy; only the 36-minute owner may commit canonical data.

    MARKET_FIT failure must not prevent an independently valid Identity-only
    CAS return from becoming POST_IDENTITY_READY. Packaging remains HOLD.
    """
    from scripts.reconcile_post_identity import _all_jobs, reconcile_approved_return
    jobs = _all_jobs(ledger)
    matching = [job for job in jobs if job.get("slug") == slug]
    if len(matching) != 1:
        raise MarketFitReadHold("HOLD_MARKET_FIT_REVIEW_JOB_NOT_UNIQUE")
    job = matching[0]
    read_hold = [None]

    def fetch_market_fit(repository: str, path: str, source_sha: str) -> str | None:
        expected_path = f"products/{job['slug']}/market-fit.json"
        if (repository != job.get("source_repository")
                or path != expected_path or source_sha != job.get("source_sha")):
            raise MarketFitReadHold("HOLD_MARKET_FIT_REVIEW_CROSS_PRODUCT")
        try:
            return read_reviewed_market_fit(job)
        except MarketFitReadHold as exc:
            read_hold[0] = str(exc)
            return None

    updated, transition = reconcile_approved_return(
        ledger, slug, fetch_branch_head=fetch_branch_head,
        fetch_approved_file=fetch_approved_file,
        verify_source_ancestry=verify_source_ancestry,
        fetch_market_fit=fetch_market_fit,
    )
    if read_hold[0]:
        for item in _all_jobs(updated):
            if item.get("slug") == slug:
                item["market_fit_gate"] = "MARKET_FIT_HOLD"
                item["market_fit_reason"] = read_hold[0]
        for item in updated["post_identity_pipeline"]["products"]:
            if item.get("request_id") == job["request_id"]:
                item["market_fit_gate"] = "MARKET_FIT_HOLD"
                item["market_fit_reason"] = read_hold[0]
    return updated, transition
