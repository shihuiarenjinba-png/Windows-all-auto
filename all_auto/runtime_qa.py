"""Product-key-driven, read-only runtime QA planning and evidence binding."""
from __future__ import annotations

import hashlib
import json
import os
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
    """Run an immutable, clean-checkout DCA source GUI driver and validate its receipt."""
    profile_path = profile_root / f"{product}.json"
    if not profile_path.is_file():
        raise StoreWorkflowError(f"runtime QA profile is missing for {product}")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    driver = profile.get("source_gui_driver")
    binding = profile.get("source_binding")
    if not isinstance(driver, dict) or driver.get("enabled") is not True:
        return {"status": "NO_APPROVED_SOURCE_DRIVER", "qa_pass": False}
    if not isinstance(binding, dict):
        raise StoreWorkflowError("source QA profile has no immutable source binding")
    if platform.system() != "Windows":
        return {"status": "WRONG_HOST_OS", "qa_pass": False, "required_host": "Windows"}

    script_rel = str(driver.get("script", ""))
    expected_commit = str(binding.get("commit", "")).lower()
    expected_repo = str(binding.get("repository", "")).strip().lower().removesuffix(".git")
    expected_driver_sha = str(binding.get("driver_sha256", "")).lower()
    required_checks = driver.get("required_receipt_checks", [])
    scenario_check_map = driver.get("scenario_check_map", {})
    if (not script_rel or len(expected_commit) != 40
            or len(expected_driver_sha) != 64 or not expected_repo
            or not isinstance(required_checks, list) or not required_checks
            or not isinstance(scenario_check_map, dict)):
        raise StoreWorkflowError("source QA binding is incomplete or malformed")

    roots: list[Path] = []
    override = os.environ.get("ALL_AUTO_QA_SOURCE_ROOT")
    if override:
        roots.append(Path(override).expanduser())
    roots.extend(
        Path.home() / "Desktop" / "portfolio-audit" / rel
        for rel in driver.get("source_root_candidates", [])
        if isinstance(rel, str) and rel and not Path(rel).is_absolute()
    )
    source_root = next((root.resolve() for root in roots if (root / script_rel).is_file()), None)
    if source_root is None:
        return {"status": "SOURCE_DRIVER_NOT_FOUND", "qa_pass": False,
                "searched_candidates": [str(root) for root in roots]}
    script = (source_root / script_rel).resolve()
    if source_root not in script.parents:
        raise StoreWorkflowError("source GUI driver path escaped its product checkout")

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(source_root), *args],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if result.returncode != 0:
            raise StoreWorkflowError("source QA checkout is not a readable Git worktree")
        return result.stdout.strip()

    def binding_observation() -> dict[str, Any]:
        head = git("rev-parse", "HEAD").lower()
        status_text = git("status", "--porcelain", "--untracked-files=all")
        origin = git("config", "--get", "remote.origin.url").strip().lower().removesuffix(".git")
        blob = subprocess.run(
            ["git", "-C", str(source_root), "cat-file", "blob",
             f"HEAD:{Path(script_rel).as_posix()}"],
            capture_output=True, timeout=15, check=False,
        )
        if blob.returncode != 0:
            raise StoreWorkflowError("source QA driver Git blob is unavailable")
        script_hash = hashlib.sha256(blob.stdout).hexdigest()
        return {
            "source_sha": head,
            "source_worktree_clean": not bool(status_text),
            "source_uncommitted_entry_count": len([line for line in status_text.splitlines() if line]),
            "source_status_sha256": hashlib.sha256(status_text.encode("utf-8")).hexdigest(),
            "repository_matches": origin == expected_repo,
            "driver_sha256": script_hash,
        }

    try:
        before = binding_observation()
    except (OSError, subprocess.SubprocessError, StoreWorkflowError) as exc:
        return {"status": "SOURCE_BINDING_UNREADABLE", "qa_pass": False,
                "reason": str(exc)[:300]}
    if (before["source_sha"] != expected_commit
            or not before["source_worktree_clean"]
            or not before["repository_matches"]
            or before["driver_sha256"] != expected_driver_sha):
        return {"status": "SOURCE_BINDING_MISMATCH", "qa_pass": False,
                "binding": before, "expected_source_sha": expected_commit,
                "expected_driver_sha256": expected_driver_sha,
                "expected_repository": expected_repo}

    evidence_root = evidence_root.resolve()
    evidence_root.parent.mkdir(parents=True, exist_ok=True)
    if evidence_root.exists():
        raise StoreWorkflowError("refusing to reuse an existing source QA evidence directory")
    receipt_path = evidence_root / str(driver.get("receipt_filename", "LOCAL_REAL_DEVICE_QA.json"))
    child_env = os.environ.copy()
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, str(script), "--evidence-dir", str(evidence_root)],
            cwd=source_root, env=child_env, capture_output=True, text=True,
            timeout=int(driver.get("timeout_seconds", 300)), check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "SOURCE_DRIVER_TIMEOUT", "qa_pass": False,
                "binding": before, "evidence_root": str(evidence_root)}
    if completed.returncode != 0 or not receipt_path.is_file():
        return {"status": "SOURCE_DRIVER_FAILED", "qa_pass": False,
                "exit_code": completed.returncode,
                "stderr_tail": completed.stderr[-1000:],
                "stdout_tail": completed.stdout[-1000:],
                "binding": before, "evidence_root": str(evidence_root)}
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "SOURCE_DRIVER_RECEIPT_INVALID", "qa_pass": False,
                "reason": str(exc)[:300], "binding": before}
    try:
        after = binding_observation()
    except (OSError, subprocess.SubprocessError, StoreWorkflowError) as exc:
        return {"status": "SOURCE_BINDING_CHANGED_DURING_QA", "qa_pass": False,
                "reason": str(exc)[:300], "before": before}
    if before != after:
        return {"status": "SOURCE_BINDING_CHANGED_DURING_QA", "qa_pass": False,
                "before": before, "after": after}

    checks = receipt.get("checks")
    by_name: dict[str, str] = {}
    if isinstance(checks, list):
        for item in checks:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                by_name[item["name"]] = str(item.get("status", ""))
    missing_or_failed = [name for name in required_checks if by_name.get(name) != "PASS"]
    if (receipt.get("schema_version") != binding.get("receipt_schema")
            or receipt.get("product") != "Data Contract Auditor"
            or receipt.get("source_sha", "").lower() != expected_commit
            or receipt.get("source_worktree_clean") is not True
            or receipt.get("driver_sha256", "").lower() != expected_driver_sha
            or receipt.get("execution_type") != "SOURCE_GUI_DRIVER_SYNTHETIC_DATA"
            or receipt.get("status") != "PASS"
            or missing_or_failed):
        return {"status": "SOURCE_DRIVER_RECEIPT_INVALID", "qa_pass": False,
                "missing_or_failed_required_checks": missing_or_failed,
                "binding": before, "receipt_path": str(receipt_path)}

    return {"status": "SOURCE_GUI_DRIVER_PASS", "qa_pass": True,
            "receipt": receipt, "receipt_path": str(receipt_path),
            "evidence_root": str(evidence_root), "binding": before,
            "scenario_check_map": scenario_check_map,
            "required_receipt_checks": required_checks,
            "packaged_runtime_proven": False, "visual_dpi_proven": False}


def source_scenario_results(driver: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map named product-driver checks to configured source-GUI scenarios.

    A scenario is PASS_SOURCE_GUI only when every receipt check mapped to that
    scenario exists and reports PASS. This evidence never proves installed-MSIX
    runtime or visual DPI behavior.
    """
    mapping = driver.get("scenario_check_map", {})
    receipt = driver.get("receipt", {})
    checks = receipt.get("checks", [])
    by_name = {
        item["name"]: str(item.get("status", ""))
        for item in checks
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    } if isinstance(checks, list) else {}
    evidence = driver.get("receipt_path")
    results: dict[str, dict[str, Any]] = {}
    for scenario_id, required_names in mapping.items():
        if not isinstance(scenario_id, str) or not isinstance(required_names, list) or not required_names:
            continue
        failed = [name for name in required_names if by_name.get(name) != "PASS"]
        results[scenario_id] = {
            "status": "PASS_SOURCE_GUI" if not failed else "NOT_RUN",
            "required_receipt_checks": list(required_names),
            "missing_or_failed_receipt_checks": failed,
            "evidence": evidence if not failed else None,
        }
    return results
