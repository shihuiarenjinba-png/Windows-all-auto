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
import tempfile
from urllib.parse import quote, urlparse

REMOTE = "shihuiarenjinba-png/Windows-all-auto"
LEDGER_REF = "codex/e2e-belt-connection-20261027"
LEDGER_PATH = "ops/active_e2e_handoff.json"
FACTORY = "shihuiarenjinba-png/AI-Game-Factory"
PROVISIONER = "shihuiarenjinba-png/Repository-Provisioner-game"
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUEST = re.compile(r"^game-signal-sprint-[0-9a-f]{40}$")
STAGES = {
    "DISCOVER_JOB", "VERIFY_FACTORY_HEAD", "VERIFY_LOCAL_PACKAGE",
    "WAITING_OFFICIAL_IDENTITY", "IDENTITY_READY", "CAS_RETURN",
    "CAS_RETURNED", "WAITING_FACTORY_MSIX", "DONE", "HOLD", "CONFLICT",
}
SENSITIVE_EVIDENCE_KEYS = re.compile(
    r"(?:token|cookie|session|password|secret|mfa|private.?key|pfx|authorization)", re.I
)


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


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix="." + path.name + ".", suffix=".tmp",
                                     delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def state_binding(args) -> dict:
    return {
        "request_id": args.request_id, "product_type": "GAME",
        "source_factory": "AI-Game-Factory", "source_repository": FACTORY,
        "source_branch": args.source_branch, "source_sha": args.source_sha,
        "slug": "signal-sprint", "provisioner_branch": args.provisioner_branch,
        "provisioner_sha": args.provisioner_sha,
        "ledger_ref": getattr(args, "ledger_ref", LEDGER_REF),
        "ledger_sha": getattr(args, "ledger_sha", "") or "",
    }


def read_state(local: Path, args) -> dict | None:
    path = local / "worker-state.json"
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise Gate("HOLD", "LOCAL_STATE_UNSAFE")
    state = parse_json(path.read_text(encoding="utf-8"), 64_000)
    if state.get("stage") not in STAGES:
        raise Gate("HOLD", "LOCAL_STATE_STAGE_INVALID")
    binding = state_binding(args)
    mutable_control_pins = {"provisioner_branch", "provisioner_sha", "ledger_ref", "ledger_sha"}
    immutable = {key: value for key, value in binding.items()
                 if key not in mutable_control_pins}
    if any(state.get(key) != value for key, value in immutable.items()):
        raise Gate("CONFLICT", "LOCAL_STATE_BINDING_MISMATCH")
    provisioner_changed = any(state.get(key, "") != binding[key]
                              for key in mutable_control_pins)
    if provisioner_changed:
        if state.get("stage") in {"CAS_RETURN", "CAS_RETURNED", "WAITING_FACTORY_MSIX", "DONE"}:
            raise Gate("CONFLICT", "LOCAL_STATE_PROVISIONER_CHANGED_AFTER_CAS_START")
        state["_provisioner_changed"] = True
    return state


def checkpoint(local: Path, args, stage: str, **fields) -> dict:
    if stage not in STAGES:
        raise ValueError("invalid worker stage")
    state = {"schema_version": 1, **state_binding(args), "stage": stage,
             "e2e_pass": False, **fields}
    atomic_json(local / "worker-state.json", state)
    return state


def hold_class(reason: str, status: str) -> str:
    if status == "CONFLICT" or "CONFLICT" in reason or "CHANGED" in reason or "MISMATCH" in reason:
        return "CONFLICT"
    if "IDENTITY" in reason:
        return "EXTERNAL_IDENTITY"
    if "APPROVAL" in reason:
        return "HUMAN_APPROVAL"
    if "GITHUB" in reason or "UNAVAILABLE" in reason:
        return "CI_INFRA"
    if "PROVISIONER" in reason:
        return "INTEGRATION_FIX"
    return "CODE_FIX"


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


def read_ledger(args=None) -> dict:
    ref = getattr(args, "ledger_ref", LEDGER_REF) if args is not None else LEDGER_REF
    pinned_sha = (getattr(args, "ledger_sha", "") or "") if args is not None else ""
    if (not isinstance(ref, str) or not ref.startswith("codex/")
            or not re.fullmatch(r"codex/[A-Za-z0-9._/-]+", ref)):
        raise Gate("HOLD", "LEDGER_REF_NOT_ALLOWED")
    if ref != LEDGER_REF and not pinned_sha:
        raise Gate("HOLD", "NONDEFAULT_LEDGER_REQUIRES_IMMUTABLE_SHA")
    if pinned_sha:
        if not SHA.fullmatch(pinned_sha):
            raise Gate("HOLD", "LEDGER_SHA_INVALID")
        observed = gh_api("repos/" + REMOTE + "/git/ref/heads/" + quote(ref, safe=""))
        if observed.get("object", {}).get("sha") != pinned_sha:
            raise Gate("CONFLICT", "LEDGER_HEAD_CHANGED")
        content_ref = pinned_sha
    else:
        content_ref = ref
    endpoint = "repos/" + REMOTE + "/contents/" + LEDGER_PATH + "?ref=" + quote(content_ref, safe="")
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
    if evidence != local / "official-identity.json":
        raise Gate("HOLD", "IDENTITY_MUST_USE_DEDICATED_LOCAL_SECURE_PATH")
    for path in (local, evidence):
        if path == repo or path.is_relative_to(repo):
            raise Gate("HOLD", "PRIVATE_FILES_MUST_BE_OUTSIDE_REPOSITORY")
        # Private evidence, Provisioner results and receipts must not land
        # inside ANY checkout where a later git add could expose them.
        if any((parent / ".git").exists() for parent in (path, *path.parents)):
            raise Gate("HOLD", "PRIVATE_FILES_MUST_BE_OUTSIDE_GIT_CHECKOUT")
    if evidence.is_symlink():
        raise Gate("HOLD", "IDENTITY_SYMLINK_NOT_ALLOWED")
    return repo, local, evidence


def validate_evidence(path: Path, args) -> bool:
    if not path.is_file():
        return False
    data = parse_json(path.read_text(encoding="utf-8"), 32_768)
    def reject_sensitive_keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if SENSITIVE_EVIDENCE_KEYS.search(str(key)):
                    raise Gate("HOLD", "SECRET_MATERIAL_NOT_ALLOWED_IN_IDENTITY_EVIDENCE")
                reject_sensitive_keys(child)
        elif isinstance(value, list):
            for child in value:
                reject_sensitive_keys(child)
    reject_sensitive_keys(data)
    expected = {"request_id": args.request_id, "product_type": "GAME",
                "slug": "signal-sprint", "source_sha": args.source_sha}
    if any(data.get(k) != v for k, v in expected.items()):
        raise Gate("CONFLICT", "LOCAL_IDENTITY_BINDING_MISMATCH")

    gdk_required = {
        "request_id", "product_type", "slug", "source_sha",
        "identity_source", "provided_at", "store_id", "name", "publisher",
        "publisher_display_name", "package_family_name", "package_sid",
        "packaging_family", "xbox_title_id", "xbox_scid", "msa_app_id",
    }
    if set(data) == gdk_required:
        if (data.get("identity_source") != "USER_PROVIDED_PARTNER_CENTER"
                or data.get("packaging_family") != "GDK"):
            raise Gate("CONFLICT", "USER_PROVIDED_GDK_IDENTITY_SOURCE_MISMATCH")
        for key in gdk_required - {"request_id", "product_type", "slug", "source_sha"}:
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise Gate("HOLD", "OFFICIAL_IDENTITY_FIELDS_MISSING")
        return True

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


def _run_checked(args, product: dict, repo: Path, local: Path, evidence: Path) -> dict:
    local.mkdir(parents=True, exist_ok=True)
    previous = read_state(local, args)
    if previous and previous.get("stage") in {"CAS_RETURNED", "WAITING_FACTORY_MSIX", "DONE"}:
        receipt_path = local / "identity-return-receipt.json"
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise Gate("HOLD", "CAS_RECEIPT_MISSING_RECONCILE")
        receipt = parse_json(receipt_path.read_text(encoding="utf-8"), 64_000)
        commit = receipt.get("factory_return_commit_sha")
        if (any(receipt.get(key) != value for key, value in state_binding(args).items()
                if key not in {"provisioner_branch", "provisioner_sha", "ledger_ref", "ledger_sha"})
                or not isinstance(commit, str) or not SHA.fullmatch(commit)):
            raise Gate("CONFLICT", "CAS_RECEIPT_BINDING_MISMATCH")
        if source_head() != commit:
            raise Gate("CONFLICT", "FACTORY_HEAD_CHANGED_AFTER_CAS")
        return receipt

    if product.get("factory_return_commit_sha") or product.get("approved_identity_json"):
        raise Gate("HOLD", "IDENTITY_ALREADY_RECORDED_RECONCILE")

    recovering_cas = bool(previous and previous.get("stage") == "CAS_RETURN")
    if (previous and not previous.get("_provisioner_changed")
            and previous.get("stage") == "WAITING_OFFICIAL_IDENTITY" and not evidence.exists()):
        expected_package = (product.get("local_execution_result") or {}).get("package_sha256")
        if previous.get("package_sha256") != expected_package:
            raise Gate("CONFLICT", "LOCAL_STATE_PACKAGE_MISMATCH")
        prior_path = getattr(args, "provisioner_result", None)
        if prior_path is not None:
            prior_path = Path(prior_path).resolve()
            if prior_path.is_symlink() or not prior_path.is_file() or prior_path.stat().st_size > 262_144:
                raise Gate("HOLD", "PRIOR_PROVISIONER_RESULT_MISSING_OR_UNSAFE")
        if source_head() != args.source_sha:
            raise Gate("CONFLICT", "FACTORY_SOURCE_HEAD_CHANGED")
        return {"status": "HOLD", "state": "WAITING_OFFICIAL_IDENTITY",
                "reason": "OFFICIAL_IDENTITY_NOT_AVAILABLE", "hold_class": "EXTERNAL_IDENTITY",
                "blocked_by": "AUTHENTICATED_PARTNER_CENTER_IDENTITY",
                "request_id": args.request_id, "source_sha": args.source_sha,
                "package_sha256": previous.get("package_sha256"), "e2e_pass": False}

    if not recovering_cas:
        checkpoint(local, args, "DISCOVER_JOB")
    initial_head = source_head()
    if initial_head != args.source_sha and not recovering_cas:
        raise Gate("CONFLICT", "FACTORY_SOURCE_HEAD_CHANGED")
    if not recovering_cas:
        checkpoint(local, args, "VERIFY_FACTORY_HEAD", factory_head_sha=initial_head)
    job_path, result_path = local / "live-job.json", local / "provisioner-result.json"
    resume_result = getattr(args, "provisioner_result", None)
    if resume_result is not None:
        resume_result = Path(resume_result).resolve()
        if (resume_result.is_symlink() or not resume_result.is_file()
                or resume_result.stat().st_size > 262_144):
            raise Gate("HOLD", "PRIOR_PROVISIONER_RESULT_MISSING_OR_UNSAFE")
    work_dir = getattr(args, "work_dir", None)
    custom_work_dir = work_dir is not None
    if not custom_work_dir:
        if local.parent.name.lower() == "secure" and local.parent.parent.name == "FactoryIdentityWorker":
            work_dir = local.parent.parent / "work" / args.source_sha[:12]
        else:
            work_dir = local / "work"
    work_dir = Path(work_dir).resolve()
    if (work_dir.is_symlink()
            or (custom_work_dir and (work_dir == repo or work_dir.is_relative_to(repo)))
            or (custom_work_dir and any((parent / ".git").exists()
                                        for parent in (work_dir, *work_dir.parents)))):
        raise Gate("HOLD", "PRIVATE_FILES_MUST_BE_OUTSIDE_GIT_CHECKOUT")
    (local / "state").mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    job = product.get("local_job_live")
    if not isinstance(job, dict) or any(job.get(k) != v for k, v in {
        "request_id": args.request_id, "source_sha": args.source_sha,
        "source_branch": args.source_branch, "product_type": "GAME",
        "source_repository": FACTORY, "slug": "signal-sprint", "dry_run": False}.items()):
        raise Gate("CONFLICT", "LIVE_JOB_MISMATCH")
    atomic_json(job_path, job)
    base_command = [sys.executable, str(repo / "provisioner.py"),
               "--input", str(job_path), "--output", str(result_path),
               "--state-dir", str(local / "state"), "--work-dir", str(work_dir)]
    if resume_result is not None:
        base_command += ["--resume-result", str(resume_result)]

    def invoke(apply: bool, include_identity: bool) -> dict:
        # No stdout/stderr or raw evidence is ever copied into the receipt.
        if result_path.exists():
            result_path.unlink()
        command = list(base_command)
        if include_identity:
            command += ["--official-identity", str(evidence)]
        if apply:
            command.append("--apply")
        try:
            proc = subprocess.run(command,
                                  cwd=repo, capture_output=True, text=True,
                                  encoding="utf-8", timeout=2400, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Gate("RETRYABLE_FAILURE", "LOCAL_PROVISIONER_UNAVAILABLE") from exc
        if not result_path.is_file():
            raise Gate("RETRYABLE_FAILURE", "PROVISIONER_RESULT_MISSING")
        result = parse_json(result_path.read_text(encoding="utf-8"), 200_000)
        if result.get("status") == "FAILED" and result.get("request_id") is None:
            raise Gate("HOLD", "PROVISIONER_STARTUP_FAILED")
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
    original_result = product.get("local_execution_result") or {}
    original = original_result.get("package_sha256")
    original_bytes = original_result.get("package_bytes")
    original_signature = original_result.get("signature_status")
    if (not isinstance(original, str) or not SHA256.fullmatch(original)
            or type(original_bytes) is not int or original_bytes <= 0
            or not isinstance(original_signature, str) or not original_signature):
        raise Gate("HOLD", "PINNED_LOCAL_EXE_SHA_MISSING")
    has_evidence = validate_evidence(evidence, args)
    if args.apply and has_evidence and args.confirm_request_id != args.request_id:
        raise Gate("HOLD", "EXPLICIT_REQUEST_APPROVAL_REQUIRED")
    preflight = invoke(False, has_evidence)
    expected_stage = ("APPLY_VERIFIED_GITHUB_RETURN" if has_evidence else
                      "OBTAIN_AUTHENTICATED_OFFICIAL_IDENTITY")
    if preflight.get("status") != "HOLD" or preflight.get("next_stage") != expected_stage:
        raise Gate("HOLD", "PROVISIONER_PREFLIGHT_HOLD")
    prepackage = preflight.get("package") or {}
    if (prepackage.get("kind") != "exe" or prepackage.get("sha256") != original
            or prepackage.get("size_bytes") != original_bytes
            or prepackage.get("signature_status") != original_signature):
        raise Gate("CONFLICT", "LOCAL_EXE_PROVENANCE_CHANGED")
    if not recovering_cas:
        checkpoint(local, args, "VERIFY_LOCAL_PACKAGE", package_sha256=original,
                   package_bytes=original_bytes, signature_status=original_signature)
    if not has_evidence:
        checkpoint(local, args, "WAITING_OFFICIAL_IDENTITY", package_sha256=original,
                   package_bytes=original_bytes, signature_status=original_signature,
                   hold_class="EXTERNAL_IDENTITY",
                   blocked_by="AUTHENTICATED_PARTNER_CENTER_IDENTITY")
        return {"status": "HOLD", "state": "WAITING_OFFICIAL_IDENTITY",
                "reason": "OFFICIAL_IDENTITY_NOT_AVAILABLE", "hold_class": "EXTERNAL_IDENTITY",
                "blocked_by": "AUTHENTICATED_PARTNER_CENTER_IDENTITY",
                "request_id": args.request_id, "source_sha": args.source_sha,
                "package_sha256": original, "e2e_pass": False}
    if ((preflight.get("github_return") or {}).get("status") != "NOT_APPLIED"
            or preflight.get("next_stage") != "APPLY_VERIFIED_GITHUB_RETURN"):
        raise Gate("HOLD", "PRECAS_PREFLIGHT_NOT_READY")
    if not recovering_cas:
        checkpoint(local, args, "IDENTITY_READY", package_sha256=original,
                   official_identity_status="LOCAL_FORMAT_AND_BINDING_CHECKED_NOT_AUTHENTICITY_VERIFIED")
    if not args.apply:
        return {"status": "READY_FOR_LOCAL_CAS_APPROVAL", "state": "IDENTITY_READY",
                "official_identity_status": "LOCAL_FORMAT_AND_BINDING_CHECKED_NOT_AUTHENTICITY_VERIFIED",
                "request_id": args.request_id, "source_sha": args.source_sha,
                "package_sha256": original, "e2e_pass": False}
    observed_before_cas = source_head()
    if observed_before_cas != args.source_sha and not recovering_cas:
        raise Gate("CONFLICT", "FACTORY_SOURCE_HEAD_CHANGED")
    checkpoint(local, args, "CAS_RETURN", package_sha256=original,
               expected_head_sha=args.source_sha)

    try:
        result = invoke(True, True)
    except Gate as exc:
        if exc.reason not in {"LOCAL_PROVISIONER_UNAVAILABLE", "PROVISIONER_RESULT_MISSING"}:
            raise
        # The mutation may have succeeded even though the local process lost
        # its response.  Observe GitHub first; only then ask Provisioner to
        # reconcile its own existing immutable payload.  Never blindly retry.
        observed = source_head()
        if observed == args.source_sha:
            raise
        result = invoke(True, True)
    returned = result.get("github_return") or {}
    commit = returned.get("commit_sha")
    if (returned.get("status") not in {"APPLIED", "EXISTING_VERIFIED"} or not isinstance(commit, str)
            or not SHA.fullmatch(commit) or result.get("status") != "HOLD"
            or result.get("next_stage") != "GITHUB_REBUILD_MSIX"):
        raise Gate("HOLD", "PROVISIONER_CAS_NOT_CONFIRMED")
    package = result.get("package") or {}
    if (package.get("kind") != "exe" or package.get("sha256") != original):
        raise Gate("CONFLICT", "LOCAL_EXE_CHANGED_DURING_CAS")
    if source_head() != commit:
        raise Gate("RETRYABLE_FAILURE", "CAS_COMMIT_NOT_VISIBLE_RECONCILE")
    checkpoint(local, args, "CAS_RETURNED", factory_return_commit_sha=commit,
               package_sha256=package["sha256"])
    receipt = {"schema_version": 1, "status": "CAS_RETURNED_MSIX_PENDING",
               "state": "WAITING_FACTORY_MSIX", "e2e_pass": False,
               "request_id": args.request_id, "product_type": "GAME",
               "source_factory": "AI-Game-Factory", "source_repository": FACTORY,
               "source_sha": args.source_sha,
               "source_branch": args.source_branch, "slug": "signal-sprint",
               "ledger_ref": getattr(args, "ledger_ref", LEDGER_REF),
               "ledger_sha": getattr(args, "ledger_sha", "") or "",
               "provisioner_branch": args.provisioner_branch,
               "provisioner_sha": args.provisioner_sha,
               "factory_return_commit_sha": commit, "package_sha256": package["sha256"],
               "signature_status": package.get("signature_status"),
               "next_action": "Create separate codex/* Factory MSIX integration branch; do not move source_sha"}
    receipt_path = local / "identity-return-receipt.json"
    atomic_json(receipt_path, receipt)
    checkpoint(local, args, "WAITING_FACTORY_MSIX", factory_return_commit_sha=commit,
               package_sha256=package["sha256"])
    return receipt


def run(args) -> dict:
    ledger = read_ledger(args)
    product, _ = validate_ledger(ledger, args)
    repo, local, evidence = check_local_paths(args)
    try:
        return _run_checked(args, product, repo, local, evidence)
    except Gate as exc:
        if local.exists() and not local.is_symlink():
            current = read_state(local, args)
            stage = ("CAS_RETURN" if exc.status == "RETRYABLE_FAILURE" and current
                     and current.get("stage") == "CAS_RETURN" else
                     "CONFLICT" if exc.status == "CONFLICT" else "HOLD")
            checkpoint(local, args, stage,
                       reason=exc.reason, hold_class=hold_class(exc.reason, exc.status))
        raise


def main(argv=None):
    p = argparse.ArgumentParser(description="Local-only, explicit approval for Signal Sprint Identity CAS")
    p.add_argument("--provisioner-root", type=Path, required=True)
    p.add_argument("--provisioner-branch", required=True)
    p.add_argument("--provisioner-sha", required=True)
    p.add_argument("--local-dir", type=Path)
    p.add_argument("--official-identity", type=Path)
    p.add_argument("--work-dir", type=Path,
                   help="Optional short local build path; evidence/state remain in the secure request directory")
    p.add_argument("--provisioner-result", type=Path,
                   help="Prior pre-Identity Provisioner result for exact EXE resume/re-inspection")
    p.add_argument("--ledger-ref", default=LEDGER_REF,
                   help="GitHub codex/* branch containing the reviewed active handoff ledger")
    p.add_argument("--ledger-sha", default="",
                   help="Required immutable branch HEAD when --ledger-ref is not the integration ledger")
    p.add_argument("--source-branch", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--request-id", required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--confirm-request-id", default="")
    args = p.parse_args(argv)
    if os.name != "nt":
        print(json.dumps({"status": "HOLD", "reason": "LOCAL_WINDOWS_REQUIRED", "e2e_pass": False}))
        return 2
    if args.local_dir is None:
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            print(json.dumps({"status": "HOLD", "reason": "LOCALAPPDATA_REQUIRED", "e2e_pass": False}))
            return 2
        args.local_dir = Path(base) / "FactoryIdentityWorker" / "secure" / args.request_id
    if args.official_identity is None:
        args.official_identity = args.local_dir / "official-identity.json"
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
