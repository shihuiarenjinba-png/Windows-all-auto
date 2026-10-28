"""Read-only replay of Prism's claimed GitHub PRE_IDENTITY queue origin.

An Identity commit's job_origin / queue_job_digest are claims, not evidence.
Replay the historical central ledger at the exact claimed SHA, compare it to
the immutable current job, and never infer authenticated UI capture or CAS.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from scripts import github_partner_center_handoff as gh
from scripts import local_partner_center_operator as op
from scripts import prism_identity_lineage_audit as lineage

HEX64 = re.compile(r"^[0-9a-f]{64}$")
DENIED_KEYS = {
    "access_token", "refresh_token", "cookie", "cookies", "session",
    "session_token", "password", "client_secret", "mfa_secret",
    "authorization", "raw_html",
}


def hold(reason: str) -> None:
    raise op.OperatorHold(reason)


def _unique_request(ledger: dict, request_id: str) -> tuple[dict, dict]:
    jobs = ledger.get("rotation_cohorts", {}).get("three_d_jobs", [])
    requests = ledger.get("user_id_requests", {}).get("items", [])
    matched_jobs = [x for x in jobs if isinstance(x, dict)
                    and x.get("request_id") == request_id]
    matched_requests = [x for x in requests if isinstance(x, dict)
                        and x.get("request_id") == request_id]
    if len(matched_jobs) != 1 or len(matched_requests) != 1:
        hold("HISTORICAL_QUEUE_NOT_UNIQUE")
    return matched_jobs[0], matched_requests[0]


def historical_payload(ledger: dict) -> dict:
    """Rebuild the queue at the *historical* creation policy, not today's."""
    job = op.expected_job(ledger, "prism-route-3d")
    source, request = _unique_request(ledger, job["request_id"])
    for key in ("slug", "source_repository", "source_branch", "source_sha",
                "registration_type", "partner_center_selection"):
        if request.get(key) != job[key]:
            hold("HISTORICAL_QUEUE_CROSS_PRODUCT_CONFLICT")
    if request.get("identity_return_target") != gh.IDENTITY_TARGET:
        hold("HISTORICAL_IDENTITY_TARGET_CONFLICT")
    exe = source.get("expected_exe_sha256")
    build = source.get("factory_build_head")
    if not isinstance(exe, str) or not HEX64.fullmatch(exe):
        hold("HISTORICAL_EXE_SHA_INVALID")
    if not isinstance(build, str) or not gh.SHA.fullmatch(build):
        hold("HISTORICAL_BUILD_HEAD_INVALID")
    return {
        **job,
        "expected_exe_sha256": exe,
        "factory_build_head": build,
        "identity_return_target": gh.IDENTITY_TARGET,
        "allow_local_product_creation":
            ledger["partner_center_local_operator"]["allow_local_product_creation"],
    }


def verify(current: dict, historical: dict, identity: dict) -> dict:
    """Pure fail-closed verifier; no network, filesystem mutation or CAS."""
    if not isinstance(identity, dict) or any(
        key.casefold() in DENIED_KEYS for key in identity
    ):
        hold("IDENTITY_PROVENANCE_UNSAFE_FIELDS")
    if (identity.get("job_origin") != "GITHUB_PRE_IDENTITY_QUEUE"
            or identity.get("central_repository") != gh.CENTRAL_REPOSITORY
            or identity.get("central_branch") != gh.CENTRAL_BRANCH
            or identity.get("source_factory") != "3d-game-factory"
            or not isinstance(identity.get("central_head_sha"), str)
            or not gh.SHA.fullmatch(identity["central_head_sha"])
            or not isinstance(identity.get("queue_job_digest"), str)
            or not HEX64.fullmatch(identity["queue_job_digest"])):
        hold("HISTORICAL_QUEUE_ORIGIN_CLAIM_INVALID")
    live = gh.queue_payload(current)
    old = historical_payload(historical)
    for key in live:
        if key == "allow_local_product_creation":
            continue  # historical creation policy may differ; never grant it now
        if old.get(key) != live[key]:
            hold("HISTORICAL_QUEUE_CURRENT_JOB_CONFLICT")
    if old["allow_local_product_creation"] not in (True, False):
        hold("HISTORICAL_CREATION_POLICY_INVALID")
    if gh.queue_digest(old) != identity["queue_job_digest"]:
        hold("HISTORICAL_QUEUE_DIGEST_CONFLICT")
    for key in ("request_id", "slug", "source_repository",
                "source_branch", "source_sha"):
        if identity.get(key) != live[key]:
            hold("HISTORICAL_QUEUE_IDENTITY_BINDING_CONFLICT")
    return {
        "status": "HISTORICAL_QUEUE_REPLAY_MATCH__NOT_CAS_AUTHORIZATION",
        "request_id": live["request_id"],
        "historical_central_head_sha": identity["central_head_sha"],
        "historical_creation_allowed": old["allow_local_product_creation"],
        "current_creation_allowed": False,
        "github_queue_digest_replayed": True,
        "authenticated_ui_capture_pass": False,
        "local_code_sync_pass": False,
        "identity_route_pass": False,
        "cas_return_pass": False,
        "package_pass": False,
        "e2e_pass": False,
    }


def audit(central_checkout: Path, source_checkout: Path,
          reference_path: Path) -> dict:
    # The existing audit proves only an Identity-only descendant candidate.
    candidate = lineage.audit(central_checkout, source_checkout, reference_path)
    if candidate["cas_return_pass"] is not False:
        hold("LINEAGE_GATE_UNEXPECTED_AUTHORIZATION")
    current_head = gh.verify_central(central_checkout)
    current = op.read_json(central_checkout / "ops" / "active_e2e_handoff.json")
    identity = op.read_json(source_checkout / gh.IDENTITY_TARGET, 64_000)
    historical_sha = identity.get("central_head_sha")
    if not isinstance(historical_sha, str) or not gh.SHA.fullmatch(historical_sha):
        hold("HISTORICAL_CENTRAL_SHA_INVALID")
    try:
        lineage.git("-C", str(central_checkout), "merge-base", "--is-ancestor",
                    historical_sha, current_head)
        raw = lineage.git("-C", str(central_checkout), "show",
                          historical_sha + ":ops/active_e2e_handoff.json")
    except op.OperatorHold as exc:
        raise op.OperatorHold("HISTORICAL_CENTRAL_COMMIT_UNVERIFIED") from exc
    try:
        historical = json.loads(raw, object_pairs_hook=lineage._json_no_duplicates)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise op.OperatorHold("HISTORICAL_CENTRAL_LEDGER_INVALID") from exc
    if not isinstance(historical, dict):
        hold("HISTORICAL_CENTRAL_LEDGER_NOT_OBJECT")
    return verify(current, historical, identity)


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
            reason = "HISTORICAL_QUEUE_UNVERIFIED"
        print(json.dumps({
            "status": "HOLD_HISTORICAL_QUEUE_PROVENANCE",
            "reason": reason, "github_queue_digest_replayed": False,
            "cas_return_pass": False, "e2e_pass": False,
        }), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
