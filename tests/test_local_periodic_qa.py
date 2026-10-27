"""No-network tests for the bounded periodic Local QA worker."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.local_periodic_qa import run_cycle


class LocalPeriodicQATests(unittest.TestCase):
    def paths(self, root):
        return root / "inbox", root / "checker", root / "reports", root / "state"

    def test_overlapping_run_holds_without_touching_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            puller, checker = Mock(), Mock()
            with patch("scripts.local_periodic_qa.LocalRunLock.acquire", return_value=False):
                result = run_cycle(*self.paths(Path(tmp)), puller=puller,
                                   checker_runner=checker)
            self.assertEqual(result["reason"], "LOCAL_QA_WORKER_ALREADY_RUNNING")
            puller.assert_not_called()
            checker.assert_not_called()

    def test_capacity_hold_still_checks_existing_local_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            puller = Mock(return_value={"status": "HOLD_LOCAL_CAPACITY",
                                        "reason": "LOCAL_QA_INBOX_FULL",
                                        "remote_backlog_preserved": True})
            checker = Mock(return_value={"status": "HOLD", "checked": 1,
                                         "executed": 1, "skipped": 0})
            result = run_cycle(*self.paths(root), puller=puller,
                               checker_runner=checker)
            self.assertEqual(result["status"], "HOLD_LOCAL_CAPACITY")
            self.assertEqual(result["hold_class"], "QUEUE_CAPACITY")
            self.assertTrue(result["pull"]["remote_backlog_preserved"])
            checker.assert_called_once()
            self.assertEqual(result["archive_status"],
                             "WAITING_CHECKER_AND_GUI_INSTALL_RECEIPT")

    def test_completed_checker_is_still_not_e2e_or_auto_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_cycle(*self.paths(root),
                puller=Mock(return_value={"status": "OK", "new_packages": 1}),
                checker_runner=Mock(return_value={"status": "HOLD", "checked": 1,
                                                  "executed": 1, "skipped": 0}))
            self.assertEqual(result["reason"], "CHECKER_COMPLETE_GUI_INSTALL_RECEIPT_PENDING")
            self.assertFalse(result["e2e_pass"])
            self.assertEqual(result["submitted_to_store"], 0)
            self.assertTrue((root / "state" / "last-cycle.json").is_file())

    def test_scheduler_uses_cycle_and_rejects_parallel_instances(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" /
                  "register_local_qa_pull.ps1").read_text(encoding="utf-8")
        self.assertIn("scripts.local_periodic_qa", script)
        self.assertIn("-MultipleInstances IgnoreNew", script)
        self.assertIn("-Minutes 15", script)


if __name__ == "__main__":
    unittest.main()
