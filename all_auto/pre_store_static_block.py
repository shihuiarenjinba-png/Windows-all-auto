"""Build the limited pre-Store static QA receipt from immutable evidence."""
from __future__ import annotations

from typing import Any

from all_auto.store_product_handoff import normalize_store_product_handoff
from all_auto.unsigned_exe_launch import (
    UnsignedExeLaunchReceiptError,
    validate_unsigned_exe_launch_reconciliation_receipt,
)


class PreStoreStaticBlockError(ValueError):
    pass


def build_pre_store_static_block_receipt(
    handoff: Any,
    artifact_receipt: Any,
    launch_reconciliation: Any,
) -> dict[str, Any]:
    current = normalize_store_product_handoff(handoff)
    if not isinstance(artifact_receipt, dict):
        raise PreStoreStaticBlockError("artifact receipt must be an object")
    if artifact_receipt.get("schema_version") != "local-store-product-artifact-pull-receipt/1":
        raise PreStoreStaticBlockError("unsupported artifact receipt schema")
    if artifact_receipt.get("status") != "LOCAL_STORE_PRODUCT_ARTIFACT_VERIFIED":
        raise PreStoreStaticBlockError("artifact receipt is not verified")

    expected_store_id = current["identity"]["store_id"]
    expected_source_sha = current["product"]["source_sha"]
    expected_package_sha = current["package"]["package_sha256"]
    expected_exe_sha = current["package"]["exe_sha256"]

    if artifact_receipt.get("store_id") != expected_store_id:
        raise PreStoreStaticBlockError("artifact receipt Store ID mismatch")
    if str(artifact_receipt.get("source_sha") or "").lower() != expected_source_sha:
        raise PreStoreStaticBlockError("artifact receipt source SHA mismatch")
    package = artifact_receipt.get("package")
    if not isinstance(package, dict):
        raise PreStoreStaticBlockError("artifact receipt package is missing")
    if str(package.get("sha256") or "").lower() != expected_package_sha:
        raise PreStoreStaticBlockError("artifact receipt package SHA mismatch")

    for key in (
        "package_rebuilt",
        "security_bypass_used",
        "package_installed",
        "submitted_to_store",
        "certification_submitted",
        "published",
    ):
        if artifact_receipt.get(key) is not False:
            raise PreStoreStaticBlockError(f"unsafe artifact receipt flag: {key}")

    try:
        launch = validate_unsigned_exe_launch_reconciliation_receipt(
            launch_reconciliation,
            expected_exe_sha256=expected_exe_sha,
        )
    except UnsignedExeLaunchReceiptError as exc:
        raise PreStoreStaticBlockError(str(exc)) from exc

    return {
        "schema_version": "pre-store-static-qa-receipt/1",
        "status": "APPLICATION_CONTROL_BLOCKED",
        "store_id": expected_store_id,
        "source_sha": expected_source_sha,
        "package_sha256": expected_package_sha,
        "tests_passed": True,
        "package_sha_verified": True,
        "unpacked_exe_sha_verified": True,
        "manifest_identity_verified": True,
        "application_control_blocked": True,
        "package_rebuilt": False,
        "security_bypass_used": False,
        "security_policy_modified": False,
        "certificate_store_modified": False,
        "alternate_bypass_used": False,
        "artifact_run_id": artifact_receipt.get("artifact_run_id"),
        "artifact_name": artifact_receipt.get("artifact_name"),
        "github_artifact_id": artifact_receipt.get("github_artifact_id"),
        "github_artifact_digest": artifact_receipt.get("github_artifact_digest"),
        "exe_sha256": expected_exe_sha,
        "launch_reconciliation_status": launch["status"],
        "blocking_event_ids": list(launch["blocking_event_ids"]),
        "policy_name": launch["policy_name"],
        "policy_guid": launch["policy_guid"],
        "original_launch_status": launch["original_launch_status"],
        "original_receipt_preserved": True,
        "second_launch_performed": False,
    }
