"""Validation for one-shot unsigned exact EXE launch evidence.

The launch lane is intentionally narrow: one normal-user attempt against bytes
already bound by the Store handoff. It never authorizes elevation, policy changes,
certificate changes, installation, Store upload, certification, or publication.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


SCHEMA = "unsigned-exe-launch-receipt/1"
PASS = "PASS_NORMAL_EXIT"
HOLD_STATUSES = {
    "STARTED_NOT_CLOSED_WITHIN_WINDOW",
    "EXITED_NONZERO",
    "APPLICATION_CONTROL_BLOCKED",
    "LAUNCH_FAILED",
}


class UnsignedExeLaunchReceiptError(ValueError):
    pass


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise UnsignedExeLaunchReceiptError(f"{label} must be a SHA256 hex string")
    return text


def validate_unsigned_exe_launch_receipt(
    receipt: Any,
    *,
    expected_exe_sha256: str,
) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise UnsignedExeLaunchReceiptError("receipt must be an object")
    if receipt.get("schema_version") != SCHEMA:
        raise UnsignedExeLaunchReceiptError("unsupported launch receipt schema")

    status = receipt.get("status")
    if status not in {PASS, *HOLD_STATUSES}:
        raise UnsignedExeLaunchReceiptError("unsupported launch status")

    expected = _sha(expected_exe_sha256, "expected EXE SHA256")
    receipt_expected = _sha(receipt.get("expected_exe_sha256"), "receipt expected EXE SHA256")
    actual = _sha(receipt.get("actual_exe_sha256"), "actual EXE SHA256")
    if receipt_expected != expected or actual != expected:
        raise UnsignedExeLaunchReceiptError("launch receipt EXE SHA256 mismatch")

    required_false = (
        "elevated",
        "package_rebuilt",
        "security_bypass_used",
        "security_policy_modified",
        "certificate_store_modified",
        "alternate_bypass_used",
        "msix_installed",
        "partner_center_write_performed",
        "package_uploaded",
        "certification_submitted",
        "published",
    )
    for key in required_false:
        if receipt.get(key) is not False:
            raise UnsignedExeLaunchReceiptError(f"unsafe launch receipt flag: {key}")
    if receipt.get("normal_user_context") is not True:
        raise UnsignedExeLaunchReceiptError("normal_user_context must be true")
    if receipt.get("launch_attempts") != 1:
        raise UnsignedExeLaunchReceiptError("launch_attempts must equal exactly 1")

    process_started = receipt.get("process_started")
    normal_exit = receipt.get("normal_exit")
    exit_code = receipt.get("exit_code")

    if status == PASS:
        if process_started is not True or normal_exit is not True or exit_code != 0:
            raise UnsignedExeLaunchReceiptError("PASS requires one clean normal exit")
    elif status == "STARTED_NOT_CLOSED_WITHIN_WINDOW":
        if process_started is not True or normal_exit is not False or exit_code is not None:
            raise UnsignedExeLaunchReceiptError(
                "running-window HOLD has inconsistent process evidence"
            )
    elif status == "EXITED_NONZERO":
        if (
            process_started is not True
            or normal_exit is not False
            or type(exit_code) is not int
            or exit_code == 0
        ):
            raise UnsignedExeLaunchReceiptError(
                "nonzero-exit HOLD has inconsistent process evidence"
            )
    elif status == "APPLICATION_CONTROL_BLOCKED":
        if process_started is not False or normal_exit is not False:
            raise UnsignedExeLaunchReceiptError(
                "Application Control block must occur before process start"
            )
        event_ids = receipt.get("code_integrity_event_ids")
        if (
            not isinstance(event_ids, list)
            or not event_ids
            or not all(type(value) is int and value > 0 for value in event_ids)
        ):
            raise UnsignedExeLaunchReceiptError(
                "Application Control block requires Code Integrity event evidence"
            )
    elif status == "LAUNCH_FAILED":
        if process_started is not False or normal_exit is not False:
            raise UnsignedExeLaunchReceiptError("launch failure evidence is inconsistent")

    result = deepcopy(receipt)
    result["expected_exe_sha256"] = expected
    result["actual_exe_sha256"] = actual
    result["validated"] = True
    result["local_final_qa_pass"] = False
    result["store_actions_authorized"] = False
    return result


def reconcile_delayed_application_control_evidence(
    launch_receipt: Any,
    code_integrity_evidence: Any,
    *,
    expected_exe_sha256: str,
) -> dict[str, Any]:
    """Reclassify one immutable LAUNCH_FAILED receipt using later CI log evidence.

    This is read-only reconciliation: it never changes the original launch receipt
    and never implies a second launch attempt.
    """
    launch = validate_unsigned_exe_launch_receipt(
        launch_receipt,
        expected_exe_sha256=expected_exe_sha256,
    )
    if launch["status"] != "LAUNCH_FAILED":
        raise UnsignedExeLaunchReceiptError(
            "delayed Code Integrity reconciliation requires original LAUNCH_FAILED"
        )
    if launch.get("process_started") is not False:
        raise UnsignedExeLaunchReceiptError(
            "delayed block reconciliation requires process_started=false"
        )

    if not isinstance(code_integrity_evidence, dict):
        raise UnsignedExeLaunchReceiptError("Code Integrity evidence must be an object")
    if code_integrity_evidence.get("schema_version") != "code-integrity-block-evidence/1":
        raise UnsignedExeLaunchReceiptError("unsupported Code Integrity evidence schema")

    evidence_sha = _sha(
        code_integrity_evidence.get("exe_sha256"),
        "Code Integrity evidence EXE SHA256",
    )
    if evidence_sha != _sha(expected_exe_sha256, "expected EXE SHA256"):
        raise UnsignedExeLaunchReceiptError("Code Integrity evidence EXE SHA256 mismatch")

    if code_integrity_evidence.get("launch_attempts") != 1:
        raise UnsignedExeLaunchReceiptError(
            "Code Integrity evidence must preserve exactly one launch attempt"
        )
    if code_integrity_evidence.get("process_started") is not False:
        raise UnsignedExeLaunchReceiptError(
            "Code Integrity block evidence requires process_started=false"
        )
    for key in (
        "security_bypass_used",
        "security_policy_modified",
        "certificate_store_modified",
        "alternate_bypass_used",
        "msix_installed",
        "partner_center_write_performed",
        "package_uploaded",
        "certification_submitted",
        "published",
    ):
        if code_integrity_evidence.get(key) is not False:
            raise UnsignedExeLaunchReceiptError(
                f"unsafe delayed Code Integrity evidence flag: {key}"
            )

    event_ids = code_integrity_evidence.get("event_ids")
    if (
        not isinstance(event_ids, list)
        or not event_ids
        or not all(type(value) is int and value > 0 for value in event_ids)
    ):
        raise UnsignedExeLaunchReceiptError(
            "Code Integrity evidence requires event_ids"
        )
    blocking_ids = sorted({value for value in event_ids if value in {3033, 3077}})
    if not blocking_ids:
        raise UnsignedExeLaunchReceiptError(
            "Code Integrity evidence lacks block-class event 3033/3077"
        )

    policy = str(code_integrity_evidence.get("policy_name") or "").strip()
    policy_guid = str(code_integrity_evidence.get("policy_guid") or "").strip()
    if not policy:
        raise UnsignedExeLaunchReceiptError("Code Integrity evidence policy_name is required")
    if not policy_guid:
        raise UnsignedExeLaunchReceiptError("Code Integrity evidence policy_guid is required")

    result = {
        "schema_version": "unsigned-exe-launch-reconciliation-receipt/1",
        "status": "APPLICATION_CONTROL_BLOCKED",
        "original_launch_status": launch["status"],
        "expected_exe_sha256": launch["expected_exe_sha256"],
        "actual_exe_sha256": launch["actual_exe_sha256"],
        "launch_attempts": 1,
        "process_started": False,
        "normal_exit": False,
        "exit_code": None,
        "blocking_event_ids": blocking_ids,
        "all_observed_event_ids": sorted(set(event_ids)),
        "policy_name": policy,
        "policy_guid": policy_guid,
        "original_receipt_preserved": True,
        "second_launch_performed": False,
        "security_bypass_used": False,
        "security_policy_modified": False,
        "certificate_store_modified": False,
        "alternate_bypass_used": False,
        "msix_installed": False,
        "partner_center_write_performed": False,
        "package_uploaded": False,
        "certification_submitted": False,
        "published": False,
        "local_final_qa_pass": False,
        "store_actions_authorized": False,
    }
    return result


def bind_unsigned_launch_to_local_qa(
    qa_template: Any,
    launch_receipt: Any,
    *,
    expected_exe_sha256: str,
) -> dict[str, Any]:
    if not isinstance(qa_template, dict):
        raise UnsignedExeLaunchReceiptError("local QA template must be an object")
    if qa_template.get("schema_version") != "local-final-qa-receipt/1":
        raise UnsignedExeLaunchReceiptError("unsupported local QA template schema")
    if qa_template.get("status") != "HOLD":
        raise UnsignedExeLaunchReceiptError("local QA must remain HOLD before full acceptance")

    launch = validate_unsigned_exe_launch_receipt(
        launch_receipt,
        expected_exe_sha256=expected_exe_sha256,
    )
    result = deepcopy(qa_template)
    result["unsigned_exe_launch"] = launch
    result["status"] = "HOLD"
    result["product_specific_acceptance_passed"] = False
    result["normal_exit_passed"] = launch["status"] == PASS
    result["package_rebuilt"] = False
    result["security_bypass_used"] = False
    return result
