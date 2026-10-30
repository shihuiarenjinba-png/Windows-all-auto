"""Authenticated, read-only Factory readers for POST_IDENTITY reconciliation.

All reads are pinned to a verified commit. No local files, Partner Center,
browser credentials, GitHub writes, package builds or Store operations.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import subprocess
from urllib.parse import quote

_REPO = re.compile(r"shihuiarenjinba-png/(?:AI-App-Factory|AI-Game-Factory|3d-game-factory)\Z")
_BRANCH = re.compile(r"codex/[A-Za-z0-9_-]+(?:[./-][A-Za-z0-9_-]+)*\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_TARGET = re.compile(r"products/[a-z0-9]+(?:-[a-z0-9]+)*/store/approved-identity\.json\Z")
_MAX_RESPONSE = 512 * 1024
_MAX_IDENTITY = 65536


class AuthenticatedReadHold(RuntimeError):
    """Fixed failure code only: never attach subprocess output or credentials."""


def _require(value: bool, code: str) -> None:
    if not value:
        raise AuthenticatedReadHold(code)


def _gh_json(endpoint: str) -> dict:
    try:
        result = subprocess.run(
            ["gh", "api", "--method", "GET", endpoint],
            capture_output=True, text=True, encoding="utf-8", timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuthenticatedReadHold("HOLD_POST_GITHUB_READ_UNAVAILABLE") from exc
    _require(result.returncode == 0, "HOLD_POST_GITHUB_READ_UNAVAILABLE")
    _require(len(result.stdout.encode("utf-8")) <= _MAX_RESPONSE,
             "HOLD_POST_GITHUB_RESPONSE_TOO_LARGE")
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise AuthenticatedReadHold("HOLD_POST_GITHUB_JSON_INVALID") from exc
    _require(isinstance(data, dict), "HOLD_POST_GITHUB_JSON_INVALID")
    return data


def _repo(repository: str) -> None:
    _require(isinstance(repository, str) and _REPO.fullmatch(repository) is not None,
             "HOLD_POST_REPOSITORY_INVALID")


def _sha(value: str) -> None:
    _require(isinstance(value, str) and _SHA.fullmatch(value) is not None,
             "HOLD_POST_SHA_INVALID")


def fetch_factory_branch_head(repository: str, branch: str) -> str:
    _repo(repository)
    _require(isinstance(branch, str) and _BRANCH.fullmatch(branch) is not None
             and ".." not in branch and "//" not in branch,
             "HOLD_POST_BRANCH_INVALID")
    ref = quote(branch, safe="/")
    data = _gh_json(f"repos/{repository}/git/ref/heads/{ref}")
    obj = data.get("object")
    _require(data.get("ref") == f"refs/heads/{branch}"
             and isinstance(obj, dict) and obj.get("type") == "commit",
             "HOLD_POST_BRANCH_RESPONSE_INVALID")
    head = obj.get("sha")
    _sha(head)
    return head


def fetch_approved_identity(repository: str, path: str, commit_sha: str) -> str:
    _repo(repository)
    _sha(commit_sha)
    _require(isinstance(path, str) and _TARGET.fullmatch(path) is not None,
             "HOLD_POST_IDENTITY_PATH_INVALID")
    data = _gh_json(f"repos/{repository}/contents/{path}?ref={commit_sha}")
    _require(data.get("type") == "file" and data.get("path") == path
             and data.get("encoding") == "base64"
             and type(data.get("size")) is int
             and 0 < data["size"] <= _MAX_IDENTITY
             and isinstance(data.get("content"), str),
             "HOLD_POST_IDENTITY_CONTENT_INVALID")
    try:
        raw = base64.b64decode("".join(data["content"].split()), validate=True)
        _require(len(raw) == data["size"], "HOLD_POST_IDENTITY_CONTENT_INVALID")
        return raw.decode("utf-8")
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise AuthenticatedReadHold("HOLD_POST_IDENTITY_CONTENT_INVALID") from exc


def verify_identity_only_ancestry(repository: str, source_sha: str,
                                  return_head: str, identity_path: str) -> bool:
    """Require exactly one added Identity file on a one-commit source descendant.

    The compare response is authoritative; an operator-provided receipt or a
    same-name file on an unrelated branch cannot satisfy this gate.
    """
    _repo(repository)
    _sha(source_sha)
    _sha(return_head)
    _require(isinstance(identity_path, str)
             and _TARGET.fullmatch(identity_path) is not None,
             "HOLD_POST_IDENTITY_PATH_INVALID")
    _require(source_sha != return_head, "HOLD_POST_RETURN_NOT_OBSERVED")
    data = _gh_json(f"repos/{repository}/compare/{source_sha}...{return_head}")
    commits = data.get("commits")
    files = data.get("files")
    base = data.get("base_commit")
    merge_base = data.get("merge_base_commit")
    _require(data.get("status") == "ahead"
             and type(data.get("ahead_by")) is int and data["ahead_by"] == 1
             and type(data.get("behind_by")) is int and data["behind_by"] == 0
             and type(data.get("total_commits")) is int and data["total_commits"] == 1
             and isinstance(base, dict) and base.get("sha") == source_sha
             and isinstance(merge_base, dict) and merge_base.get("sha") == source_sha
             and isinstance(commits, list) and len(commits) == 1
             and isinstance(commits[0], dict)
             and commits[0].get("sha") == return_head
             and isinstance(files, list) and len(files) == 1
             and isinstance(files[0], dict)
             and files[0].get("filename") == identity_path
             and files[0].get("status") == "added",
             "HOLD_POST_IDENTITY_ONLY_ANCESTRY_CONFLICT")
    return True


def propose_authenticated_post_identity(ledger: dict, slug: str) -> tuple[dict, str]:
    """Propose a new ledger in memory; never commit it.

    MARKET_FIT remains HOLD without a verified, immutable Factory review.
    Only the 36-minute owner can write the canonical ledger with an
    expected-HEAD boundary after reviewing the proposal.
    """
    from scripts.market_fit_review_reader import reconcile_with_reviewed_market_fit
    return reconcile_with_reviewed_market_fit(
        ledger, slug,
        fetch_branch_head=fetch_factory_branch_head,
        fetch_approved_file=fetch_approved_identity,
        verify_source_ancestry=verify_identity_only_ancestry,
    )
