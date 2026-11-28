"""Single-command Store orchestration gated by persisted, section-scoped approvals."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Callable

from uploader.core import UploadError, verify_file
from uploader.live_gates import package_write_hold_reason
from .state_paths import product_state_dir
from .store_workflow import StoreWorkflowError, _load_job


ALLOWED_SECTIONS = frozenset(("properties", "store_listings", "pricing_availability",
                              "age_ratings", "submission_options", "packages"))
SECTION_DEPENDENCIES = {"store_listings": frozenset({"packages"})}
SECTION_SUCCESS_STATUSES = frozenset({"SAVED_AND_RECONCILED", "SUCCEEDED",
                                      "SUCCEEDED_RECONCILED", "DUPLICATE_CONFIRMED",
                                      "ALREADY_MATCHES"})
SECTION_RECEIPT_SUCCESS_STATUSES = SECTION_SUCCESS_STATUSES - {"DUPLICATE_CONFIRMED"}


def _valid_completion_receipt(config: dict[str, Any], section: str) -> bool:
    receipts = config.get("section_completion_receipts")
    receipt = receipts.get(section) if isinstance(receipts, dict) else None
    if not isinstance(receipt, dict):
        return False
    if (receipt.get("product_id") != config.get("product_id") or
            receipt.get("submission_id") != config.get("submission_id") or
            receipt.get("status") not in SECTION_RECEIPT_SUCCESS_STATUSES or
            not any(isinstance(receipt.get(key), str) and receipt[key].strip()
                    for key in ("saved_at_utc", "reconciled_at_utc", "observed_at_utc"))):
        return False
    if section == "packages" and receipt.get("package_sha256") != config.get("expected_sha256"):
        return False
    return True


def _approved_execution_order(sections: list[str]) -> list[str]:
    """Stable topological order, visiting only dependencies explicitly approved this run."""
    approved = set(sections)
    result: list[str] = []
    visited: set[str] = set()

    def visit(section: str) -> None:
        if section in visited:
            return
        visited.add(section)
        for dependency in SECTION_DEPENDENCIES.get(section, frozenset()):
            if dependency in approved:
                visit(dependency)
        result.append(section)

    for section in sections:
        visit(section)
    return result


def _run_approval(config: dict[str, Any]) -> tuple[bool, str]:
    policy = config.get("execution_policy")
    approval = policy.get("approval") if isinstance(policy, dict) else None
    if (not isinstance(policy, dict) or policy.get("status") != "OWNER_APPROVED" or
            policy.get("auto_execute_approved_sections") is not True):
        return False, "PERSISTED_AUTO_RUN_APPROVAL_MISSING"
    if not isinstance(approval, dict):
        return False, "AUTO_RUN_APPROVAL_RECORD_MISSING"
    if approval.get("product_id") != config.get("product_id") or approval.get("submission_id") != config.get("submission_id"):
        return False, "AUTO_RUN_APPROVAL_TARGET_MISMATCH"
    if any(not isinstance(approval.get(key), str) or not approval[key].strip()
           for key in ("approval_ref", "approved_by", "approved_at")):
        return False, "AUTO_RUN_APPROVAL_RECORD_INCOMPLETE"
    sections = policy.get("approved_sections")
    if not isinstance(sections, list) or not sections or len(set(sections)) != len(sections):
        return False, "AUTO_RUN_APPROVED_SECTION_LIST_INVALID"
    if any(section not in ALLOWED_SECTIONS for section in sections):
        return False, "AUTO_RUN_SECTION_NOT_ALLOWED"
    return True, "OWNER_APPROVED_PERSISTED_SCOPE"


def run_approved_sections(*, product: str, config_root: Path, package: Path | None,
                          ui_map_path: Path, cdp_endpoint: str | None = None,
                          section_runner: Callable[..., dict[str, Any]] | None = None,
                          package_runner: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run only sections individually listed in the product's persisted approval.

    With no complete profile approval this is a no-op plan. Certification and
    Publish have no representation in ALLOWED_SECTIONS and cannot be dispatched.
    """
    config, _ = _load_job(product, config_root)
    approved, reason = _run_approval(config)
    if not approved:
        unapproved_sections = sorted(ALLOWED_SECTIONS)
        return {"status": "PLAN_ONLY", "reason": reason,
                "approved_sections": [], "completed_sections": [],
                "pending_sections": unapproved_sections,
                "unapproved_sections": unapproved_sections,
                "not_executed_sections": unapproved_sections,
                "all_approved_sections_completed": False,
                "actions": [], "writes_performed": False,
                "certification_executed": False, "publish_executed": False}

    ui_map = json.loads(ui_map_path.read_text(encoding="utf-8"))
    configured_sections = config.get("approved_store_sections", {})
    actions: list[dict[str, Any]] = []
    writes = False
    section_runner = section_runner or _run_non_package_section
    package_runner = package_runner or _run_package_section
    approved_sections = _approved_execution_order(config["execution_policy"]["approved_sections"])
    dependency_sections = set(SECTION_DEPENDENCIES)
    for values in SECTION_DEPENDENCIES.values():
        dependency_sections.update(values)
    completed = {section for section in dependency_sections
                 if _valid_completion_receipt(config, section)}
    completed_sections = sorted(completed)
    pending_sections: list[str] = []

    for section in approved_sections:
        dependencies = SECTION_DEPENDENCIES.get(section, frozenset())
        missing_dependencies = sorted(dependency for dependency in dependencies
                                      if dependency not in completed)
        if missing_dependencies:
            actions.append({"section": section, "status": "WAITING_DEPENDENCY",
                            "reason": "SECTION_DEPENDENCY_NOT_RECONCILED",
                            "dependencies": missing_dependencies})
            pending_sections.append(section)
            continue
        if section == "packages":
            result = _package_gate(config, package)
            if result["status"] != "READY":
                actions.append({"section": section, **result})
                pending_sections.append(section)
                continue
            try:
                outcome = package_runner(config=config, product=product, package=package)
            except Exception:
                actions.append({"section": section, "status": "RECONCILE_REQUIRED",
                                "reason": "PACKAGE_RUNNER_OUTCOME_UNKNOWN"})
                pending_sections.append(section)
                break
        else:
            entry = configured_sections.get(section) if isinstance(configured_sections, dict) else None
            if not isinstance(entry, dict) or not isinstance(entry.get("fields"), list) or not entry["fields"]:
                actions.append({"section": section, "status": "HOLD",
                                "reason": "APPROVED_SECTION_VALUES_MISSING"})
                pending_sections.append(section)
                continue
            descriptor = (ui_map.get("sections") or {}).get(section)
            if not isinstance(descriptor, dict) or descriptor.get("verified") is not True:
                actions.append({"section": section, "status": "HOLD",
                                "reason": "ACTION_TIME_VERIFIED_UI_MAP_REQUIRED"})
                pending_sections.append(section)
                continue
            try:
                outcome = section_runner(config=config, section=section, entry=entry,
                                         ui_map=ui_map, cdp_endpoint=cdp_endpoint)
            except Exception as exc:
                from uploader.store_form_engine import StoreUiHold
                if isinstance(exc, StoreUiHold) and not exc.write_started:
                    actions.append({"section": section, "status": "HOLD",
                                    "reason": "SECTION_RUNNER_HELD_BEFORE_WRITE"})
                    pending_sections.append(section)
                    continue
                actions.append({"section": section, "status": "RECONCILE_REQUIRED",
                                "reason": "SECTION_RUNNER_OUTCOME_UNKNOWN"})
                pending_sections.append(section)
                break
        if not isinstance(outcome, dict):
            actions.append({"section": section, "status": "RECONCILE_REQUIRED",
                            "reason": "ACTION_RESULT_INVALID"})
            pending_sections.append(section)
            break
        if section == "packages" and outcome.get("status") in SECTION_SUCCESS_STATUSES:
            observed_sha = outcome.get("sha256", outcome.get("package_sha256"))
            if (outcome.get("product_id") != config.get("product_id") or
                    outcome.get("submission_id") != config.get("submission_id") or
                    observed_sha != config.get("expected_sha256") or
                    (outcome.get("status") == "DUPLICATE_CONFIRMED" and
                     outcome.get("partner_center_reconfirmed") is not True)):
                actions.append({"section": section, "status": "RECONCILE_REQUIRED",
                                "reason": "PACKAGE_COMPLETION_BINDING_OR_SHA_MISMATCH"})
                pending_sections.append(section)
                break
        if outcome.get("status") == "ALREADY_MATCHES" and outcome.get("reload_reconciled") is not True:
            actions.append({"section": section, "status": "RECONCILE_REQUIRED",
                            "reason": "ALREADY_MATCHES_WITHOUT_RELOAD_RECONCILIATION"})
            pending_sections.append(section)
            break
        actions.append({"section": section, **outcome})
        status = outcome.get("status")
        writes = writes or outcome.get("writes_performed") is True
        if status in SECTION_SUCCESS_STATUSES:
            completed.add(section)
            if section not in completed_sections:
                completed_sections.append(section)
            continue
        pending_sections.append(section)
        if status in {"RECONCILE_REQUIRED", "FAILED", "UNKNOWN"}:
            break

    # A stop after an unknown write or package mismatch leaves every later
    # approved section explicitly pending; never report an incomplete chain as done.
    pending_sections = [section for section in approved_sections if section not in completed]
    blocked = bool(pending_sections) or any(
        action.get("status") in {"HOLD", "FAILED", "RECONCILE_REQUIRED", "WAITING_DEPENDENCY"}
        for action in actions)
    reconcile = any(x.get("status") == "RECONCILE_REQUIRED" for x in actions)
    all_approved_completed = not pending_sections and all(
        section in completed for section in approved_sections)
    status = ("RECONCILE_REQUIRED" if reconcile
            else "PARTIAL_RECONCILE_REQUIRED" if blocked and writes
            else "HOLD" if blocked else "EXECUTED" if all_approved_completed else "NO_APPROVED_ACTIONS")
    return {"status": status,
            "approval_ref": config["execution_policy"]["approval"]["approval_ref"],
            "approved_sections": approved_sections,
            "completed_sections": completed_sections,
            "pending_sections": pending_sections,
            "all_approved_sections_completed": all_approved_completed,
            "actions": actions, "writes_performed": writes,
            "certification_executed": False, "publish_executed": False}


def _package_gate(config: dict[str, Any], package: Path | None) -> dict[str, Any]:
    if not package:
        return {"status": "HOLD", "reason": "EXACT_PACKAGE_NOT_RESOLVED"}
    if package.is_symlink():
        return {"status": "HOLD", "reason": "PACKAGE_SYMLINK_NOT_ALLOWED"}
    hold = package_write_hold_reason(config, package)
    if hold:
        return {"status": "HOLD", "reason": hold}
    try:
        job = verify_file(config, package, expected_sha256=config.get("expected_sha256"),
                          max_bytes=int(config.get("max_bytes", 4_000_000_000)))
    except (OSError, UploadError) as exc:
        return {"status": "HOLD", "reason": getattr(exc, "code", type(exc).__name__)}
    return {"status": "READY", "file_name": job.file_name, "sha256": job.sha256}


def _run_non_package_section(*, config: dict[str, Any], section: str, entry: dict[str, Any],
                             ui_map: dict[str, Any], cdp_endpoint: str | None) -> dict[str, Any]:
    from uploader.store_form_engine import apply_live_section
    return apply_live_section(config=config, section=section,
                              fields=entry["fields"], approval=entry.get("approval"),
                              ui_map=ui_map, cdp_endpoint=cdp_endpoint)


def _run_package_section(*, config: dict[str, Any], product: str,
                         package: Path | None) -> dict[str, Any]:
    if package is None:
        return {"status": "HOLD", "reason": "EXACT_PACKAGE_NOT_RESOLVED"}
    from contextlib import redirect_stdout
    from io import StringIO
    from uploader.run import main as uploader_main

    old_argv = sys.argv[:]
    captured = StringIO()
    try:
        sys.argv = ["uploader.run", "--product", product, "--package", str(package),
                    "--workdir", str(product_state_dir(product)), "--execute"]
        with redirect_stdout(captured):
            code = uploader_main()
    finally:
        sys.argv = old_argv
    try:
        outcome = json.loads(captured.getvalue().strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"status": "RECONCILE_REQUIRED", "reason": "PACKAGE_UPLOADER_RESULT_UNREADABLE"}
    if code != 0 and outcome.get("status") not in {"RECONCILE_REQUIRED", "FAILED"}:
        return {"status": "RECONCILE_REQUIRED", "reason": "PACKAGE_UPLOADER_EXIT_RESULT_MISMATCH"}
    return {**outcome, "writes_performed": outcome.get("status") in {"SUCCEEDED", "SUCCEEDED_RECONCILED"}}
