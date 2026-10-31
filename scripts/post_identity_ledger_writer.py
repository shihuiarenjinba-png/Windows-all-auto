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
import copy
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
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


def _finite_float(value: str) -> float:
    # JSON permits 1e999 syntactically, but Python float() yields infinity.
    # Treat numeric overflow as invalid canonical evidence, not a valid gate.
    number = float(value)
    _require(math.isfinite(number), "HOLD_CANONICAL_JSON_INVALID")
    return number


def _json_load(raw: str) -> dict:
    try:
        data = json.loads(raw, object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant,
                          parse_float=_finite_float)
    except LedgerWriteHold:
        raise
    except (ValueError, TypeError) as exc:
        raise LedgerWriteHold("HOLD_CANONICAL_JSON_INVALID") from exc
    _require(isinstance(data, dict) and type(data.get("schema_version")) is int
             and data["schema_version"] == 1,
             "HOLD_CANONICAL_SCHEMA_INVALID")
    return data


def _git_blob_sha(content: str) -> str:
    """Verify the exact Git object returned by the immutable commit readback."""
    raw = content.encode("utf-8")
    header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(header + raw).hexdigest()


def _proposal_sha256(content: str) -> str:
    """Pin all substantive proposal fields, excluding volatile audit time.

    prepare() regenerates updated_at_utc on each invocation. Hashing raw JSON
    would make a reviewed proposal impossible to apply in a later process.
    Only that timestamp is excluded; any Identity, gate or routing change
    invalidates the operator's reviewed digest.
    """
    try:
        data = json.loads(content, object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant,
                          parse_float=_finite_float)
    except LedgerWriteHold:
        raise
    except (ValueError, TypeError) as exc:
        raise LedgerWriteHold("HOLD_CANONICAL_PROPOSAL_INVALID") from exc
    _require(isinstance(data, dict), "HOLD_CANONICAL_PROPOSAL_INVALID")
    data.pop("updated_at_utc", None)
    normalized = json.dumps(data, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
    parsed = _json_load(decoded)
    # The contents endpoint must not silently bind a valid JSON payload to
    # a different Git blob object. Check before using the blob as a review pin.
    _require(blob == _git_blob_sha(decoded),
             "HOLD_CANONICAL_BLOB_CONTENT_MISMATCH")
    return parsed, blob


@dataclass(frozen=True)
class PreparedLedger:
    expected_head: str
    expected_blob: str
    slug: str
    transition: str
    content: str



def _assert_only_target_records_changed(original: dict, after: dict,
                                        slug: str) -> None:
    """Reject collateral edits inside otherwise allowlisted ledger sections.

    The authenticated reconciler may update one product and its three bound
    auxiliary records, but may not mutate another job, reorder a queue, or
    change cohort metrics/policy through an allowlisted top-level dictionary.
    """
    code = "HOLD_CANONICAL_CROSS_PRODUCT_MUTATION"
    before_cohorts = original.get("rotation_cohorts")
    after_cohorts = after.get("rotation_cohorts")
    _require(isinstance(before_cohorts, dict) and isinstance(after_cohorts, dict),
             code)
    positions = []
    for collection in ("app_jobs", "game_jobs", "three_d_jobs"):
        jobs = before_cohorts.get(collection, [])
        _require(isinstance(jobs, list), code)
        for index, job in enumerate(jobs):
            _require(isinstance(job, dict), code)
            if job.get("slug") == slug:
                positions.append((collection, index, job))
    _require(len(positions) == 1, code)
    collection, index, job = positions[0]
    current_jobs = after_cohorts.get(collection)
    _require(isinstance(current_jobs, list) and len(current_jobs) > index
             and isinstance(current_jobs[index], dict)
             and current_jobs[index].get("slug") == slug
             and current_jobs[index].get("request_id") == job.get("request_id"),
             code)
    def require_pinned_binding(old: dict, new: dict,
                               fields: tuple[str, ...]) -> None:
        # Status/evidence may advance, but provenance must never be rewritten,
        # deleted or injected by a reconciliation adapter.
        _require(isinstance(old, dict) and isinstance(new, dict), code)
        for field in fields:
            _require((field in old) == (field in new)
                     and old.get(field) == new.get(field), code)

    def require_only_reviewed_changes(old: dict, new: dict,
                                      allowed: frozenset[str]) -> None:
        # The target is not a free-form mutation slot. A future adapter must
        # not inject a new Store, package, QA or sales PASS field under a name
        # that was not anticipated by the downstream blacklist.
        for field in set(old) | set(new):
            if field not in allowed:
                _require((field in old) == (field in new)
                         and old.get(field) == new.get(field),
                         "HOLD_CANONICAL_UNREVIEWED_TARGET_FIELD_MUTATION")

    require_pinned_binding(job, current_jobs[index], (
        "product_type", "display_name", "slug", "request_id",
        "source_repository", "source_branch", "source_sha",
        "identity_return_target", "expected_exe_sha256",
        "expected_exe_bytes", "packaging_family", "packaging_strategy",
        "registration_type", "partner_center_selection",
        "factory_build_head", "market_fit_review_commit_sha",
    ))
    # This writer reconciles Identity and reviewed MARKET_FIT only. It cannot
    # silently turn a pre-Identity EXE into a real package, local QA pass or
    # Store submission, even if a future adapter starts returning those fields.
    downstream_code = "HOLD_CANONICAL_DOWNSTREAM_GATE_MUTATION"
    for field in (
        "real_msix", "local_execution", "store_submission",
        "real_msix_sha256", "signed_msix_sha256",
        "github_backlog_receipt", "local_pull_receipt",
        "checker_receipt", "gui_install_qa_receipt",
    ):
        _require((field in job) == (field in current_jobs[index])
                 and job.get(field) == current_jobs[index].get(field),
                 downstream_code)
    _require(job.get("package_version_gate") in (None, "HOLD")
             and current_jobs[index].get("package_version_gate") in (None, "HOLD")
             and current_jobs[index].get("identity_cas_allowed") is False,
             downstream_code)
    require_only_reviewed_changes(job, current_jobs[index], frozenset({
        "status", "identity_status", "identity_return_commit_sha",
        "identity_store_id", "identity_pfn", "identity_cas_allowed",
        "package_version_gate", "next_action", "market_fit_gate",
        "market_fit_reason", "market_fit_evidence_verified",
    }))
    restored = copy.deepcopy(after_cohorts)
    restored[collection][index] = copy.deepcopy(job)
    _require(restored == before_cohorts, code)

    def check_aux(section: str, list_key: str, identity_key: str,
                  identity_value: str, pinned_fields: tuple[str, ...],
                  allowed_changes: frozenset[str]) -> None:
        old = original.get(section)
        new = after.get(section)
        _require(isinstance(old, dict) and isinstance(new, dict), code)
        old_items = old.get(list_key)
        new_items = new.get(list_key)
        _require(isinstance(old_items, list) and isinstance(new_items, list)
                 and len(old_items) == len(new_items), code)
        old_positions = [i for i, item in enumerate(old_items)
                         if isinstance(item, dict)
                         and item.get(identity_key) == identity_value]
        new_positions = [i for i, item in enumerate(new_items)
                         if isinstance(item, dict)
                         and item.get(identity_key) == identity_value]
        _require(len(old_positions) == 1 and new_positions == old_positions,
                 code)
        require_pinned_binding(old_items[old_positions[0]],
                               new_items[new_positions[0]], pinned_fields)
        require_only_reviewed_changes(old_items[old_positions[0]],
                                      new_items[new_positions[0]],
                                      allowed_changes)
        candidate = copy.deepcopy(new)
        candidate[list_key][old_positions[0]] = copy.deepcopy(
            old_items[old_positions[0]]
        )
        _require(candidate == old, code)

    request_id = job.get("request_id")
    display_name = job.get("display_name")
    _require(isinstance(request_id, str) and bool(request_id)
             and isinstance(display_name, str) and bool(display_name), code)
    check_aux("user_id_requests", "items", "request_id", request_id, (
        "request_id", "product_name", "repo", "source_branch", "source_sha",
        "identity_return_target", "product_type", "slug",
        "registration_type", "partner_center_selection",
    ), frozenset({"status", "requested_fields", "next_gate",
                  "allow_local_product_creation"}))
    check_aux("registration_router", "entries", "product", display_name, (
        "product", "repository", "request_id", "slug", "product_type",
        "source_branch", "source_sha", "identity_return_target",
        "registration_type", "partner_center_selection",
    ), frozenset({"identity_status", "next_action"}))
    check_aux("post_identity_pipeline", "products", "request_id", request_id, (
        "product", "lane", "request_id", "source_repository",
        "source_branch", "source_sha", "identity_return_target",
        "gates", "package_version_gate", "real_msix_sha256",
        "github_backlog_receipt", "local_pull_receipt",
        "checker_receipt", "gui_install_qa_receipt",
        "store_submission", "submission_draft_opened",
    ), frozenset({
        "state", "identity_status", "identity_return_commit_sha",
        "identity_store_id", "identity_pfn", "market_fit_gate",
        "market_fit_reason", "market_fit_evidence_verified", "next_action",
    }))


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
    # An adapter may mutate the supplied ledger in place. Preserve the exact
    # authenticated pre-proposal snapshot for all escalation/diff checks.
    original = copy.deepcopy(before)
    after, transition = propose_authenticated_post_identity(before, slug)
    _require(isinstance(after, dict)
             and after.get("e2e_pass") is False
             and after.get("e2e_status") == "HOLD"
             and after.get("new_product_allowed") == original.get("new_product_allowed"),
             "HOLD_CANONICAL_GATE_ESCALATION")
    changed = {key for key in set(original) | set(after)
               if original.get(key) != after.get(key)}
    _require(changed <= _ALLOWED_CHANGED,
             "HOLD_CANONICAL_UNRELATED_MUTATION")
    _assert_only_target_records_changed(original, after, slug)
    # Timestamp is metadata, never independent proof of a successful gate.
    after["updated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    content = json.dumps(after, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    _require(len(content.encode("utf-8")) <= _MAX_LEDGER_BYTES,
             "HOLD_CANONICAL_CONTENT_TOO_LARGE")
    _require(fetch_canonical_head() == head, "HOLD_CANONICAL_HEAD_DRIFT")
    return PreparedLedger(head, blob, slug, transition, content)


def apply(prepared: PreparedLedger, *, reviewed_head: str,
          reviewed_blob: str, reviewed_proposal_sha256: str) -> str:
    """Explicit write, atomically leased against the exact reviewed HEAD."""
    _require(isinstance(prepared, PreparedLedger),
             "HOLD_CANONICAL_PROPOSAL_INVALID")
    _sha(reviewed_head)
    _sha(reviewed_blob)
    _require(isinstance(reviewed_proposal_sha256, str)
             and re.fullmatch(r"[0-9a-f]{64}", reviewed_proposal_sha256) is not None
             and reviewed_proposal_sha256 == _proposal_sha256(prepared.content),
             "HOLD_CANONICAL_PROPOSAL_REVIEW_MISMATCH")
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
    parser.add_argument("--expected-proposal-sha256")
    args = parser.parse_args(argv)
    if args.apply and (not args.expected_head or not args.expected_blob
                       or not args.expected_proposal_sha256):
        parser.error("--apply requires --expected-head, --expected-blob "
                     "and --expected-proposal-sha256")
    try:
        proposal = prepare(args.slug)
        output = {
            "status": "PROPOSAL_ONLY", "slug": proposal.slug,
            "transition": proposal.transition,
            "expected_head": proposal.expected_head,
            "expected_blob": proposal.expected_blob,
            "proposal_sha256": _proposal_sha256(proposal.content),
            "store_submission": "NOT_PERFORMED", "e2e_pass": False,
        }
        if args.apply:
            output["commit_sha"] = apply(
                proposal, reviewed_head=args.expected_head,
                reviewed_blob=args.expected_blob,
                reviewed_proposal_sha256=args.expected_proposal_sha256,
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
