"""Product-key-driven, read-only runtime QA planning and evidence binding."""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uploader.core import UploadError, read_msix_identity, read_msix_manifest_metadata, verify_file
from .store_workflow import StoreWorkflowError, _load_job


def build_runtime_qa_report(*, product: str, config_root: Path,
                            profile_root: Path, package: Path | None) -> dict[str, Any]:
    config, _ = _load_job(product, config_root)
    profile_path = profile_root / f"{product}.json"
    if not profile_path.is_file():
        raise StoreWorkflowError(f"runtime QA profile is missing for {product}")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if profile.get("schema_version") != "all-auto-runtime-qa-profile/1" or profile.get("product_key") != product:
        raise StoreWorkflowError("runtime QA profile schema or product binding is invalid")
    expected = profile.get("package")
    if not isinstance(expected, dict):
        raise StoreWorkflowError("runtime QA profile has no package binding")
    config_binding = {
        "filename": Path(config["path"]).name,
        "sha256": config.get("expected_sha256"),
        "identity_name": config.get("identity_name"),
        "publisher": config.get("publisher"),
        "version": config.get("version"),
        "architecture": config.get("architecture"),
    }
    if any(expected.get(key) != value for key, value in config_binding.items()):
        raise StoreWorkflowError("runtime QA profile differs from the immutable product package binding")

    package_result: dict[str, Any] = {"status": "PACKAGE_NOT_RESOLVED"}
    if package is not None:
        try:
            verified = verify_file(config, package, expected_sha256=config.get("expected_sha256"),
                                   max_bytes=int(config.get("max_bytes", 4_000_000_000)))
            identity = read_msix_identity(package)
            manifest = read_msix_manifest_metadata(package)
            manifest_tuple = {
                "identity_name": identity.get("Name"),
                "publisher": identity.get("Publisher"),
                "version": identity.get("Version"),
                "architecture": identity.get("ProcessorArchitecture"),
            }
            if any(expected.get(key) != value for key, value in manifest_tuple.items()):
                raise StoreWorkflowError("package manifest differs from the runtime QA profile")
            if manifest.get("target_device_families") != expected.get("target_device_families"):
                raise StoreWorkflowError("package target device families differ from the runtime QA profile")
            package_result = {
                "status": "EXACT_PACKAGE_SHA_AND_MANIFEST_VERIFIED",
                "file_name": verified.file_name, "sha256": verified.sha256,
                "size_bytes": verified.size, "signature_state": manifest.get("signature_state"),
                "manifest": manifest_tuple,
                "target_device_families": manifest.get("target_device_families"),
                "application_id": expected.get("application_id"),
            }
        except (OSError, UploadError, StoreWorkflowError) as exc:
            package_result = {"status": "PACKAGE_HOLD", "reason": str(exc)[:500]}

    host = platform.platform()
    host_system = platform.system()
    checks = [{"id": item["id"], "required": item.get("required") is True,
               "status": "NOT_RUN", "automation": item.get("automation"),
               "description": item.get("description")}
              for item in profile.get("runtime_scenarios", [])]
    package_ok = package_result.get("status") == "EXACT_PACKAGE_SHA_AND_MANIFEST_VERIFIED"
    overall = "RUNTIME_QA_READY_TO_RUN" if package_ok else "RUNTIME_QA_HOLD_PACKAGE_NOT_VERIFIED"
    return {
        "schema_version": "all-auto-product-runtime-qa/1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "product_key": product,
        "product_id": config.get("product_id"), "submission_id": config.get("submission_id"),
        "host": {"platform": host, "system": host_system},
        "package": package_result,
        "runtime_kind": profile.get("runtime_kind"),
        "checks": checks,
        "environment_lanes": profile.get("environment_lanes", {}),
        "owner_policy": profile.get("owner_policy", {}),
        "status": overall,
        "qa_pass": False,
        "store_write_performed": False,
        "certification_executed": False,
        "publish_executed": False,
        "note": "This report verifies the frozen package binding and enumerates product-specific checks; it does not claim runtime or visual QA unless a separate execution receipt completes every required scenario.",
    }


def run_profiled_source_driver(*, product: str, profile_root: Path,
                               evidence_root: Path) -> dict[str, Any]:
    """Run only the profile-authorized synthetic-data source GUI driver."""
    profile_path = profile_root / f"{product}.json"
    if not profile_path.is_file():
        raise StoreWorkflowError(f"runtime QA profile is missing for {product}")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    driver = profile.get("source_gui_driver")
    if not isinstance(driver, dict) or driver.get("enabled") is not True:
        return {"status": "NO_APPROVED_SOURCE_DRIVER", "qa_pass": False}
    if platform.system() != "Windows":
        return {"status": "WRONG_HOST_OS", "qa_pass": False,
                "required_host": "Windows"}

    script_rel = str(driver.get("script", ""))
    roots = [Path.home() / "Desktop" / "portfolio-audit" / rel
             for rel in driver.get("source_root_candidates", [])
             if isinstance(rel, str) and rel and not Path(rel).is_absolute()]
    source_root = next((root.resolve() for root in roots
                        if (root / script_rel).is_file()), None)
    if source_root is None:
        return {"status": "SOURCE_DRIVER_NOT_FOUND", "qa_pass": False,
                "searched_candidates": [str(root) for root in roots]}
    script = (source_root / script_rel).resolve()
    if source_root not in script.parents:
        raise StoreWorkflowError("source GUI driver path escaped its product checkout")

    evidence_root = evidence_root.resolve()
    evidence_root.parent.mkdir(parents=True, exist_ok=True)
    if evidence_root.exists():
        raise StoreWorkflowError("refusing to reuse an existing source QA evidence directory")
    receipt_path = evidence_root / "DCA_GUI_QA_RECEIPT.json"
    try:
        completed = subprocess.run(
            [sys.executable, str(script), "--evidence-dir", str(evidence_root)],
            cwd=source_root, capture_output=True, text=True,
            timeout=int(driver.get("timeout_seconds", 240)), check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "SOURCE_DRIVER_TIMEOUT", "qa_pass": False,
                "evidence_root": str(evidence_root)}
    if completed.returncode != 0 or not receipt_path.is_file():
        return {"status": "SOURCE_DRIVER_FAILED", "qa_pass": False,
                "exit_code": completed.returncode,
                "stderr_tail": completed.stderr[-1000:],
                "stdout_tail": completed.stdout[-1000:],
                "evidence_root": str(evidence_root)}
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (receipt.get("schema_version") != "data-contract-auditor-gui-smoke/1"
            or receipt.get("status") != "PASS"
            or receipt.get("execution_type") != "SOURCE_GUI_DRIVER_SYNTHETIC_DATA"):
        return {"status": "SOURCE_DRIVER_RECEIPT_INVALID", "qa_pass": False,
                "evidence_root": str(evidence_root)}
    return {"status": "SOURCE_GUI_DRIVER_PASS", "qa_pass": True,
            "receipt": receipt, "receipt_path": str(receipt_path),
            "evidence_root": str(evidence_root),
            "packaged_runtime_proven": False, "visual_dpi_proven": False}
