from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .store_workflow import StoreWorkflowError, _load_job


def load_package_candidate(*, product: str, candidate_id: str, config_root: Path,
                           registry_root: Path, archive_root: Path) -> tuple[dict[str, Any], Path]:
    path = registry_root / f"{product}.json"
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreWorkflowError("package candidate registry is unavailable or invalid") from exc
    if (registry.get("schema_version") != "all-auto-package-candidates/1"
            or registry.get("product_key") != product):
        raise StoreWorkflowError("package candidate registry product/schema binding is invalid")
    matches = [item for item in registry.get("candidates", [])
               if isinstance(item, dict) and item.get("candidate_id") == candidate_id]
    if len(matches) != 1:
        raise StoreWorkflowError("candidate ID is absent or ambiguous")
    candidate = matches[0]
    config, _ = _load_job(product, config_root)
    if (candidate.get("product_id") != config.get("product_id")
            or candidate.get("submission_id") != config.get("submission_id")):
        raise StoreWorkflowError("candidate Product/Submission binding differs from the registered product")
    if candidate.get("candidate_status") != "PROVISIONAL_NOT_OWNER_APPROVED":
        raise StoreWorkflowError("candidate is not explicitly marked provisional")
    if any(candidate.get(key) is not False for key in
           ("owner_version_approval", "upload_approved", "certification_authorized", "publish_authorized")):
        raise StoreWorkflowError("candidate approval boundary must remain false")
    rel = Path(str(candidate.get("archive_relative_path", "")))
    if not rel.parts or rel.is_absolute() or ".." in rel.parts:
        raise StoreWorkflowError("candidate archive path is unsafe")
    package = (archive_root / rel).resolve()
    root = archive_root.resolve()
    if root not in package.parents or not package.is_file():
        raise StoreWorkflowError("exact candidate MSIX is not present in the local archive")
    return candidate, package


def runtime_package_binding(candidate: dict[str, Any]) -> dict[str, Any]:
    return {key: candidate[key] for key in (
        "filename", "sha256", "identity_name", "publisher", "version",
        "architecture", "application_id", "target_device_families")}


def load_candidate_source_gui_receipt(candidate: dict[str, Any], archive_root: Path) -> dict[str, Any]:
    rel = Path(str(candidate.get("source_gui_receipt_relative_path", "")))
    if not rel.parts or rel.is_absolute() or ".." in rel.parts:
        raise StoreWorkflowError("candidate source GUI receipt path is unsafe")
    path = (archive_root / rel).resolve()
    if archive_root.resolve() not in path.parents or not path.is_file():
        raise StoreWorkflowError("candidate source GUI receipt is missing")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreWorkflowError("candidate source GUI receipt is unreadable") from exc
    expected_checks = [
        "core_csv_drift", "csv_xlsx_compare", "invalid_input_rejected", "outputs_reopen",
        "inputs_unchanged", "writable_default_output", "default_output_files_written",
        "ui_language_and_scaling", "ui_compare_workflow", "ui_error_path", "close_relaunch",
    ]
    check_map = {item.get("name"): item.get("status") for item in receipt.get("checks", []) if isinstance(item, dict)}
    if (receipt.get("schema_version") != "data-contract-local-real-device-qa/1"
            or receipt.get("source_sha") != candidate.get("gui_qa_source_commit")
            or receipt.get("driver_sha256") != candidate.get("source_gui_driver_sha256")
            or receipt.get("execution_type") != "SOURCE_GUI_DRIVER_SYNTHETIC_DATA"
            or receipt.get("source_worktree_clean") is not True
            or receipt.get("status") != "PASS"
            or any(check_map.get(name) != "PASS" for name in expected_checks)):
        raise StoreWorkflowError("candidate source GUI receipt does not match the candidate source binding")
    return {"status": "SOURCE_GUI_DRIVER_PASS", "qa_pass": True,
            "receipt": receipt, "receipt_path": str(path),
            "binding": {"source_sha": receipt["source_sha"],
                        "source_worktree_clean": receipt["source_worktree_clean"],
                        "driver_sha256": receipt["driver_sha256"],
                        "repository_matches": True},
            "packaged_runtime_proven": False, "visual_dpi_proven": False}
