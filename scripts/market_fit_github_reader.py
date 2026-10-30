"""Authenticated, immutable Factory MARKET_FIT reader for the E2E owner.

Read-only. Never uses Partner Center, browser sessions, CAS, package or Store APIs.
The caller supplies a pinned Factory job; this module never reads a moving branch.
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
    """A fixed, secret-safe read error. Do not attach raw gh stderr."""


def read_factory_market_fit(repository: str, path: str, source_sha: str) -> str | None:
    """Fetch UTF-8 Factory evidence at the *immutable* source SHA via gh auth.

    None means authenticated GitHub returned HTTP 404. Any other failure holds.
    Never substitute a branch, a local file, or a user-provided JSON.
    """
    if (not isinstance(repository, str) or not REPO.fullmatch(repository)
            or not isinstance(path, str) or not PATH.fullmatch(path)
            or not isinstance(source_sha, str) or not SHA.fullmatch(source_sha)):
        raise MarketFitReadHold("HOLD_MARKET_FIT_UNSAFE_SOURCE_REF")
    endpoint = f"repos/{repository}/contents/{path}?ref={source_sha}"
    try:
        proc = subprocess.run(
            ["gh", "api", "--method", "GET", endpoint],
            capture_output=True, text=True, encoding="utf-8", timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MarketFitReadHold("HOLD_MARKET_FIT_GITHUB_READ") from exc
    if proc.returncode != 0:
        if re.search(r"\bHTTP 404\b", proc.stderr or ""):
            return None
        raise MarketFitReadHold("HOLD_MARKET_FIT_GITHUB_READ")
    try:
        item = json.loads(proc.stdout)
        if (not isinstance(item, dict) or item.get("type") != "file"
                or item.get("path") != path or item.get("encoding") != "base64"
                or type(item.get("size")) is not int
                or not 0 < item["size"] <= MAX_BYTES
                or not isinstance(item.get("content"), str)):
            raise MarketFitReadHold("HOLD_MARKET_FIT_GITHUB_CONTENT")
        raw = base64.b64decode("".join(item["content"].split()), validate=True)
        if len(raw) != item["size"]:
            raise MarketFitReadHold("HOLD_MARKET_FIT_GITHUB_CONTENT")
        return raw.decode("utf-8")
    except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error) as exc:
        raise MarketFitReadHold("HOLD_MARKET_FIT_GITHUB_CONTENT") from exc


def assess_factory_market_fit(job: dict) -> tuple[str, str]:
    """Safe read-only classification. Never converts API/auth errors into PASS."""
    try:
        return assess_market_fit(job, read_factory_market_fit)
    except MarketFitReadHold as exc:
        return "MARKET_FIT_HOLD", str(exc)


def reconcile_with_authenticated_market_fit(
    ledger: dict, slug: str, *, fetch_branch_head, fetch_approved_file,
    verify_source_ancestry,
) -> tuple[dict, str]:
    """Wire the real authenticated reader to the pure POST Identity reconciler.

    Returns a proposed ledger copy only. The 36-minute owner remains the sole
    central-ledger writer; no implicit CAS or package build is performed.
    """
    from scripts.reconcile_post_identity import reconcile_approved_return
    return reconcile_approved_return(
        ledger, slug, fetch_branch_head=fetch_branch_head,
        fetch_approved_file=fetch_approved_file,
        verify_source_ancestry=verify_source_ancestry,
        fetch_market_fit=lambda repository, path, sha: _read_or_hold(repository, path, sha),
    )


def _read_or_hold(repository: str, path: str, sha: str) -> str | None:
    try:
        return read_factory_market_fit(repository, path, sha)
    except MarketFitReadHold:
        # Reconciler is read-only. Fail closed before a central-ledger commit.
        raise
