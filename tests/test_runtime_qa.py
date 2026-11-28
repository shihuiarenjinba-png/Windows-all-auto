from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from all_auto.runtime_qa import (
    build_runtime_qa_report,
    run_profiled_source_driver,
    source_scenario_results,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT / "uploader" / "config"
PROFILE_ROOT = CONFIG_ROOT / "runtime_qa_profiles"

RECEIPT_CHECKS = [
    "core_csv_drift", "csv_xlsx_compare", "invalid_input_rejected",
    "outputs_reopen", "inputs_unchanged", "writable_default_output",
    "default_output_files_written", "ui_language_and_scaling",
    "ui_compare_workflow", "ui_error_path", "close_relaunch",
]
SCENARIO_MAP = {
    "language_switch_ja": ["ui_language_and_scaling"],
    "language_switch_en": ["ui_language_and_scaling"],
    "launch_and_render": ["ui_language_and_scaling"],
    "csv_schema_and_quality_comparison": ["core_csv_drift", "ui_compare_workflow"],
    "xlsx_input": ["csv_xlsx_compare"],
    "report_output_reopens": ["outputs_reopen", "default_output_files_written"],
    "invalid_csv_error": ["invalid_input_rejected", "ui_error_path"],
    "normal_exit_and_relaunch": ["close_relaunch"],
}
DRIVER_SOURCE = r'''#!/usr/bin/env python3
import hashlib, json, os, subprocess, sys
from pathlib import Path
args = sys.argv
evidence = Path(args[args.index("--evidence-dir") + 1])
evidence.mkdir(parents=True)
root = Path(__file__).resolve().parents[1]
source_sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
status = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"], text=True)
driver = Path(__file__).resolve()
driver_rel = driver.relative_to(root).as_posix()
driver_blob = subprocess.check_output(["git", "-C", str(root), "cat-file", "blob", "HEAD:" + driver_rel])
checks = [{"name": name, "status": "PASS"} for name in [
  "core_csv_drift", "csv_xlsx_compare", "invalid_input_rejected", "outputs_reopen",
  "inputs_unchanged", "writable_default_output", "default_output_files_written",
  "ui_language_and_scaling", "ui_compare_workflow", "ui_error_path", "close_relaunch"]]
missing = os.environ.get("SOURCE_QA_MISSING_CHECK")
if missing:
  checks = [item for item in checks if item["name"] != missing]
receipt = {
  "schema_version": "data-contract-local-real-device-qa/1",
  "product": "Data Contract Auditor",
  "source_sha": source_sha,
  "source_worktree_clean": not bool(status),
  "driver_sha256": hashlib.sha256(driver_blob).hexdigest(),
  "execution_type": "SOURCE_GUI_DRIVER_SYNTHETIC_DATA",
  "status": "PASS",
  "checks": checks,
}
(evidence / "LOCAL_REAL_DEVICE_QA.json").write_text(json.dumps(receipt), encoding="utf-8")
'''


class RuntimeQaPlanTests(unittest.TestCase):
    def _make_source_fixture(self, root: Path):
        checkout = root / "dca-source"
        script = checkout / "scripts" / "local_real_device_qa.py"
        script.parent.mkdir(parents=True)
        script.write_text(DRIVER_SOURCE, encoding="utf-8")
        subprocess.run(["git", "init", str(checkout)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(checkout), "config", "user.email", "qa@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(checkout), "config", "user.name", "QA fixture"], check=True)
        subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin",
                        "https://github.com/shihuiarenjinba-png/csv-import-validator.git"], check=True)
        subprocess.run(["git", "-C", str(checkout), "add", "scripts/local_real_device_qa.py"], check=True)
        subprocess.run(["git", "-C", str(checkout), "commit", "-m", "fixture"], check=True, capture_output=True)
        commit = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        driver_blob = subprocess.check_output([
            "git", "-C", str(checkout), "cat-file", "blob",
            "HEAD:scripts/local_real_device_qa.py",
        ])
        profile_root = root / "profiles"
        profile_root.mkdir()
        profile = {
            "source_gui_driver": {
                "enabled": True, "script": "scripts/local_real_device_qa.py",
                "source_root_candidates": [], "timeout_seconds": 30,
                "receipt_filename": "LOCAL_REAL_DEVICE_QA.json",
                "required_receipt_checks": RECEIPT_CHECKS,
                "scenario_check_map": SCENARIO_MAP,
            },
            "source_binding": {
                "repository": "https://github.com/shihuiarenjinba-png/csv-import-validator",
                "commit": commit, "receipt_schema": "data-contract-local-real-device-qa/1",
                "driver_sha256": hashlib.sha256(driver_blob).hexdigest(),
            },
        }
        (profile_root / "data-contract-auditor.json").write_text(json.dumps(profile), encoding="utf-8")
        return checkout, script, profile_root, profile

    def _run_source_fixture(self, root: Path):
        checkout, script, profile_root, profile = self._make_source_fixture(root)
        evidence = root / "evidence"
        with (
            patch("all_auto.runtime_qa.platform.system", return_value="Windows"),
            patch.dict(os.environ, {"ALL_AUTO_QA_SOURCE_ROOT": str(checkout)}, clear=False),
        ):
            result = run_profiled_source_driver(product="data-contract-auditor",
                profile_root=profile_root, evidence_root=evidence)
        return result, checkout, script, profile_root, profile, evidence

    def test_clean_pinned_checkout_accepts_current_dca_receipt_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, _, _, _, _, _ = self._run_source_fixture(Path(temporary))
            self.assertEqual(result["status"], "SOURCE_GUI_DRIVER_PASS")
            self.assertEqual(result["receipt"]["schema_version"], "data-contract-local-real-device-qa/1")
            self.assertEqual(result["binding"]["source_worktree_clean"], True)
            self.assertEqual(result["binding"]["driver_sha256"], result["receipt"]["driver_sha256"])
            self.assertFalse(result["packaged_runtime_proven"])
            self.assertFalse(result["visual_dpi_proven"])

    def test_dirty_source_checkout_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout, _, profile_root, _ = self._make_source_fixture(root)
            (checkout / "untracked.txt").write_text("dirty", encoding="utf-8")
            with (
                patch("all_auto.runtime_qa.platform.system", return_value="Windows"),
                patch.dict(os.environ, {"ALL_AUTO_QA_SOURCE_ROOT": str(checkout)}, clear=False),
            ):
                result = run_profiled_source_driver(product="data-contract-auditor",
                    profile_root=profile_root, evidence_root=root / "evidence")
            self.assertEqual(result["status"], "SOURCE_BINDING_MISMATCH")
            self.assertFalse(result["binding"]["source_worktree_clean"])

    def test_wrong_pinned_commit_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout, _, profile_root, profile = self._make_source_fixture(root)
            profile["source_binding"]["commit"] = "0" * 40
            (profile_root / "data-contract-auditor.json").write_text(json.dumps(profile), encoding="utf-8")
            with (
                patch("all_auto.runtime_qa.platform.system", return_value="Windows"),
                patch.dict(os.environ, {"ALL_AUTO_QA_SOURCE_ROOT": str(checkout)}, clear=False),
            ):
                result = run_profiled_source_driver(product="data-contract-auditor",
                    profile_root=profile_root, evidence_root=root / "evidence")
            self.assertEqual(result["status"], "SOURCE_BINDING_MISMATCH")

    def test_modified_driver_is_rejected_by_hash_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout, script, profile_root, _ = self._make_source_fixture(root)
            script.write_text(script.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
            with (
                patch("all_auto.runtime_qa.platform.system", return_value="Windows"),
                patch.dict(os.environ, {"ALL_AUTO_QA_SOURCE_ROOT": str(checkout)}, clear=False),
            ):
                result = run_profiled_source_driver(product="data-contract-auditor",
                    profile_root=profile_root, evidence_root=root / "evidence")
            self.assertEqual(result["status"], "SOURCE_BINDING_MISMATCH")
            self.assertFalse(result["binding"]["source_worktree_clean"])
            self.assertEqual(result["binding"]["driver_sha256"],
                             result["expected_driver_sha256"])

    def test_missing_required_receipt_check_prevents_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout, _, profile_root, _ = self._make_source_fixture(root)
            with (
                patch("all_auto.runtime_qa.platform.system", return_value="Windows"),
                patch.dict(os.environ, {
                    "ALL_AUTO_QA_SOURCE_ROOT": str(checkout),
                    "SOURCE_QA_MISSING_CHECK": "default_output_files_written",
                }, clear=False),
            ):
                result = run_profiled_source_driver(product="data-contract-auditor",
                    profile_root=profile_root, evidence_root=root / "evidence")
            self.assertEqual(result["status"], "SOURCE_DRIVER_RECEIPT_INVALID")
            self.assertIn("default_output_files_written", result["missing_or_failed_required_checks"])

    def test_scenario_mapping_uses_receipt_names_and_requires_all_mapped_checks(self):
        driver = {
            "scenario_check_map": {
                "csv_schema_and_quality_comparison": ["core_csv_drift", "ui_compare_workflow"],
                "report_output_reopens": ["outputs_reopen", "default_output_files_written"],
            },
            "receipt_path": "LOCAL_REAL_DEVICE_QA.json",
            "receipt": {"checks": [
                {"name": "core_csv_drift", "status": "PASS"},
                {"name": "ui_compare_workflow", "status": "PASS"},
                {"name": "outputs_reopen", "status": "PASS"},
                {"name": "default_output_files_written", "status": "FAIL"},
            ]},
        }
        results = source_scenario_results(driver)
        self.assertEqual(results["csv_schema_and_quality_comparison"]["status"], "PASS_SOURCE_GUI")
        self.assertEqual(results["report_output_reopens"]["status"], "NOT_RUN")
        self.assertIsNone(results["report_output_reopens"]["evidence"])

    def test_product_key_profile_keeps_server_and_windows_10_11_lanes_distinct(self):
        report = build_runtime_qa_report(product="data-contract-auditor",
            config_root=CONFIG_ROOT, profile_root=PROFILE_ROOT, package=None)
        self.assertEqual(report["status"], "RUNTIME_QA_HOLD_PACKAGE_NOT_VERIFIED")
        self.assertFalse(report["qa_pass"])
        lanes = report["environment_lanes"]
        self.assertIn("windows_server_automation", lanes)
        self.assertIn("windows_10_11_interactive", lanes)
        self.assertNotEqual(lanes["windows_server_automation"]["status"],
                            lanes["windows_10_11_interactive"]["status"])
        self.assertTrue(all(check["status"] == "NOT_RUN" for check in report["checks"]))
        self.assertFalse(report["store_write_performed"])

    def test_profile_cannot_change_immutable_package_sha(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_root = Path(temporary)
            profile = json.loads((PROFILE_ROOT / "data-contract-auditor.json").read_text(encoding="utf-8"))
            profile["package"]["sha256"] = "0" * 64
            (profile_root / "data-contract-auditor.json").write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "immutable product package binding"):
                build_runtime_qa_report(product="data-contract-auditor", config_root=CONFIG_ROOT,
                                        profile_root=profile_root, package=None)


if __name__ == "__main__":
    unittest.main()
