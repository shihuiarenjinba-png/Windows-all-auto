"""Read-only local preflight for registered Store MSIX package candidates."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uploader.core import UploadError, validate_config, verify_file

PRODUCT_KEYS = (
    "ai-upload-guard",
    "image-privacy-cleaner",
    "excel-csv-privacy-cleaner",
    "data-contract-auditor",
    "pdf-privacy",
    "web-evidence-archiver",
)


def verify_local_product(product_key: str, package_root: Path, config_root: Path) -> dict[str, Any]:
    config_path = config_root / f"{product_key}.job.json"
    if not config_path.is_file():
        return {"product_key": product_key, "status": "CONFIG_MISSING", "hold_reasons": ["PRODUCT_JOB_CONFIG_MISSING"]}
    try:
        config = validate_config(json.loads(config_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, UploadError) as exc:
        return {"product_key": product_key, "status": "CONFIG_INVALID", "hold_reasons": [type(exc).__name__, str(exc)]}

    file_name = Path(config["path"]).name
    matches = sorted(path for path in package_root.rglob(file_name) if path.is_file())
    if not matches:
        return {
            "product_key": product_key, "product_name": config["product_name"],
            "product_id": config["product_id"], "submission_id": config["submission_id"],
            "status": "PACKAGE_NOT_FOUND", "expected_file_name": file_name,
            "hold_reasons": ["EXACT_LOCAL_PACKAGE_NOT_FOUND"],
        }
    if len(matches) != 1:
        return {
            "product_key": product_key, "product_name": config["product_name"],
            "product_id": config["product_id"], "submission_id": config["submission_id"],
            "status": "PACKAGE_PATH_AMBIGUOUS", "expected_file_name": file_name,
            "matching_paths": [str(path) for path in matches],
            "hold_reasons": ["MULTIPLE_MATCHING_PACKAGE_FILES_REFUSE_TO_GUESS"],
        }

    package = matches[0].resolve()
    expected = config.get("expected_sha256")
    expected = expected if isinstance(expected, str) and len(expected) == 64 else None
    try:
        job = verify_file(
            config, package, expected_sha256=expected,
            max_bytes=int(config.get("max_bytes", 4_000_000_000)),
        )
    except UploadError as exc:
        return {
            "product_key": product_key, "product_name": config["product_name"],
            "product_id": config["product_id"], "submission_id": config["submission_id"],
            "package_file_name": file_name, "status": "STATIC_VERIFICATION_FAILED",
            "error_code": exc.code, "error": str(exc),
            "hold_reasons": ["PACKAGE_STATIC_VERIFICATION_FAILED"],
        }

    holds = list(config.get("upload_hold_reasons", []))
    if config.get("upload_approved") is not True:
        holds.append("PRODUCT_UPLOAD_APPROVAL_NOT_SET")
    return {
        "product_key": product_key, "product_name": job.product_name,
        "product_id": job.product_id, "submission_id": job.submission_id,
        "source_sha": config.get("source_sha", config.get("ref")),
        "package_file_name": job.file_name, "package_path": str(package),
        "version": job.version, "architecture": job.architecture,
        "identity_name": job.identity_name, "publisher": job.publisher,
        "sha256": job.sha256, "expected_sha256_match": bool(expected),
        "status": "STATIC_VERIFICATION_PASS_HELD" if holds else "STATIC_VERIFICATION_PASS_REQUIRES_LIVE_RECHECK",
        "upload_approved": config.get("upload_approved") is True,
        "hold_reasons": holds,
        "live_partner_center_recheck_required": True,
    }


def build_fleet_preflight(package_root: Path, config_root: Path) -> dict[str, Any]:
    if not package_root.is_dir():
        raise ValueError(f"Package root is not a directory: {package_root}")
    products = [verify_local_product(key, package_root, config_root) for key in PRODUCT_KEYS]
    products.append({
        "product_key": "workflow-automation-hub",
        "product_name": "Workflow Automation Hub",
        "product_id": "9P6SXJNNB5KK",
        "status": "NO_EXISTING_SUBMISSION",
        "hold_reasons": [
            "NO_EXISTING_DRAFT_IN_2026-11-25_OBSERVATION",
            "TECHNICAL_DRAFT_NOT_OWNER_APPROVED",
            "DO_NOT_START_SUBMISSION_FROM_EXISTING_DRAFT_UPLOADER",
        ],
    })
    verified = sum(item.get("status") in {"STATIC_VERIFICATION_PASS_HELD", "STATIC_VERIFICATION_PASS_REQUIRES_LIVE_RECHECK"} for item in products)
    return {
        "schema_version": "store-msix-fleet-preflight/1",
        "read_only": True,
        "package_root": str(package_root.resolve()),
        "config_root": str(config_root.resolve()),
        "products_total": len(products),
        "static_package_verifications_passed": verified,
        "partner_center_touched": False,
        "package_uploaded": False,
        "packages_saved": False,
        "certification_started": False,
        "published": False,
        "products": products,
    }
