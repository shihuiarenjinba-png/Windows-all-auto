"""Bind local Store pre-upload checks into one machine-readable receipt.

This module is intentionally product-agnostic and read-only.  It joins the
cheap local candidate check with the Windows MSIX unpack/Manifest/EXE check;
it never downloads, uploads, installs, signs, submits, or publishes anything.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from all_auto.store_product_handoff import (
    StoreHandoffError,
    normalize_store_product_handoff,
)


RECEIPT_SCHEMA = "store-preupload-readiness/1"
PREFLIGHT_SCHEMA = "local-static-package-preflight/1"
READY = "READY_FOR_MSIX_UPLOAD_APPROVAL"


class LocalPreuploadReceiptError(ValueError):
    """The component evidence cannot safely authorize an upload request."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LocalPreuploadReceiptError(f"{label} must be an object")
    return value


def _exact(value: Any, expected: Any, label: str) -> None:
    if value != expected:
        raise LocalPreuploadReceiptError(f"{label} mismatch")


def finalize_local_preupload_receipt(
    candidate: Any,
    static_preflight: Any,
    handoff: Any,
) -> dict[str, Any]:
    """Return one exact-package receipt or fail closed.

    The caller must preserve a HOLD if this function raises.  READY is only a
    boundary at which a human may be asked to approve an upload; it is never
    upload authorization itself.
    """
    candidate_obj = _object(candidate, "candidate receipt")
    preflight = _object(static_preflight, "static preflight")
    handoff_obj = _object(handoff, "Store handoff")
    try:
        normalized = normalize_store_product_handoff(handoff_obj)
    except StoreHandoffError as exc:
        raise LocalPreuploadReceiptError(str(exc)) from exc

    _exact(candidate_obj.get("schema_version"), RECEIPT_SCHEMA, "candidate schema")
    _exact(candidate_obj.get("status"), READY, "candidate status")
    _exact(preflight.get("schema_version"), PREFLIGHT_SCHEMA, "preflight schema")
    _exact(preflight.get("status"), "PASS", "preflight status")

    for field in (
        "package_upload_executed",
        "certification_executed",
        "published",
    ):
        if candidate_obj.get(field) is not False:
            raise LocalPreuploadReceiptError(f"candidate {field} must be false")

    product = normalized["product"]
    package = normalized["package"]
    identity = normalized["identity"]
    expected = {
        "store_id": identity["store_id"],
        "source_sha": product["source_sha"],
        "package_sha256": package["package_sha256"],
        "exe_sha256": package["exe_sha256"],
        "package_file_name": package["file_name"],
        "identity_name": identity["name"],
        "publisher": identity["publisher"],
        "version": identity["version"],
        "architecture": identity["architecture"],
    }

    _exact(candidate_obj.get("store_id"), expected["store_id"], "candidate Store ID")
    _exact(candidate_obj.get("source_sha"), expected["source_sha"], "candidate source SHA")
    _exact(
        str(candidate_obj.get("expected_package_sha256") or "").lower(),
        expected["package_sha256"].lower(),
        "candidate expected package SHA",
    )
    _exact(
        str(candidate_obj.get("actual_package_sha256") or "").lower(),
        expected["package_sha256"].lower(),
        "candidate actual package SHA",
    )
    _exact(
        candidate_obj.get("expected_package_filename"),
        expected["package_file_name"],
        "candidate expected package filename",
    )
    _exact(
        candidate_obj.get("package_filename"),
        expected["package_file_name"],
        "candidate package filename",
    )
    if candidate_obj.get("exact_package_match") is not True:
        raise LocalPreuploadReceiptError("candidate exact_package_match must be true")

    _exact(preflight.get("store_id"), expected["store_id"], "preflight Store ID")
    _exact(preflight.get("source_sha"), expected["source_sha"], "preflight source SHA")
    _exact(
        str(preflight.get("package_sha256") or "").lower(),
        expected["package_sha256"].lower(),
        "preflight package SHA",
    )
    _exact(
        str(preflight.get("unpacked_exe_sha256") or "").lower(),
        expected["exe_sha256"].lower(),
        "preflight EXE SHA",
    )
    if preflight.get("manifest_identity_verified") is not True:
        raise LocalPreuploadReceiptError("Manifest Identity was not verified")
    if preflight.get("package_rebuilt") is not False:
        raise LocalPreuploadReceiptError("package_rebuilt must be false")
    if preflight.get("security_bypass_used") is not False:
        raise LocalPreuploadReceiptError("security_bypass_used must be false")
    if preflight.get("source_checkout_mode") not in {"ExactHead", "ContainedCommit"}:
        raise LocalPreuploadReceiptError("unsupported source checkout mode")

    receipt = deepcopy(candidate_obj)
    receipt["receipt_kind"] = "READ_ONLY_LOCAL_PREUPLOAD_HANDOFF"
    receipt["ready_for_upload_approval"] = True
    receipt["partner_center_write_performed"] = False
    receipt["immutable_binding"] = expected
    receipt["static_preflight"] = {
        "status": "PASS",
        "local_repo_head": preflight.get("local_repo_head"),
        "source_checkout_mode": preflight["source_checkout_mode"],
        "manifest_identity_verified": True,
        "unpacked_exe_sha256": preflight["unpacked_exe_sha256"],
        "self_test_pass": preflight.get("self_test_pass"),
        "package_rebuilt": False,
        "security_bypass_used": False,
    }
    receipt["store_actions"] = {
        "package_upload": "NOT_EXECUTED",
        "certification": "NOT_EXECUTED",
        "publish": "NOT_EXECUTED",
    }
    return receipt
