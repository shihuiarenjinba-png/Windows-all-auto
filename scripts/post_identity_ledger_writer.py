"""Atomic, explicit-only single-writer update for the canonical E2E ledger.

The POST Identity proposal is authenticated and read-only by default. An apply
requires an operator-reviewed canonical commit AND ledger blob, and GitHub's
atomic expectedHeadOid lease. Never use the Contents API's non-atomic HEAD
preflight as the sole concurrency guard. No CAS return, Store or package action.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import subprocess

from scripts.post_identity_github_readers import (
    _gh_json, propose_authenticated_post_identity,
)

REPOSITORY = "shihuiarenjinba-png/Windows-all-auto"
BRANCH = "codex/e2e-belt-connection-20261027"
PATH = "ops/active_e2e_handoff.json"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ALLOWED_CHANGED = frozenset({
    "updated_at_utc", "rotation_cohorts", "user_id_requests",
    "registration_router", "post_identity_pipeline",
})
_MAX_LEDGER_BYTES = 1024 * 1024
_MAX_GRAPHQL_RESPONSE = 128 * 1024
_MUTATION = """mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { oid } }
}"""


class LedgerWriteHold(RuntimeError):
    """Fixed status codes only; never leak gh stderr or authentication details."""


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise LedgerWriteHold(code)


def _sha(value: str) -> None:
    _require(isinstance(value, str) and _SHA.fullmatch(value) is not None,
             "HOLD_CANONICAL_SHA_INVALID")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "HOLD_CANONICAL_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_constant(value):
    raise LedgerWriteHold("HOLD_CANONICAL_JSON_INVALID")


def _json_load(raw: str) -> dict:
    try:
        data = json.loads(raw, object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
    except LedgerWriteHold:
        raise
    except (ValueError, TypeError) as exc:
        raise LedgerWriteHold("HOLD_CANONICAL_JSON_INVALID") from exc
    _require(isinstance(data, dict) and data.get("schema_version") == 1,
             "HOLD_CANONICAL_SCHEMA_INVALID")
    return data


def _git_blob_sha(content: str) -> str:
    """Verify the exact Git object returned by the immutable commit readback."""
    raw = content.encode("utf-8")
    header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(header + raw).hexdigest()


def fetch_canonical_head() -> str:
    data = _gh_json(f"repos/{REPOSITORY}/git/ref/heads/{BRANCH}")
    obj = data.get("object")
    _require(data.get("ref") == f"refs/heads/{BRANCH}"
             and isinstance(obj, dict) and obj.get("type") == "commit",
             "HOLD_CANONICAL_HEAD_INVALID")
    head = obj.get("sha")
    _sha(head)
    return head


def fetch_canonical_ledger(head: str) -> tuple[dict, str]:
    _sha(head)
    data = _gh_json(f"repos/{REPOSITORY}/contents/{PATH}?ref={head}")
    blob = data.get("sha")
    _sha(blob)
    _require(data.get("type") == "file" and data.get("path") == PATH
             and data.get("encoding") == "base64"
             and type(data.get("size")) is int
             and 0 < data["size"] <= _MAX_LEDGER_BYTES
             and isinstance(data.get("content"), str),
             "HOLD_CANONICAL_CONTENT_INVALID")
    try:
        raw = base64.b64decode("".join(data["content"].split()), validate=True)
        _require(len(raw) == data["size"], "HOLD_CANONICAL_CONTENT_INVALID")
        decoded = raw.decode("utf-8")
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise LedgerWriteHold("HOLD_CANONICAL_CONTENT_INVALID") from exc
    return _json_load(decoded), blob


@dataclass(frozen=True)
class PreparedLedger:
    expected_head: str
    expected_blob: str
    slug: str
    transition: str
    content: str


def prepare(slug: str) -> PreparedLedger:
    """Fetch exact canonical snapshot, then build an authenticated proposal."""
    _require(isinstance(slug, str)
             and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) is not None,
             "HOLD_CANONICAL_SLUG_INVALID")
    head = fetch_canonical_head()
    before, blob = fetch_canonical_ledger(head)
    _require(before.get("e2e_pass") is False
             and before.get("e2e_status") == "HOLD",
             "HOLD_CANONICAL_UNEXPECTED_E2E_STATE")
    after, transition = propose_authenticated_post_identity(before, slug)
    _require(isinstance(after, dict)
             and after.get("e2e_pass") is False
             and after.get("e2e_status") == "HOLD"
             and after.get("new_product_allowed") == before.get("new_product_allowed"),
             "HOLD_CANONICAL_GATE_ESCALATION")
    changed = {key for key in set(before) | set(after)
               if before.get(key) != after.get(key)}
    _require(changed <= _ALLOWED_CHANGED,
             "HOLD_CANONICAL_UNRELATED_MUTATION")
    # Timestamp is metadata, never independent proof of a successful gate.
    after["updated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    content = json.dumps(after, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    _require(len(content.encode("utf-8")) <= _MAX_LEDGER_BYTES,
             "HOLD_CANONICAL_CONTENT_TOO_LARGE")
    _require(fetch_canonical_head() == head, "HOLD_CANONICAL_HEAD_DRIFT")
    return PreparedLedger(head, blob, slug, transition, content)


def apply(prepared: PreparedLedger, *, reviewed_head: str,
          reviewed_blob: str) -> str:
    """Explicit write, atomically leased against the exact reviewed HEAD."""
    _require(isinstance(prepared, PreparedLedger),
             "HOLD_CANONICAL_PROPOSAL_INVALID")
    _sha(reviewed_head)
    _sha(reviewed_blob)
    _require(reviewed_head == prepared.expected_head
             and reviewed_blob == prepared.expected_blob,
             "HOLD_CANONICAL_REVIEW_PIN_MISMATCH")
    _require(fetch_canonical_head() == reviewed_head,
             "HOLD_CANONICAL_HEAD_DRIFT")
    encoded = base64.b64encode(prepared.content.encode("utf-8")).decode("ascii")
    variables = {"input": {
        "branch": {"repositoryNameWithOwner": REPOSITORY, "branchName": BRANCH},
        "expectedHeadOid": reviewed_head,
        "message": {"headline": f"Reconcile {prepared.slug} POST Identity evidence (HOLD gates)"},
        "fileChanges": {"additions": [{"path": PATH, "contents": encoded}]},
    }}
    try:
        proc = subprocess.run(
            ["gh", "api", "graphql", "--input", "-"],
            input=json.dumps({"query": _MUTATION, "variables": variables}),
            capture_output=True, text=True, encoding="utf-8",
            timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LedgerWriteHold("HOLD_CANONICAL_ATOMIC_WRITE_UNAVAILABLE") from exc
    _require(proc.returncode == 0
             and len(proc.stdout.encode("utf-8")) <= _MAX_GRAPHQL_RESPONSE,
             "HOLD_CANONICAL_ATOMIC_WRITE_FAILED")
    try:
        response = json.loads(proc.stdout)
    except (ValueError, TypeError) as exc:
        raise LedgerWriteHold("HOLD_CANONICAL_ATOMIC_RESPONSE_INVALID") from exc
    _require(isinstance(response, dict)
             and not response.get("errors")
             and isinstance(response.get("data"), dict)
             and isinstance(response["data"].get("createCommitOnBranch"), dict)
             and isinstance(response["data"]["createCommitOnBranch"].get("commit"), dict),
             "HOLD_CANONICAL_ATOMIC_WRITE_REJECTED")
    commit = response["data"]["createCommitOnBranch"]["commit"].get("oid")
    _sha(commit)
    # A mutation acknowledgement alone is not a verified ledger update.
    # Read the new immutable commit and verify the exact Git blob and JSON.
    # If readback fails, report HOLD even if the write may have succeeded;
    # the next run can independently reconcile the already-written state.
    try:
        persisted, persisted_blob = fetch_canonical_ledger(commit)
    except Exception as exc:
        raise LedgerWriteHold("HOLD_CANONICAL_POSTWRITE_READ_UNAVAILABLE") from exc
    _require(persisted_blob == _git_blob_sha(prepared.content)
             and persisted == _json_load(prepared.content),
             "HOLD_CANONICAL_POSTWRITE_CONTENT_MISMATCH")
    return commit


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only by default; exact-head write only")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-head")
    parser.add_argument("--expected-blob")
    args = parser.parse_args(argv)
    if args.apply and (not args.expected_head or not args.expected_blob):
        parser.error("--apply requires --expected-head and --expected-blob")
    try:
        proposal = prepare(args.slug)
        output = {
            "status": "PROPOSAL_ONLY", "slug": proposal.slug,
            "transition": proposal.transition,
            "expected_head": proposal.expected_head,
            "expected_blob": proposal.expected_blob,
            "store_submission": "NOT_PERFORMED", "e2e_pass": False,
        }
        if args.apply:
            output["commit_sha"] = apply(
                proposal, reviewed_head=args.expected_head,
                reviewed_blob=args.expected_blob,
            )
            output["status"] = "ATOMIC_LEDGER_COMMIT_CREATED"
        print(json.dumps(output, sort_keys=True))
        return 0
    except Exception as exc:
        # Never include arbitrary gh stderr or source payloads in receipts.
        code = str(exc) if isinstance(exc, LedgerWriteHold) else (
            str(exc) if type(exc).__name__ in {
                "AuthenticatedReadHold", "ReconcileHold", "MarketFitReadHold"
            } else "HOLD_CANONICAL_RECONCILIATION_UNAVAILABLE"
        )
        print(json.dumps({"status": "HOLD", "code": code, "e2e_pass": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
