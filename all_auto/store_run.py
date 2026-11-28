"""Single-command Store orchestration gated by persisted, section-scoped approvals."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Callable

from uploader.core import UploadError, read_msix_manifest_metadata, verify_file
from uploader.device_families import device_family_plan
from .store_workflow import StoreWorkflowError, _load_job


ALLOWED_SECTIONS = frozenset(("properties", "store_listings", "pricing_availability",
                              "age_ratings", "submission_options", "packages"))


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
        return {"status": "PLAN_ONLY", "reason": reason,
                "actions": [], "writes_performed": False,
                "certification_executed": False, "publish_executed": False}

    ui_map = json.loads(ui_map_path.read_text(encoding="utf-8"))
    configured_sections = config.get("approved_store_sections", {})
    actions: list[dict[str, Any]] = []
    writes = False
    section_runner = section_runner or _run_non_package_section
    package_runner = package_runner or _run_package_section

    for section in config["execution_policy"]["approved_sections"]:
        if section == "packages":
            result = _package_gate(config, package)
            if result["status"] != "READY":
                actions.append({"section": section, **result})
                break
            outcome = package_runner(config=config, product=product, package=package)
        else:
            entry = configured_sections.get(section) if isinstance(configured_sections, dict) else None
            if not isinstance(entry, dict) or not isinstance(entry.get("fields"), list) or not entry["fields"]:
                actions.append({"section": section, "status": "HOLD",
                                "reason": "APPROVED_SECTION_VALUES_MISSING"})
                break
            descriptor = (ui_map.get("sections") or {}).get(section)
            if not isinstance(descriptor, dict) or descriptor.get("verified") is not True:
                actions.append({"section": section, "status": "HOLD",
                                "reason": "ACTION_TIME_VERIFIED_UI_MAP_REQUIRED"})
                break
            outcome = section_runner(config=config, section=section, entry=entry,
                                     ui_map=ui_map, cdp_endpoint=cdp_endpoint)
        if not isinstance(outcome, dict):
            actions.append({"section": section, "status": "RECONCILE_REQUIRED",
                            "reason": "ACTION_RESULT_INVALID"})
            break
        actions.append({"section": section, **outcome})
        writes = writes or outcome.get("writes_performed") is True or outcome.get("status") in {"SUCCEEDED", "SUCCEEDED_RECONCILED"}
        if outcome.get("status") not in {"SAVED_AND_RECONCILED", "SUCCEEDED", "SUCCEEDED_RECONCILED"}:
            break

    blocked = any(action.get("status") in {"HOLD", "FAILED", "RECONCILE_REQUIRED"} for action in actions)
    reconcile = any(x.get("status") == "RECONCILE_REQUIRED" for x in actions)
    return {"status": "RECONCILE_REQUIRED" if reconcile
            else "PARTIAL_RECONCILE_REQUIRED" if blocked and writes
            else "HOLD" if blocked else "EXECUTED" if writes else "NO_APPROVED_ACTIONS",
            "approval_ref": config["execution_policy"]["approval"]["approval_ref"],
            "actions": actions, "writes_performed": writes,
            "certification_executed": False, "publish_executed": False}


def _package_gate(config: dict[str, Any], package: Path | None) -> dict[str, Any]:
    if config.get("upload_approved") is not True or config.get("upload_scope") != "ONE_EXACT_MSIX_TO_EXISTING_DRAFT_PACKAGES_ONLY":
        return {"status": "HOLD", "reason": "PACKAGE_UPLOAD_APPROVAL_MISSING"}
    if config.get("certification_submission_authorized") is not False or config.get("publish_authorized") is not False:
        return {"status": "HOLD", "reason": "PROHIBITED_ACTION_GUARD_INVALID"}
    if not package:
        return {"status": "HOLD", "reason": "EXACT_PACKAGE_NOT_RESOLVED"}
    if package.is_symlink():
        return {"status": "HOLD", "reason": "PACKAGE_SYMLINK_NOT_ALLOWED"}
    if package.name.casefold() != Path(str(config.get("path", ""))).name.casefold():
        return {"status": "HOLD", "reason": "PACKAGE_FILENAME_MISMATCH"}
    if config.get("local_runtime_qa_status") != "WINDOWS_REAL_DEVICE_QA_PASS_EXACT_PACKAGE":
        return {"status": "HOLD", "reason": "EXACT_PACKAGE_RUNTIME_QA_REQUIRED"}
    settings = config.get("device_family_settings")
    if not isinstance(settings, dict) or settings.get("status") != "OWNER_APPROVED":
        return {"status": "HOLD", "reason": "DEVICE_FAMILY_OWNER_APPROVAL_REQUIRED"}
    approval = settings.get("approval")
    if (not isinstance(approval, dict) or approval.get("product_id") != config.get("product_id")
            or approval.get("submission_id") != config.get("submission_id")):
        return {"status": "HOLD", "reason": "DEVICE_FAMILY_APPROVAL_TARGET_MISMATCH"}
    try:
        job = verify_file(config, package, expected_sha256=config.get("expected_sha256"),
                          max_bytes=int(config.get("max_bytes", 4_000_000_000)))
    except (OSError, UploadError) as exc:
        return {"status": "HOLD", "reason": getattr(exc, "code", type(exc).__name__)}
    family = device_family_plan(config, read_msix_manifest_metadata(package)["target_device_families"])
    if family.get("status") != "OWNER_APPROVED":
        return {"status": "HOLD", "reason": "DEVICE_FAMILY_APPROVAL_INVALID"}
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
                    "--workdir", str(Path(".uploader-run") / product), "--execute"]
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
