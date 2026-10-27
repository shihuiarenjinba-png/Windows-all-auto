"""Opt-in LOCAL Windows Identity CAS return. Never uploads Partner Center evidence.

Reads the pinned GitHub handoff ledger, checks the exact Factory source ref and
local Provisioner checkout, then delegates the only write to Provisioner's
--official-identity --apply (which performs GitHub expectedHeadOid CAS).
The receipt and raw Provisioner result remain OUTSIDE the repository.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, urlparse

REMOTE = "shihuiarenjinba-png/Windows-all-auto"
LEDGER_REF = "codex/e2e-belt-connection-20261027"
LEDGER_PATH = "ops/active_e2e_handoff.json"
FACTORY = "shihuiarenjinba-png/AI-Game-Factory"
PROVISIONER = "shihuiarenjinba-png/Repository-Provisioner-game"
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUEST = re.compile(r"^game-signal-sprint-[0-9a-f]{40}$")


class Gate(Exception):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status, self.reason = status, reason


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise Gate("HOLD", "DUPLICATE_JSON_KEY")
        obj[key] = value
    return obj


def parse_json(raw: str, limit: int = 200_000) -> dict:
    if len(raw.encode("utf-8")) > limit:
        raise Gate("HOLD", "JSON_SIZE_LIMIT")
    try:
        data = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as exc:
        raise Gate("HOLD", "INVALID_JSON") from exc
    if not isinstance(data, dict):
        raise Gate("HOLD", "JSON_ROOT_NOT_OBJECT")
    return data


def gh_api(endpoint: str) -> dict:
    try:
        result = subprocess.run(["gh", "api", "-X", "GET", endpoint],
                                capture_output=True, text=True, encoding="utf-8",
                                timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Gate("RETRYABLE_FAILURE", "GITHUB_READ_UNAVAILABLE") from exc
    if result.returncode:
        # Do not expose gh stderr: it can contain authentication details.
        raise Gate("RETRYABLE_FAILURE", "GITHUB_READ_UNAVAILABLE")
    return parse_json(result.stdout)


def read_ledger() -> dict:
    endpoint = "repos/" + REMOTE + "/contents/" + LEDGER_PATH + "?ref=" + quote(LEDGER_REF, safe="")
    item = gh_api(endpoint)
    if item.get("encoding") != "base64" or not isinstance(item.get("content"), str):
        raise Gate("HOLD", "LEDGER_ENCODING_INVALID")
    try:
        decoded = base64.b64decode("".join(item["content"].split()), validate=True).decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise Gate("HOLD", "LEDGER_DECODE_FAILED") from exc
    return parse_json(decoded)


def validate_ledger(ledger: dict, args) -> tuple[dict, dict]:
    product = ledger.get("active_product")
    if not isinstance(product, dict):
        raise Gate("HOLD", "NO_ACTIVE_PRODUCT")
    pinned = {
        "lane": "GAME", "product_type": "GAME", "source_factory": "AI-Game-Factory",
        "source_repository": FACTORY, "source_branch": args.source_branch,
        "source_sha": args.source_sha, "expected_head_sha": args.source_sha,
        "request_id": args.request_id, "slug": "signal-sprint",
    }
    if (ledger.get("new_product_allowed") is not False or ledger.get("e2e_pass") is not False
            or any(product.get(k) != v for k, v in pinned.items())
            or not SHA.fullmatch(args.source_sha)
            or not REQUEST.fullmatch(args.request_id)
            or args.request_id != "game-signal-sprint-" + args.source_sha
            or args.source_branch != "codex/game-signal-sprint-undo-20261027"):
        raise Gate("CONFLICT", "PINNED_PRODUCT_OR_SHA_MISMATCH")
    if product.get("factory_return_commit_sha") or product.get("approved_identity_json"):
        raise Gate("HOLD", "IDENTITY_ALREADY_RECORDED_RECONCILE")
    safety = product.get("provisioner_package_safety")
    if (not isinstance(safety, dict) or safety.get("repository") != PROVISIONER
            or safety.get("branch") != args.provisioner_branch
            or safety.get("head_sha") != args.provisioner_sha
            or not SHA.fullmatch(args.provisioner_sha)):
        raise Gate("CONFLICT", "PROVISIONER_PIN_MISMATCH")
    return product, safety


def source_head() -> str:
    item = gh_api("repos/" + FACTORY + "/git/ref/heads/codex/game-signal-sprint-undo-20261027")
    sha = item.get("object", {}).get("sha")
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise Gate("RETRYABLE_FAILURE", "FACTORY_HEAD_UNVERIFIED")
    return sha


def check_local_paths(args):
    repo = args.provisioner_root.resolve(strict=True)
    if not (repo / "provisioner.py").is_file() or not (repo / "config.json").is_file():
        raise Gate("HOLD", "LOCAL_PROVISIONER_MISSING")
    try:
        cp = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                            capture_output=True, text=True, timeout=20, check=False)
        branch = subprocess.run(["git", "-C", str(repo), "branch", "--show-current"],
                                capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Gate("HOLD", "LOCAL_GIT_UNAVAILABLE") from exc
    if (cp.returncode or cp.stdout.strip() != args.provisioner_sha or
            branch.returncode or branch.stdout.strip() != args.provisioner_branch):
        raise Gate("CONFLICT", "LOCAL_PROVISIONER_CHECKOUT_MISMATCH")
    config = parse_json((repo / "config.json").read_text(encoding="utf-8"), 32_768)
    if (config.get("product_type") != "GAME" or config.get("source_factory") != "AI-Game-Factory"
            or config.get("source_repository") != FACTORY):
        raise Gate("CONFLICT", "LOCAL_PROVISIONER_CONFIG_MISMATCH")
    local = args.local_dir.resolve()
    evidence = args.official_identity.resolve()
    for path in (local, evidence):
        if path == repo or path.is_relative_to(repo):
            raise Gate("HOLD", "PRIVATE_FILES_MUST_BE_OUTSIDE_REPOSITORY")
    if evidence.is_symlink():
        raise Gate("HOLD", "IDENTITY_SYMLINK_NOT_ALLOWED")
    return repo, local, evidence


def validate_evidence(path: Path, args) -> bool:
    if not path.is_file():
        return False
    data = parse_json(path.read_text(encoding="utf-8"), 32_768)
    expected = {"request_id": args.request_id, "product_type": "GAME",
                "slug": "signal-sprint", "source_sha": args.source_sha}
    if any(data.get(k) != v for k, v in expected.items()):
        raise Gate("CONFLICT", "LOCAL_IDENTITY_BINDING_MISMATCH")
    url = urlparse(str(data.get("official_evidence_url", "")))
    if (url.scheme != "https" or url.hostname not in
            {"partner.microsoft.com", "partnercenter.microsoft.com"}
            or url.username or url.password or url.fragment):
        raise Gate("HOLD", "AUTHENTICATED_PARTNER_CENTER_EVIDENCE_REQUIRED")
    for key in ("authenticated_account", "verified_at", "store_id", "name",
                "publisher", "version", "package_family_name", "package_sid"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise Gate("HOLD", "OFFICIAL_IDENTITY_FIELDS_MISSING")
    return True


def run(args) -> dict:
    ledger = read_ledger()
    product, _ = validate_ledger(ledger, args)
    if source_head() != args.source_sha:
        raise Gate("CONFLICT", "FACTORY_SOURCE_HEAD_CHANGED")
    repo, local, evidence = check_local_paths(args)
    if not validate_evidence(evidence, args):
        return {"status": "HOLD", "reason": "OFFICIAL_IDENTITY_NOT_AVAILABLE",
                "request_id": args.request_id, "source_sha": args.source_sha,
                "e2e_pass": False}
    if not args.apply:
        return {"status": "READY_FOR_LOCAL_CAS_APPROVAL",
                "request_id": args.request_id, "source_sha": args.source_sha,
                "e2e_pass": False}
    if args.confirm_request_id != args.request_id:
        raise Gate("HOLD", "EXPLICIT_REQUEST_APPROVAL_REQUIRED")
    # Recheck immediately before the only allowed remote mutation.
    if source_head() != args.source_sha:
        raise Gate("CONFLICT", "FACTORY_SOURCE_HEAD_CHANGED")
    local.mkdir(parents=True, exist_ok=True)
    job_path, result_path = local / "live-job.json", local / "provisioner-result.json"
    job = product.get("local_job_live")
    if not isinstance(job, dict) or any(job.get(k) != v for k, v in {
        "request_id": args.request_id, "source_sha": args.source_sha,
        "source_branch": args.source_branch, "product_type": "GAME",
        "source_repository": FACTORY, "slug": "signal-sprint", "dry_run": False}.items()):
        raise Gate("CONFLICT", "LIVE_JOB_MISMATCH")
    job_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    base_command = [sys.executable, str(repo / "provisioner.py"),
               "--input", str(job_path), "--output", str(result_path),
               "--official-identity", str(evidence),
               "--state-dir", str(local / "state"), "--work-dir", str(local / "work")]

    def invoke(apply: bool) -> dict:
        # No stdout/stderr or raw evidence is ever copied into the receipt.
        try:
            proc = subprocess.run(base_command + (["--apply"] if apply else []),
                                  cwd=repo, capture_output=True, text=True,
                                  encoding="utf-8", timeout=2400, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Gate("RETRYABLE_FAILURE", "LOCAL_PROVISIONER_UNAVAILABLE") from exc
        if not result_path.is_file():
            raise Gate("RETRYABLE_FAILURE", "PROVISIONER_RESULT_MISSING")
        result = parse_json(result_path.read_text(encoding="utf-8"), 200_000)
        if any(result.get(k) != v for k, v in {
            "request_id": args.request_id, "product_type": "GAME",
            "source_sha": args.source_sha, "source_repository": FACTORY,
            "source_branch": args.source_branch, "slug": "signal-sprint"}.items()):
            raise Gate("CONFLICT", "PROVISIONER_RESULT_BINDING_MISMATCH")
        if proc.returncode not in (0, 2):
            raise Gate("HOLD", "PROVISIONER_PROCESS_FAILED")
        return result

    # Preflight builds and inspects the real EXE BEFORE any CAS mutation.
    # A changed EXE cannot be approved using the previously inspected bytes.
    original = (product.get("local_execution_result") or {}).get("package_sha256")
    if not isinstance(original, str) or not SHA256.fullmatch(original):
        raise Gate("HOLD", "PINNED_LOCAL_EXE_SHA_MISSING")
    preflight = invoke(False)
    prepackage = preflight.get("package") or {}
    if prepackage.get("kind") != "exe" or prepackage.get("sha256") != original:
        raise Gate("CONFLICT", "LOCAL_EXE_PROVENANCE_CHANGED")
    if ((preflight.get("github_return") or {}).get("status") != "NOT_APPLIED"
            or preflight.get("status") != "HOLD"
            or preflight.get("next_stage") != "APPLY_VERIFIED_GITHUB_RETURN"):
        raise Gate("HOLD", "PRECAS_PREFLIGHT_NOT_READY")
    if source_head() != args.source_sha:
        raise Gate("CONFLICT", "FACTORY_SOURCE_HEAD_CHANGED")

    result = invoke(True)
    returned = result.get("github_return") or {}
    commit = returned.get("commit_sha")
    if (returned.get("status") != "APPLIED" or not isinstance(commit, str)
            or not SHA.fullmatch(commit) or result.get("status") != "HOLD"
            or result.get("next_stage") != "GITHUB_REBUILD_MSIX"):
        raise Gate("HOLD", "PROVISIONER_CAS_NOT_CONFIRMED")
    package = result.get("package") or {}
    if (package.get("kind") != "exe" or package.get("sha256") != original):
        raise Gate("CONFLICT", "LOCAL_EXE_CHANGED_DURING_CAS")
    if source_head() != commit:
        raise Gate("RETRYABLE_FAILURE", "CAS_COMMIT_NOT_VISIBLE_RECONCILE")
    receipt = {"status": "CAS_RETURNED_MSIX_PENDING", "e2e_pass": False,
               "request_id": args.request_id, "product_type": "GAME",
               "source_factory": "AI-Game-Factory", "source_sha": args.source_sha,
               "source_branch": args.source_branch, "slug": "signal-sprint",
               "factory_return_commit_sha": commit, "package_sha256": package["sha256"],
               "signature_status": package.get("signature_status"),
               "next_action": "Create separate codex/* Factory MSIX integration branch; do not move source_sha"}
    receipt_path = local / "identity-return-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main(argv=None):
    p = argparse.ArgumentParser(description="Local-only, explicit approval for Signal Sprint Identity CAS")
    p.add_argument("--provisioner-root", type=Path, required=True)
    p.add_argument("--provisioner-branch", required=True)
    p.add_argument("--provisioner-sha", required=True)
    p.add_argument("--local-dir", type=Path, required=True)
    p.add_argument("--official-identity", type=Path, required=True)
    p.add_argument("--source-branch", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--request-id", required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--confirm-request-id", default="")
    args = p.parse_args(argv)
    if os.name != "nt":
        print(json.dumps({"status": "HOLD", "reason": "LOCAL_WINDOWS_REQUIRED", "e2e_pass": False}))
        return 2
    try:
        result = run(args)
    except Gate as exc:
        result = {"status": exc.status, "reason": exc.reason, "e2e_pass": False}
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        result = {"status": "HOLD", "reason": "LOCAL_INPUT_OR_FILESYSTEM_ERROR",
                  "e2e_pass": False}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in {"READY_FOR_LOCAL_CAS_APPROVAL", "CAS_RETURNED_MSIX_PENDING"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
