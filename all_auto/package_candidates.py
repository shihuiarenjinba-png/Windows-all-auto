from __future__ import annotations

import hashlib
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

def load_candidate_installed_msix_qa_receipt(candidate: dict[str, Any], archive_root: Path) -> dict[str, Any]:
    """Validate functional, signature-derivative and install receipts for the exact provisional package."""
    root = archive_root.resolve()

    def read_receipt(path_key: str, sha_key: str) -> tuple[dict[str, Any], Path, str]:
        rel = Path(str(candidate.get(path_key, "")))
        if not rel.parts or rel.is_absolute() or ".." in rel.parts:
            raise StoreWorkflowError("candidate installed-MSIX QA receipt path is unsafe")
        path = (root / rel).resolve()
        if root not in path.parents or not path.is_file():
            raise StoreWorkflowError("candidate installed-MSIX QA receipt is missing")
        try:
            raw = path.read_bytes()
            obj = json.loads(raw.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StoreWorkflowError("candidate installed-MSIX QA receipt is unreadable") from exc
        digest = hashlib.sha256(raw).hexdigest()
        if candidate.get(sha_key) != digest:
            raise StoreWorkflowError("candidate installed-MSIX QA receipt hash differs from registry")
        return obj, path, digest

    functional, path, receipt_sha = read_receipt(
        "installed_msix_qa_receipt_relative_path", "installed_msix_qa_receipt_sha256")
    derivative, _, derivative_sha = read_receipt(
        "test_signature_derivative_receipt_relative_path", "test_signature_derivative_receipt_sha256")
    installed, _, install_sha = read_receipt(
        "test_signature_install_receipt_relative_path", "test_signature_install_receipt_sha256")
    expected_sha = str(candidate.get("sha256", "")).lower()
    expected_identity = {"Name": candidate.get("identity_name"), "Publisher": candidate.get("publisher"),
                         "Version": candidate.get("version"), "ProcessorArchitecture": candidate.get("architecture")}
    required = {
        "language_switch", "csv_compare_anomaly_detection", "xlsx_compare_anomaly_detection",
        "default_output_and_reopened_files", "invalid_csv_error", "normal_exit", "aumid_relaunch",
    }
    checks = functional.get("checks")
    status_by_id = {item.get("id"): item.get("status") for item in checks
                    if isinstance(item, dict) and isinstance(item.get("id"), str)} if isinstance(checks, list) else {}
    source_identity = derivative.get("source", {}).get("identity", {})
    derived_identity = derivative.get("derived", {}).get("identity", {})
    no_payload_changes = (derivative.get("changed_payload_members") == []
                          and set(derivative.get("added_members", [])) == {"AppxMetadata/CodeIntegrity.cat", "AppxSignature.p7x"})
    if (functional.get("schema_version") != "dca-installed-msix-gui-qa/1"
            or functional.get("product") != "Data Contract Auditor"
            or functional.get("execution_type") != "INSTALLED_TEST_SIGNED_MSIX_GUI"
            or str(functional.get("candidate_package_sha256", "")).lower() != expected_sha
            or functional.get("status") != "INSTALLED_PACKAGE_FUNCTIONAL_QA_PASS"
            or any(status_by_id.get(key) != "PASS" for key in required)
            or functional.get("store_write_performed") is not False
            or functional.get("certification_executed") is not False
            or functional.get("publish_executed") is not False
            or derivative.get("schema_version") != "all-auto-msix-test-signature-derivative/1"
            or derivative.get("status") != "SIGNATURE_ONLY_DERIVATIVE_VERIFIED"
            or derivative.get("diagnostic_only") is not True
            or str(derivative.get("source", {}).get("sha256", "")).lower() != expected_sha
            or source_identity != expected_identity or derived_identity != expected_identity
            or not no_payload_changes
            or str(derivative.get("derived", {}).get("sha256", "")).lower() == expected_sha
            or installed.get("schema_version") != "all-auto-msix-test-sign-install/2"
            or installed.get("status") != "TEST_SIGNED_DERIVATIVE_INSTALL_FUNCTIONAL_GUI_QA_PASS"
            or installed.get("diagnostic_only") is not True
            or installed.get("install") != "PASS" or installed.get("launch") != "PASS"
            or str(installed.get("source_sha256", "")).lower() != expected_sha
            or str(installed.get("derived_sha256", "")).lower() != str(derivative.get("derived", {}).get("sha256", "")).lower()
            or installed.get("identity") != candidate.get("identity_name")
            or installed.get("publisher") != candidate.get("publisher")
            or installed.get("version") != candidate.get("version")
            or installed.get("architecture") != candidate.get("architecture")):
        raise StoreWorkflowError("candidate installed-MSIX QA evidence does not match the exact candidate or required checks")
    screenshots = functional.get("screenshots")
    if not isinstance(screenshots, list) or not screenshots:
        raise StoreWorkflowError("candidate installed-MSIX QA screenshots are missing")
    screenshot_root = path.parent.resolve()
    for shot in screenshots:
        if not isinstance(shot, dict):
            raise StoreWorkflowError("candidate installed-MSIX QA screenshot record is invalid")
        shot_rel = Path(str(shot.get("artifact_path", "")).replace("\\", "/"))
        if not shot_rel.parts or shot_rel.is_absolute() or ".." in shot_rel.parts:
            raise StoreWorkflowError("candidate installed-MSIX screenshot path is unsafe")
        shot_path = (screenshot_root / shot_rel).resolve()
        if screenshot_root not in shot_path.parents or not shot_path.is_file():
            raise StoreWorkflowError("candidate installed-MSIX screenshot is missing")
        if hashlib.sha256(shot_path.read_bytes()).hexdigest() != str(shot.get("sha256", "")).lower():
            raise StoreWorkflowError("candidate installed-MSIX screenshot hash mismatch")
    return {
        "status": "INSTALLED_TEST_SIGNED_DERIVATIVE_QA_PASS_PROVISIONAL",
        "qa_pass": True,
        "evidence_type": "TEST_SIGNED_DERIVATIVE_GUI",
        "candidate_sha256": expected_sha,
        "test_signed_derived_sha256": str(derivative.get("derived", {}).get("sha256", "")).lower(),
        "receipt_sha256": receipt_sha,
        "signature_derivative_receipt_sha256": derivative_sha,
        "test_sign_install_receipt_sha256": install_sha,
        "receipt_path": str(path),
        "required_checks": sorted(required),
        "screenshot_count": len(screenshots),
        "runner_context": candidate.get("installed_msix_qa_runner_context", "UNRECORDED"),
        "formal_package_promoted": False,
        "store_write_performed": False,
    }
