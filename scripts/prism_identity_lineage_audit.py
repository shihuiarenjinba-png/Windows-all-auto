"""Read-only audit of a Prism post-Identity commit against an immutable PRE_IDENTITY source.

This is NOT Identity capture, CAS authorization, source-sync PASS or Store QA.
The original source SHA remains immutable; a later branch HEAD is a separate candidate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from scripts import github_partner_center_handoff as gh
from scripts import local_partner_center_operator as op

HEX40 = re.compile(r"^[0-9a-f]{40}$")
IDENTITY_MAP = {
    "store_id": "store_id",
    "reserved_display_name": "reserved_display_name",
    "identity_name": "name",
    "publisher": "publisher",
    "publisher_display_name": "publisher_display_name",
    "package_family_name": "package_family_name",
    "package_sid": "package_sid",
}


def hold(reason: str):
    raise op.OperatorHold(reason)


def git(*args: str) -> str:
    try:
        p = subprocess.run(["git", *args], capture_output=True, text=True,
                           check=True, timeout=45)
    except (OSError, subprocess.SubprocessError) as exc:
        raise op.OperatorHold("SOURCE_GIT_EVIDENCE_UNAVAILABLE") from exc
    return p.stdout.strip()


def _json_no_duplicates(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            hold("DUPLICATE_IDENTITY_KEY")
        value[key] = item
    return value


def evaluate(ledger: dict, reference: dict, identity: dict, evidence: dict) -> dict:
    """Evaluate a git-observed one-file commit; never upgrade any CAS gate."""
    payload = gh.queue_payload(ledger)
    pinned = payload["source_sha"]
    head = evidence.get("head")
    if not isinstance(head, str) or not HEX40.fullmatch(head) or head == pinned:
        hold("RETURN_COMMIT_HEAD_INVALID")
    if evidence.get("remote_head") != head or evidence.get("parent") != pinned:
        hold("RETURN_COMMIT_PARENT_OR_REMOTE_CONFLICT")
    if evidence.get("changed") != [["A", payload["identity_return_target"]]]:
        hold("RETURN_COMMIT_UNEXPECTED_FILES")
    observed = ledger.get("rotation_cohorts", {}).get("three_d_jobs", [])
    matching = [x for x in observed if isinstance(x, dict)
                and x.get("request_id") == payload["request_id"]]
    if len(matching) != 1 or matching[0].get("observed_pr_head") != head:
        hold("CENTRAL_OBSERVED_HEAD_CONFLICT")
    required = {
        "request_id": payload["request_id"],
        "source_repository": payload["source_repository"],
        "source_branch": payload["source_branch"],
        "source_sha": pinned,
        "verified_source_sha": pinned,
        "expected_head_sha": pinned,
        "slug": payload["slug"],
        "package_sha256": payload["expected_exe_sha256"],
        "reserved_display_name": payload["display_name"],
        "product_type": "GAME_3D",
    }
    for key, expected in required.items():
        if identity.get(key) != expected:
            hold("IDENTITY_COMMIT_SOURCE_OR_PACKAGE_CONFLICT")
    if identity.get("reviewed") is not True or identity.get("source") != "partner_center":
        hold("IDENTITY_COMMIT_UNREVIEWED")
    if (not isinstance(reference, dict) or set(reference) != {"source", "product", "identity"}
            or reference["source"] != "LOCAL_OPERATOR_MANUAL_REFERENCE"
            or reference["product"] != payload["display_name"]
            or not isinstance(reference["identity"], dict)
            or set(reference["identity"]) != set(IDENTITY_MAP)):
        hold("MANUAL_REFERENCE_SCHEMA_CONFLICT")
    for oracle_key, committed_key in IDENTITY_MAP.items():
        if identity.get(committed_key) != reference["identity"][oracle_key]:
            hold("MANUAL_REFERENCE_COMMIT_CONFLICT")
    return {
        "status": "POST_IDENTITY_COMMIT_CANDIDATE__CAS_RECEIPT_UNVERIFIED",
        "request_id": payload["request_id"],
        "source_repository": payload["source_repository"],
        "source_branch": payload["source_branch"],
        "immutable_source_sha": pinned,
        "observed_return_commit": head,
        "only_changed_file": payload["identity_return_target"],
        "manual_reference_matches": True,
        "local_code_sync": "HOLD_REMOTE_HEAD_CONFLICT",
        "identity_capture_pass": False,
        "identity_route_pass": False,
        "cas_return_pass": False,
        "package_pass": False,
        "e2e_pass": False,
        "next_gate": "REQUEST_SCOPED_CAS_APPROVAL_RECEIPT_AND_INDEPENDENT_LOCAL_CAPTURE",
    }


def audit(central_checkout: Path, source_checkout: Path, reference_path: Path) -> dict:
    # Verify the ledger itself is a clean, exact-HEAD GitHub checkout.
    gh.verify_central(central_checkout)
    ledger = op.read_json(central_checkout / "ops" / "active_e2e_handoff.json")
    payload = gh.queue_payload(ledger)
    source = source_checkout.resolve()
    if (not op._safe_path(source) or not source.is_dir()
            or not (source / ".git").is_dir()
            or not op._safe_path(source / ".git")):
        hold("SOURCE_CHECKOUT_UNSAFE")
    if git("-C", str(source), "status", "--porcelain"):
        hold("SOURCE_CHECKOUT_DIRTY")
    expected_origin = "https://github.com/" + payload["source_repository"] + ".git"
    if git("-C", str(source), "remote", "get-url", "origin") != expected_origin:
        hold("SOURCE_ORIGIN_CONFLICT")
    head = git("-C", str(source), "rev-parse", "HEAD")
    if not HEX40.fullmatch(head):
        hold("SOURCE_HEAD_INVALID")
    remote = git("ls-remote", "--heads", expected_origin,
                 "refs/heads/" + payload["source_branch"])
    if remote != head + "\trefs/heads/" + payload["source_branch"]:
        hold("SOURCE_REMOTE_HEAD_CONFLICT")
    parents = git("-C", str(source), "rev-list", "--parents", "-n", "1", head).split()
    if len(parents) != 2 or parents != [head, payload["source_sha"]]:
        hold("SOURCE_RETURN_PARENT_CONFLICT")
    diff = git("-C", str(source), "diff-tree", "--no-commit-id",
               "--name-status", "-r", head)
    changed = [line.split("\t") for line in diff.splitlines()]
    if changed != [["A", payload["identity_return_target"]]]:
        hold("SOURCE_RETURN_FILES_CONFLICT")
    raw = git("-C", str(source), "show",
              head + ":" + payload["identity_return_target"])
    try:
        identity = json.loads(raw, object_pairs_hook=_json_no_duplicates)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise op.OperatorHold("RETURN_IDENTITY_JSON_INVALID") from exc
    if not isinstance(identity, dict):
        hold("RETURN_IDENTITY_NOT_OBJECT")
    return evaluate(ledger, op.read_json(reference_path, 64_000), identity, {
        "head": head, "remote_head": head, "parent": parents[1], "changed": changed,
    })


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--central-checkout", type=Path, required=True)
    parser.add_argument("--source-checkout", type=Path, required=True)
    parser.add_argument("--manual-reference", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.central_checkout, args.source_checkout,
                       args.manual_reference)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (op.OperatorHold, OSError) as exc:
        reason = str(exc)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,100}", reason):
            reason = "POST_IDENTITY_LINEAGE_UNVERIFIED"
        print(json.dumps({"status": "HOLD_POST_IDENTITY_LINEAGE",
                          "reason": reason, "cas_return_pass": False,
                          "e2e_pass": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
