"""Authenticated immutable Factory file reader for four accounting SKUs.

This is only the Factory-file trust boundary. It cannot authenticate Actions
fixture results, IRS reviews, Partner Center markets, promotion, or Store QA.
No local files, browser credentials, token persistence, writes, or CAS.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import subprocess

from scripts.accounting_country_gate import FACTORY, SPECS

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_PATH = re.compile(
    r"products/([a-z0-9]+(?:-[a-z0-9]+)*)/"
    r"(market-scope\.json|accounting-validation\.json|"
    r"US_COMPLIANCE_SCOPE\.md|us-compliance-policy\.json|store-description\.txt)\Z"
)
_US_FILES = frozenset({
    "US_COMPLIANCE_SCOPE.md", "us-compliance-policy.json", "store-description.txt",
})
_MAX_RESPONSE = 256 * 1024
_MAX_CONTENT = 65536


class AccountingImmutableReadHold(RuntimeError):
    """Fixed, secret-safe HOLD code only."""


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise AccountingImmutableReadHold(code)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "HOLD_ACCOUNTING_GITHUB_DUPLICATE_KEY")
        result[key] = value
    return result


def _git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def read_accounting_immutable_text(repository: str, path: str, source_sha: str) -> str:
    """Read only an allowlisted accounting file at an exact immutable commit SHA.

    GitHub Contents metadata must match the path, size, and Git blob SHA.
    Authentication comes from the installed gh CLI; no tokens are passed as
    arguments or emitted in error messages. A mocked subprocess is not a
    production attestation.
    """
    _require(repository == FACTORY and isinstance(source_sha, str)
             and _SHA.fullmatch(source_sha) is not None,
             "HOLD_ACCOUNTING_GITHUB_SOURCE_INVALID")
    match = _PATH.fullmatch(path) if isinstance(path, str) else None
    _require(match is not None and match.group(1) in SPECS
             and (match.group(2) not in _US_FILES
                  or match.group(1).startswith("us-")),
             "HOLD_ACCOUNTING_GITHUB_PATH_INVALID")
    endpoint = f"repos/{FACTORY}/contents/{path}?ref={source_sha}"
    try:
        proc = subprocess.run(
            ["gh", "api", "--method", "GET", endpoint],
            capture_output=True, text=True, encoding="utf-8", timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AccountingImmutableReadHold("HOLD_ACCOUNTING_GITHUB_UNAVAILABLE") from exc
    _require(proc.returncode == 0, "HOLD_ACCOUNTING_GITHUB_UNAVAILABLE")
    _require(isinstance(proc.stdout, str)
             and len(proc.stdout.encode("utf-8")) <= _MAX_RESPONSE,
             "HOLD_ACCOUNTING_GITHUB_RESPONSE_INVALID")
    try:
        item = json.loads(proc.stdout, object_pairs_hook=_unique)
    except AccountingImmutableReadHold:
        raise
    except (ValueError, TypeError, UnicodeError) as exc:
        raise AccountingImmutableReadHold("HOLD_ACCOUNTING_GITHUB_RESPONSE_INVALID") from exc
    _require(type(item) is dict and item.get("type") == "file"
             and item.get("path") == path and item.get("encoding") == "base64"
             and type(item.get("size")) is int
             and 0 < item["size"] <= _MAX_CONTENT
             and isinstance(item.get("content"), str)
             and isinstance(item.get("sha"), str)
             and _SHA.fullmatch(item["sha"]) is not None,
             "HOLD_ACCOUNTING_GITHUB_CONTENT_INVALID")
    try:
        raw = base64.b64decode("".join(item["content"].split()), validate=True)
        _require(len(raw) == item["size"]
                 and _git_blob_sha(raw) == item["sha"],
                 "HOLD_ACCOUNTING_GITHUB_BLOB_MISMATCH")
        return raw.decode("utf-8")
    except AccountingImmutableReadHold:
        raise
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise AccountingImmutableReadHold("HOLD_ACCOUNTING_GITHUB_CONTENT_INVALID") from exc
