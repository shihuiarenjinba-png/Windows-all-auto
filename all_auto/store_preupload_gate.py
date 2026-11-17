"""Fail-closed, read-only gate immediately before Microsoft Store MSIX upload.

The gate performs no Partner Center operation.  It re-hashes the exact local
package on every evaluation and only returns READY when the recovered Draft,
immutable product binding, Store-field observations, and assets are complete.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
import re


SCHEMA = "store-preupload-gate-input/1"
RECEIPT_SCHEMA = "store-preupload-gate-receipt/1"
RECOVERED_DRAFT_SCHEMA = "existing-store-initial-submission-reconcile-receipt/1"
HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
NUMERIC_DRAFT = re.compile(r"^[0-9]+$")
READ_SECTIONS = (
    "packages",
    "pricing",
    "trial",
    "markets",
    "audience",
    "properties",
    "store_listings",
    "submission_options",
)


class PreuploadGateError(ValueError):
    """The local gate input is malformed rather than merely incomplete."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreuploadGateError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PreuploadGateError(f"{label} must be a non-empty string")
    return value.strip()


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _base_receipt(status: str, package_path: Path) -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": status,
        "package_path": str(package_path),
        "package_upload": "NOT_EXECUTED",
        "start_submission": "NOT_REPEATED",
        "certification": "NOT_EXECUTED",
        "publish": "NOT_EXECUTED",
        "write_performed": False,
    }


def _draft_is_exact(draft: dict[str, Any], store_id: str) -> bool:
    if draft.get("schema_version") != RECOVERED_DRAFT_SCHEMA:
        return False
    if draft.get("status") != "INITIAL_SUBMISSION_DRAFT_PRESENT_RECOVERED":
        return False
    if draft.get("submission_state") != "EXISTING_PRODUCT_DRAFT_PRESENT":
        return False
    if str(draft.get("store_id") or "") != store_id:
        return False
    draft_id = str(draft.get("draft_id") or "")
    if not NUMERIC_DRAFT.fullmatch(draft_id):
        return False
    expected_url = (
        "https://partner.microsoft.com/en-us/dashboard/products/"
        f"{store_id}/submissions/{draft_id}"
    )
    if str(draft.get("draft_url") or "").rstrip("/") != expected_url:
        return False
    required_false = (
        "write_performed",
        "retry_authorized",
        "start_submission_clicked",
        "package_uploaded",
        "pricing_changed",
        "submitted",
        "published",
    )
    return all(draft.get(key) is False for key in required_false)


def evaluate_store_preupload_gate(payload: Any) -> dict[str, Any]:
    """Evaluate the upload-approval boundary and re-hash the package now.

    HOLD priority is deliberate: local existence/hash, recovered Draft,
    immutable binding, assets, then unknown/read-incomplete Store state.
    """
    root = _object(payload, "gate input")
    if root.get("schema_version") != SCHEMA:
        raise PreuploadGateError("unsupported schema_version")
    expected = _object(root.get("expected"), "expected")
    observed = _object(root.get("observed"), "observed")
    store_fields = _object(root.get("store_fields"), "store_fields")
    assets = _object(root.get("assets"), "assets")
    draft = _object(root.get("draft_reconciliation"), "draft_reconciliation")

    package_path = Path(_text(root.get("package_path"), "package_path"))
    expected_values = {
        "store_id": _text(expected.get("store_id"), "expected.store_id"),
        "identity_name": _text(expected.get("identity_name"), "expected.identity_name"),
        "publisher": _text(expected.get("publisher"), "expected.publisher"),
        "version": _text(expected.get("version"), "expected.version"),
        "architecture": _text(expected.get("architecture"), "expected.architecture"),
        "source_sha": _text(expected.get("source_sha"), "expected.source_sha").lower(),
        "package_sha256": _text(expected.get("package_sha256"), "expected.package_sha256").upper(),
        "package_file_name": _text(expected.get("package_file_name"), "expected.package_file_name"),
    }
    if not HEX40.fullmatch(expected_values["source_sha"]):
        raise PreuploadGateError("expected.source_sha is invalid")
    if not HEX64.fullmatch(expected_values["package_sha256"]):
        raise PreuploadGateError("expected.package_sha256 is invalid")

    if not package_path.is_file():
        return _base_receipt("HOLD_LOCAL_MSIX_NOT_FOUND", package_path)

    stat = package_path.stat()
    actual_hash = _hash_file(package_path)
    package_evidence = {
        "exists": True,
        "size": stat.st_size,
        "last_write_time_utc": datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat(),
        "sha256": actual_hash,
        "rehash_performed": True,
    }
    if actual_hash != expected_values["package_sha256"]:
        receipt = _base_receipt("HOLD_LOCAL_MSIX_SHA_MISMATCH", package_path)
        receipt["local_package"] = package_evidence
        return receipt

    if not _draft_is_exact(draft, expected_values["store_id"]):
        receipt = _base_receipt("HOLD_SUBMISSION_RECONCILE_REQUIRED", package_path)
        receipt["local_package"] = package_evidence
        return receipt

    exact_keys = (
        "store_id",
        "identity_name",
        "publisher",
        "version",
        "architecture",
        "source_sha",
        "package_sha256",
        "package_file_name",
    )
    mismatches: list[str] = []
    for key in exact_keys:
        actual = str(observed.get(key) or "")
        expected_value = expected_values[key]
        if key == "source_sha":
            actual = actual.lower()
        elif key == "package_sha256":
            actual = actual.upper()
        if actual != expected_value:
            mismatches.append(key)
    if package_path.name != expected_values["package_file_name"]:
        mismatches.append("local_package_file_name")
    if mismatches:
        receipt = _base_receipt("HOLD_EXACT_PACKAGE_MISMATCH", package_path)
        receipt["local_package"] = package_evidence
        receipt["mismatches"] = sorted(set(mismatches))
        return receipt

    if assets.get("ready") is not True:
        receipt = _base_receipt("HOLD_STORE_ASSETS", package_path)
        receipt["local_package"] = package_evidence
        return receipt

    fields_read = all(store_fields.get(section) is True for section in READ_SECTIONS)
    unknown = store_fields.get("unknown_partner_center_state") is not False
    read_only_ui_state_changed = store_fields.get("read_only_ui_state_changed") is True
    read_only_reload_reconciled = store_fields.get("read_only_reload_reconciled") is True
    if (
        not fields_read
        or unknown
        or (read_only_ui_state_changed and not read_only_reload_reconciled)
    ):
        receipt = _base_receipt("HOLD_UNKNOWN_PARTNER_CENTER_STATE", package_path)
        receipt["local_package"] = package_evidence
        receipt["unread_sections"] = [
            section for section in READ_SECTIONS if store_fields.get(section) is not True
        ]
        receipt["read_only_ui_state_changed"] = read_only_ui_state_changed
        receipt["read_only_reload_reconciled"] = read_only_reload_reconciled
        receipt["read_only_reconciliation_required"] = (
            read_only_ui_state_changed and not read_only_reload_reconciled
        )
        return receipt

    receipt = _base_receipt("READY_FOR_MSIX_UPLOAD_APPROVAL", package_path)
    receipt["local_package"] = package_evidence
    receipt["draft"] = {
        "store_id": draft["store_id"],
        "draft_id": str(draft["draft_id"]),
        "draft_url": draft["draft_url"],
        "reconcile_status": draft["status"],
    }
    receipt["immutable_binding"] = expected_values
    receipt["store_fields_read"] = True
    receipt["assets_ready"] = True
    return receipt

