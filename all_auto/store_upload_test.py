"""Bridge final-QA-passed GitHub artifacts into Windows-Automator upload tests.

This module is intentionally narrower than Store submission. It accepts only
candidates that already passed product E2E, evidence readback, Windows-checker,
official identity re-verification, owner security confirmation, and listing
asset readiness.

The bridge may drive Windows-Automator in:
- dry_run: no Partner Center writes;
- live: package upload + Save draft only, with action-time owner confirmation.

Certification submission and publication are never authorized here.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Callable

from all_auto.github_artifact_intake import (
    ArtifactIntakeHold, IntakeResult, fetch_actions_artifact,
)

SCHEMA = "store-upload-test-batch-v1"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
REQUEST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{3,127}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
STORE_ID = re.compile(r"^[A-Za-z0-9]{8,32}$")
AUTOMATOR_REPOSITORY = "shihuiarenjinba-png/Windows-Automator"
MAX_CANDIDATES = 20

BATCH_KEYS = {"schema_version", "automator", "candidates"}
AUTOMATOR_KEYS = {"repository", "branch", "commit_sha"}
CANDIDATE_KEYS = {
    "request_id", "product_type", "artifact_source", "identity",
    "readiness", "windows_automator_input",
}
ARTIFACT_KEYS = {
    "repository", "artifact_id", "artifact_name", "workflow_run_id",
    "source_sha", "archive_sha256", "package_name", "package_sha256",
    "executable_sha256",
}
IDENTITY_KEYS = {"store_id", "name", "publisher", "version"}
READINESS_KEYS = {
    "test_status", "evidence_return_e2e_pass", "product_e2e_pass",
    "checker_verdict", "official_identity_reverified",
    "security_owner_confirmed", "listing_assets_ready",
}
REQUIRED_READINESS = {
    "test_status": "TEST_PASS",
    "evidence_return_e2e_pass": True,
    "product_e2e_pass": True,
    "checker_verdict": "READY_CANDIDATE_NOT_CERTIFIED",
    "official_identity_reverified": True,
    "security_owner_confirmed": True,
    "listing_assets_ready": True,
}


class StoreUploadTestHold(ValueError):
    pass


def _hold(reason: str) -> None:
    raise StoreUploadTestHold("STORE_UPLOAD_TEST_HOLD: " + reason)


def _normalized_repo(value: str) -> str:
    value = value.strip()
    for prefix in ("https://github.com/", "git@github.com:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value.removesuffix(".git").strip("/")


def validate_batch(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != BATCH_KEYS:
        _hold("batch fields are invalid")
    if value.get("schema_version") != SCHEMA:
        _hold("batch schema mismatch")
    automator = value.get("automator")
    if not isinstance(automator, dict) or set(automator) != AUTOMATOR_KEYS:
        _hold("automator pin is invalid")
    if automator.get("repository") != AUTOMATOR_REPOSITORY:
        _hold("unexpected Windows-Automator repository")
    if not isinstance(automator.get("branch"), str) or not automator["branch"].startswith("codex/"):
        _hold("automator branch must be an explicit codex branch")
    if not isinstance(automator.get("commit_sha"), str) or not SHA40.fullmatch(
            automator["commit_sha"]):
        _hold("invalid automator commit SHA")

    candidates = value.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_CANDIDATES:
        _hold("candidate count must be between 1 and 20")

    seen_requests: set[str] = set()
    seen_store_ids: set[str] = set()
    safe_candidates: list[dict[str, Any]] = []

    for index, candidate in enumerate(candidates):
        prefix = f"candidate[{index}]"
        if not isinstance(candidate, dict) or set(candidate) != CANDIDATE_KEYS:
            _hold(prefix + " fields are invalid")
        request_id = candidate.get("request_id")
        if not isinstance(request_id, str) or not REQUEST.fullmatch(request_id):
            _hold(prefix + " request_id invalid")
        if request_id in seen_requests:
            _hold(prefix + " duplicate request_id")
        seen_requests.add(request_id)

        product_type = candidate.get("product_type")
        if product_type not in {"APP", "GAME"}:
            _hold(prefix + " product_type must be APP or GAME")

        source = candidate.get("artifact_source")
        if not isinstance(source, dict) or set(source) != ARTIFACT_KEYS:
            _hold(prefix + " artifact_source invalid")
        if not isinstance(source.get("repository"), str) or not REPOSITORY.fullmatch(
                source["repository"]):
            _hold(prefix + " artifact repository invalid")
        if type(source.get("artifact_id")) is not int or source["artifact_id"] <= 0:
            _hold(prefix + " artifact_id invalid")
        if type(source.get("workflow_run_id")) is not int or source["workflow_run_id"] <= 0:
            _hold(prefix + " workflow_run_id invalid")
        if not isinstance(source.get("artifact_name"), str) or not source["artifact_name"]:
            _hold(prefix + " artifact_name invalid")
        if not isinstance(source.get("package_name"), str) or not source["package_name"].lower().endswith(".msix"):
            _hold(prefix + " currently requires one exact .msix package")
        if not isinstance(source.get("source_sha"), str) or not SHA40.fullmatch(source["source_sha"]):
            _hold(prefix + " source_sha invalid")
        for field in ("archive_sha256", "package_sha256", "executable_sha256"):
            if not isinstance(source.get(field), str) or not SHA64.fullmatch(source[field]):
                _hold(prefix + " " + field + " invalid")

        identity = candidate.get("identity")
        if not isinstance(identity, dict) or set(identity) != IDENTITY_KEYS:
            _hold(prefix + " identity invalid")
        if not isinstance(identity.get("store_id"), str) or not STORE_ID.fullmatch(identity["store_id"]):
            _hold(prefix + " official Store ID missing")
        folded_store = identity["store_id"].casefold()
        if folded_store in seen_store_ids:
            _hold(prefix + " duplicate Store ID in batch")
        seen_store_ids.add(folded_store)
        if any(not isinstance(identity.get(k), str) or not identity[k].strip()
               for k in ("name", "publisher", "version")):
            _hold(prefix + " identity values incomplete")

        readiness = candidate.get("readiness")
        if not isinstance(readiness, dict) or set(readiness) != READINESS_KEYS:
            _hold(prefix + " readiness fields invalid")
        for key, expected in REQUIRED_READINESS.items():
            if readiness.get(key) != expected:
                _hold(prefix + " not READY_FOR_UPLOAD_TEST: " + key)

        product = candidate.get("windows_automator_input")
        if not isinstance(product, dict):
            _hold(prefix + " Windows-Automator input missing")
        expected_product_type = "app" if product_type == "APP" else "game"
        checks = {
            "product_type": expected_product_type,
            "store_product_id": identity["store_id"],
            "source_sha": source["source_sha"],
            "package_sha256": source["package_sha256"],
            "identity_name": identity["name"],
            "identity_publisher": identity["publisher"],
            "package_version": identity["version"],
            "checker_status": "READY_CANDIDATE_NOT_CERTIFIED",
            "human_local_qa_pass": True,
            "certification_gate": "READY_FOR_UPLOAD_TEST",
        }
        for key, expected in checks.items():
            if product.get(key) != expected:
                _hold(prefix + " Windows-Automator input mismatch: " + key)
        if product.get("package_path") not in (None, ""):
            _hold(prefix + " package_path must be injected locally, not trusted from GitHub")
        if product.get("security_package_sha256") != source["package_sha256"]:
            _hold(prefix + " security confirmation is not bound to exact package SHA")
        if product.get("source_branch") in (None, ""):
            _hold(prefix + " source_branch required")
        if product.get("submission_kind") not in {"new", "update"}:
            _hold(prefix + " submission_kind must be new or update")

        safe_candidates.append(candidate)

    return {
        "schema_version": SCHEMA,
        "automator": dict(automator),
        "candidates": safe_candidates,
    }


def verify_automator_checkout(
    checkout: Path, automator: dict[str, Any],
    *, runner: Callable[..., Any] = subprocess.run,
) -> None:
    root = checkout.resolve()
    if checkout.is_symlink() or not root.is_dir():
        _hold("Windows-Automator checkout missing or linked")
    if not (root / "store_manager" / "cli.py").is_file():
        _hold("Windows-Automator CLI missing")
    try:
        head = runner(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15, check=False,
        )
        remote = runner(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StoreUploadTestHold(
            "STORE_UPLOAD_TEST_HOLD: cannot verify Windows-Automator checkout"
        ) from exc
    if head.returncode or head.stdout.strip().lower() != automator["commit_sha"].lower():
        _hold("Windows-Automator HEAD does not match pinned commit")
    if remote.returncode or _normalized_repo(remote.stdout) != automator["repository"]:
        _hold("Windows-Automator origin does not match pinned repository")


@dataclass(frozen=True)
class PreparedQueue:
    queue: list[dict[str, Any]]
    intakes: tuple[IntakeResult, ...]


def prepare_queue(
    batch: dict[str, Any], workspace: Path,
    *, fetcher: Callable[..., IntakeResult] = fetch_actions_artifact,
) -> PreparedQueue:
    safe = validate_batch(batch)
    root = workspace.resolve()
    if workspace.is_symlink():
        _hold("workspace may not be a symlink")
    if root.exists() and any(root.iterdir()):
        _hold("workspace must be empty")
    root.mkdir(parents=True, exist_ok=True)

    queue: list[dict[str, Any]] = []
    intakes: list[IntakeResult] = []
    for index, candidate in enumerate(safe["candidates"]):
        source = candidate["artifact_source"]
        intake = fetcher(
            repository=source["repository"],
            artifact_id=source["artifact_id"],
            expected_name=source["artifact_name"],
            expected_run_id=source["workflow_run_id"],
            expected_head_sha=source["source_sha"],
            expected_archive_sha256=source["archive_sha256"],
            expected_package_name=source["package_name"],
            expected_package_sha256=source["package_sha256"],
            expected_executable_sha256=source["executable_sha256"],
            destination=root / ("candidate-" + str(index + 1)),
        )
        expected_identity = candidate["identity"]
        observed_identity = intake.metadata.get("identity") or {}
        for key, observed_key in (
            ("name", "name"), ("publisher", "publisher"), ("version", "version")
        ):
            if observed_identity.get(observed_key) != expected_identity[key]:
                _hold(f"candidate[{index}] package Identity mismatch: {key}")

        product = json.loads(json.dumps(candidate["windows_automator_input"]))
        product["package_path"] = str(intake.package_path.resolve())
        product["package_sha256"] = source["package_sha256"]
        product["source_sha"] = source["source_sha"]
        product["store_product_id"] = expected_identity["store_id"]
        product["identity_name"] = expected_identity["name"]
        product["identity_publisher"] = expected_identity["publisher"]
        product["package_version"] = expected_identity["version"]
        queue.append(product)
        intakes.append(intake)

    return PreparedQueue(queue=queue, intakes=tuple(intakes))


def classify_automator_report(report: Any, *, execution_mode: str) -> dict[str, Any]:
    if not isinstance(report, dict) or report.get("schema_version") != 2:
        _hold("Windows-Automator report schema invalid")
    summary = report.get("summary")
    results = report.get("results")
    if not isinstance(summary, dict) or not isinstance(results, list):
        _hold("Windows-Automator report incomplete")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"submitted", "certified", "published"} and item is True:
                    _hold("prohibited certification/publication action detected")
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(report)

    statuses = [item.get("status") for item in results if isinstance(item, dict)]
    if len(statuses) != len(results):
        _hold("Windows-Automator result item invalid")
    allowed = {"DONE", "DRAFT_SAVED", "HOLD", "UNKNOWN", "ERROR", "AUTH_ERROR"}
    if any(status not in allowed for status in statuses):
        _hold("Windows-Automator returned unknown status")

    counts = {name: statuses.count(name) for name in allowed}
    total = len(statuses)
    if execution_mode == "dry_run":
        status = (
            "UPLOAD_TEST_DRY_RUN_PASS"
            if total and counts["DONE"] == total
            else "UPLOAD_TEST_DRY_RUN_HOLD"
        )
    elif execution_mode == "live":
        if counts["UNKNOWN"]:
            status = "UPLOAD_TEST_UNKNOWN_HOLD"
        elif total and counts["DRAFT_SAVED"] == total:
            status = "UPLOAD_TEST_DRAFT_SAVED"
        else:
            status = "UPLOAD_TEST_LIVE_HOLD"
    else:
        _hold("execution mode invalid")

    return {
        "status": status,
        "total": total,
        "dry_run_done": counts["DONE"],
        "draft_saved": counts["DRAFT_SAVED"],
        "hold": counts["HOLD"],
        "unknown": counts["UNKNOWN"],
        "error": counts["ERROR"] + counts["AUTH_ERROR"],
        "results": results,
        "store_submission_allowed": False,
        "certification_allowed": False,
        "publish_allowed": False,
        "automatic_retry_unknown": False,
    }
