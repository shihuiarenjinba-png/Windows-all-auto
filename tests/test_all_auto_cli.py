from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone
from uuid import uuid4

from all_auto.__main__ import main, _store_run_exit_code


class StoreCliTests(unittest.TestCase):
    def test_store_qa_execute_runs_source_driver_without_promoting_package_gate(self):
        scenarios = [{"id": key, "required": True, "status": "NOT_RUN"}
                     for key in ("language_switch_ja", "language_switch_en",
                                 "launch_and_render", "csv_schema_and_quality_comparison",
                                 "xlsx_input", "report_output_reopens", "invalid_csv_error",
                                 "normal_exit_and_relaunch")]
        driver_checks = [{"id": key, "status": "PASS"} for key in
                         ("language_toggle_ja", "language_toggle_en", "launch_and_render",
                          "csv_compare_and_output_reopen", "xlsx_compare_and_output_reopen",
                          "duplicate_header_visible_error", "normal_exit_and_relaunch")]
        with tempfile.TemporaryDirectory() as temporary, \
             patch("all_auto.__main__._load_job", return_value=({"product_id": "p", "submission_id": "s"}, Path(temporary) / "job.json")), \
             patch("all_auto.__main__.acquire_registered_package", return_value={"status": "PACKAGE_ACQUISITION_HOLD"}), \
             patch("all_auto.runtime_qa.build_runtime_qa_report", return_value={
                 "status": "RUNTIME_QA_HOLD_PACKAGE_NOT_VERIFIED", "qa_pass": False,
                 "package": {"status": "PACKAGE_HOLD"}, "checks": scenarios}), \
             patch("all_auto.runtime_qa.run_profiled_source_driver", return_value={
                 "status": "SOURCE_GUI_DRIVER_PASS", "qa_pass": True,
                 "receipt": {"checks": driver_checks}, "receipt_path": "receipt.json",
                 "packaged_runtime_proven": False}), \
             patch("all_auto.__main__._write_store_report", return_value=Path(temporary) / "qa.json") as writer, \
             contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = main(["store", "qa", "--product", "data-contract-auditor",
                         "--package", str(Path(temporary) / "candidate.msix"),
                         "--out", temporary, "--execute"])
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "SOURCE_GUI_QA_PASS_PACKAGED_RUNTIME_UNVERIFIED")
        self.assertFalse(result["qa_pass"])
        self.assertFalse(result["store_write_performed"])
        persisted = writer.call_args.args[0]
        self.assertTrue(all(item["status"] == "PASS_SOURCE_GUI" for item in persisted["checks"]))

    def test_store_qa_plan_never_exits_as_runtime_pass(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch("all_auto.__main__._load_job", return_value=({"product_id": "p", "submission_id": "s"}, Path(temporary) / "job.json")), \
             patch("all_auto.runtime_qa.build_runtime_qa_report", return_value={
                 "status": "RUNTIME_QA_READY_TO_RUN", "qa_pass": False,
                 "package": {"status": "EXACT_PACKAGE_SHA_AND_MANIFEST_VERIFIED"}}), \
             patch("all_auto.__main__.write_store_report_with_fallback", return_value=Path(temporary) / "qa.json") as report_writer, \
             contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = main(["store", "qa", "--product", "data-contract-auditor",
                         "--package", str(Path(temporary) / "candidate.msix")])
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "RUNTIME_QA_READY_TO_RUN")
        self.assertFalse(result["qa_pass"])
        self.assertFalse(result["store_write_performed"])
        self.assertEqual(report_writer.call_args.args[2][-1], Path(tempfile.gettempdir()))

    def test_read_only_run_reports_unapproved_and_unexecuted_sections(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch("all_auto.__main__._load_job", return_value=({"product_id": "p", "submission_id": "s"}, Path(temporary) / "job.json")), \
             patch("all_auto.__main__.build_store_workflow_report", return_value={
                 "status": "INPUTS_REQUIRED", "missing_or_unverified": [],
                 "created_at_utc": datetime.now(timezone.utc).isoformat(), "run_id": uuid4().hex,
                 "binding": {"product_id": "p", "submission_id": "s"}, "owner_decisions": [],
                 "owner_decision_candidates": [], "shared_store_policy": {}, "owner_decision_batch": []}), \
             patch("all_auto.__main__.write_unique_report", return_value=Path(temporary) / "report.json"), \
             contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = main(["store", "run", "--product", "data-contract-auditor", "--mode", "READ_ONLY",
                         "--out", temporary])
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(len(result["pending_sections"]), 6)
        self.assertEqual(result["not_executed_sections"], result["pending_sections"])
        self.assertEqual(result["unapproved_sections"], result["pending_sections"])

    def test_store_run_reports_write_flag_from_actual_execution(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch("all_auto.__main__.build_store_workflow_report", return_value={
                 "status": "READY_FOR_REVIEW", "missing_or_unverified": [],
                 "created_at_utc": datetime.now(timezone.utc).isoformat(), "run_id": uuid4().hex,
                 "binding": {"product_id": "9PDL4ZWSB45P", "submission_id": "1152921505702212222"},
                 "owner_decisions": []}), \
             patch("all_auto.__main__.write_store_report_with_fallback", return_value=Path(temporary) / "report.json"), \
             patch("all_auto.store_run.run_approved_sections", return_value={
                 "status": "EXECUTED", "actions": [{"section": "properties", "status": "SAVED_AND_RECONCILED"}],
                 "writes_performed": True, "certification_executed": False, "publish_executed": False}), \
             contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = main(["store", "run", "--product", "data-contract-auditor", "--mode", "AUTO",
                         "--package", str(Path(temporary) / "candidate.msix")])
        self.assertEqual(code, 0, stdout.getvalue())
        self.assertTrue(json.loads(stdout.getvalue())["partner_center_writes"])

    def test_run_exit_code_distinguishes_hold_failure_and_reconciliation(self):
        report = {"missing_or_unverified": []}
        acquisition = {"status": "EXPLICIT_LOCAL_PACKAGE"}
        self.assertEqual(_store_run_exit_code(report, {"status": "HOLD", "writes_performed": False}, acquisition), 1)
        self.assertEqual(_store_run_exit_code(report, {"status": "FAILED", "writes_performed": False}, acquisition), 2)
        self.assertEqual(_store_run_exit_code(report, {"status": "RECONCILE_REQUIRED", "writes_performed": True}, acquisition), 2)
        self.assertEqual(_store_run_exit_code(report, {"status": "EXECUTED", "writes_performed": False}, acquisition), 2)
        self.assertEqual(_store_run_exit_code(report, {"status": "PLAN_ONLY", "writes_performed": False}, acquisition), 1)
        self.assertEqual(_store_run_exit_code(report, {"status": "EXECUTED", "writes_performed": False,
                                                       "all_approved_sections_completed": True}, acquisition), 0)
        self.assertEqual(_store_run_exit_code({"missing_or_unverified": [{"key": "other"}],
                                               "status": "READY_FOR_REVIEW"},
                                               {"status": "EXECUTED", "writes_performed": False,
                                                "all_approved_sections_completed": True}, acquisition), 1)


if __name__ == "__main__":
    unittest.main()
