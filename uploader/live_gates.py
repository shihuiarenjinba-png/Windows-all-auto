"""Shared fail-closed authorization gates for live Partner Center writes."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uploader.device_families import device_family_plan
from uploader.core import UploadError, read_msix_manifest_metadata, verify_file


def package_write_hold_reason(config: dict[str, Any], package: Path | None = None) -> str | None:
    """Return a stable hold code unless the exact package has all live approvals.

    This is intentionally shared by store orchestration and the legacy uploader
    so a direct CLI invocation cannot bypass the newer run-level QA gate.
    """
    if config.get("upload_approved") is not True:
        return "UPLOAD_NOT_APPROVED"
    if config.get("upload_scope") != "ONE_EXACT_MSIX_TO_EXISTING_DRAFT_PACKAGES_ONLY":
        return "UPLOAD_SCOPE_NOT_APPROVED"
    if config.get("certification_submission_authorized") is not False:
        return "CERTIFICATION_SCOPE_FORBIDDEN"
    if config.get("publish_authorized") is not False:
        return "PUBLISH_SCOPE_FORBIDDEN"

    policy = config.get("execution_policy")
    approval = policy.get("approval") if isinstance(policy, dict) else None
    if (not isinstance(policy, dict) or policy.get("status") != "OWNER_APPROVED"
            or policy.get("auto_execute_approved_sections") is not True
            or not isinstance(policy.get("approved_sections"), list)
            or "packages" not in policy["approved_sections"]):
        return "PERSISTED_PACKAGE_EXECUTION_APPROVAL_REQUIRED"
    if (not isinstance(approval, dict)
            or approval.get("product_id") != config.get("product_id")
            or approval.get("submission_id") != config.get("submission_id")
            or any(not isinstance(approval.get(k), str) or not approval[k].strip()
                   for k in ("approval_ref", "approved_by", "approved_at"))):
        return "PACKAGE_EXECUTION_APPROVAL_TARGET_MISMATCH"

    if config.get("local_runtime_qa_status") != "WINDOWS_REAL_DEVICE_QA_PASS_EXACT_PACKAGE":
        return "EXACT_PACKAGE_RUNTIME_QA_REQUIRED"
    qa = config.get("runtime_qa_receipt")
    if (not isinstance(qa, dict) or qa.get("status") != "WINDOWS_REAL_DEVICE_QA_PASS_EXACT_PACKAGE"
            or qa.get("product_id") != config.get("product_id")
            or qa.get("submission_id") != config.get("submission_id")
            or str(qa.get("package_sha256", "")).lower() != str(config.get("expected_sha256", "")).lower()
            or qa.get("identity") != config.get("identity_name")
            or qa.get("version") != config.get("version")
            or str(qa.get("architecture", "")).casefold() != str(config.get("architecture", "")).casefold()):
        return "EXACT_PACKAGE_QA_RECEIPT_REQUIRED"

    settings = config.get("device_family_settings")
    family = settings.get("approval") if isinstance(settings, dict) else None
    if (not isinstance(settings, dict) or settings.get("status") != "OWNER_APPROVED"
            or not isinstance(family, dict)
            or family.get("product_id") != config.get("product_id")
            or family.get("submission_id") != config.get("submission_id")
            or any(not isinstance(family.get(k), str) or not family[k].strip()
                   for k in ("approval_ref", "approved_by", "approved_at"))):
        return "DEVICE_FAMILY_OWNER_APPROVAL_REQUIRED"
    if package is not None:
        try:
            if package.name.casefold() != Path(str(config.get("path", ""))).name.casefold():
                return "PACKAGE_FILENAME_MISMATCH"
            job = verify_file(config, package, expected_sha256=config.get("expected_sha256"),
                              max_bytes=int(config.get("max_bytes", 4_000_000_000)))
            metadata = read_msix_manifest_metadata(package)
            # verify_file validates manifest Identity, Publisher, Version and
            # Architecture; this read additionally binds device-family approval.
            plan = device_family_plan(config, metadata.get("target_device_families", []))
            if plan.get("status") != "OWNER_APPROVED":
                return "DEVICE_FAMILY_OWNER_APPROVAL_REQUIRED"
            allowed = set(plan.get("recommended_store_device_families", []))
            selected = set(plan.get("approved_store_device_families", []))
            if not allowed or not allowed.issubset(selected):
                return "DEVICE_FAMILY_APPROVAL_INCOMPLETE"
            if str(qa.get("package_sha256", "")).lower() != job.sha256.lower():
                return "EXACT_PACKAGE_QA_SHA_MISMATCH"
        except (OSError, ValueError, UploadError):
            return "PACKAGE_VERIFICATION_FAILED"
    return None
