"""Authenticated GitHub readers for immutable source/review market-fit evidence.

No Partner Center, CAS, Store, package or ledger writes. GH errors are
redacted to fixed HOLD codes, never raw stderr or authentication data.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import subprocess

from scripts.market_fit_gate import assess_market_fit

REPO = re.compile(r"shihuiarenjinba-png/[A-Za-z0-9_.-]+\Z")
PATH = re.compile(r"products/[a-z0-9]+(?:-[a-z0-9]+)*/market-fit\.json\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_BYTES = 65536


class MarketFitReadHold(RuntimeError):
    pass


def _gh_json(endpoint):
    try:
        proc = subprocess.run(["gh", "api", "--method", "GET", endpoint],
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MarketFitReadHold("HOLD_MARKET_FIT_GITHUB_READ") from exc
    if proc.returncode:
        if re.search(r"\bHTTP 404\b", proc.stderr or ""):
            return None
        raise MarketFitReadHold("HOLD_MARKET_FIT_GITHUB_READ")
    try:
        return json.loads(proc.stdout)
    except (ValueError, TypeError) as exc:
        raise MarketFitReadHold("HOLD_MARKET_FIT_GITHUB_CONTENT") from exc


def _valid_repo_sha(repository, sha):
    return (isinstance(repository, str) and REPO.fullmatch(repository)
            and isinstance(sha, str) and SHA.fullmatch(sha))


def verify_review_ancestry(repository, source_sha, review_sha):
    if (not _valid_repo_sha(repository, source_sha)
            or not _valid_repo_sha(repository, review_sha)
            or source_sha == review_sha):
        raise MarketFitReadHold("HOLD_MARKET_FIT_UNSAFE_SOURCE_REF")
    item = _gh_json(f"repos/{repository}/compare/{source_sha}...{review_sha}")
    if not isinstance(item, dict):
        raise MarketFitReadHold("HOLD_MARKET_FIT_REVIEW_ANCESTRY")
    return (item.get("status") == "ahead"
            and type(item.get("behind_by")) is int and item["behind_by"] == 0
            and isinstance(item.get("base_commit"), dict)
            and item["base_commit"].get("sha") == source_sha
            and isinstance(item.get("head_commit"), dict)
            and item["head_commit"].get("sha") == review_sha)


def read_factory_market_fit(repository, path, review_sha):
    if (not _valid_repo_sha(repository, review_sha)
            or not isinstance(path, str) or not PATH.fullmatch(path)):
        raise MarketFitReadHold("HOLD_MARKET_FIT_UNSAFE_SOURCE_REF")
    item = _gh_json(f"repos/{repository}/contents/{path}?ref={review_sha}")
    if item is None:
        return None
    if (not isinstance(item, dict) or item.get("type") != "file"
            or item.get("path") != path or item.get("encoding") != "base64"
            or type(item.get("size")) is not int
            or not 0 < item["size"] <= MAX_BYTES
            or not isinstance(item.get("content"), str)):
        raise MarketFitReadHold("HOLD_MARKET_FIT_GITHUB_CONTENT")
    try:
        raw = base64.b64decode("".join(item["content"].split()), validate=True)
        if len(raw) != item["size"]:
            raise ValueError()
        return raw.decode("utf-8")
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise MarketFitReadHold("HOLD_MARKET_FIT_GITHUB_CONTENT") from exc


def assess_factory_market_fit(job):
    try:
        return assess_market_fit(job, read_factory_market_fit, verify_review_ancestry)
    except MarketFitReadHold as exc:
        return "MARKET_FIT_HOLD", str(exc)
