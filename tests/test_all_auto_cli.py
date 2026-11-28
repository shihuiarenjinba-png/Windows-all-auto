from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from all_auto.__main__ import main


class StoreCliTests(unittest.TestCase):
    def test_store_run_reports_write_flag_from_actual_execution(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch("all_auto.store_workflow.build_store_workflow_report", return_value={
                 "status": "READY_FOR_REVIEW", "missing_or_unverified": []}), \
             patch("all_auto.store_workflow.write_unique_report", return_value=Path(temporary) / "report.json"), \
             patch("all_auto.store_run.run_approved_sections", return_value={
                 "status": "EXECUTED", "actions": [{"section": "properties", "status": "SAVED_AND_RECONCILED"}],
                 "writes_performed": True, "certification_executed": False, "publish_executed": False}), \
             contextlib.redirect_stdout(io.StringIO()) as stdout:
            code = main(["store", "run", "--product", "data-contract-auditor", "--mode", "AUTO",
                         "--package", str(Path(temporary) / "candidate.msix")])
        self.assertIn(code, {0, 1})
        self.assertTrue(json.loads(stdout.getvalue())["partner_center_writes"])


if __name__ == "__main__":
    unittest.main()
