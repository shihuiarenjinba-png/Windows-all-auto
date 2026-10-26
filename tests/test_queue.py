import copy
import tempfile
import unittest
from pathlib import Path

from all_auto.queue import QueueLedger, fingerprint


class DurableQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "jobs.sqlite3"
        self.p = {
            "id": "sample",
            "approved_identity": {"store_id": "9REALTEST", "version": "1.0.0.0"},
            "source_sha": "a" * 40,
            "submission_kind": "update",
        }
        self.r = {"status": "READY_FOR_WINDOWS_QA", "package_sha256": "b" * 64, "findings": []}

    def test_01_fingerprint_is_deterministic(self):
        self.assertEqual(fingerprint(self.p, self.r), fingerprint(copy.deepcopy(self.p), dict(self.r)))

    def test_02_enqueue_is_idempotent(self):
        with QueueLedger(self.db) as ledger:
            first = ledger.add_product(self.p, self.r)
            second = ledger.add_product(self.p, self.r)
            self.assertEqual(first["job_key"], second["job_key"])
            self.assertEqual(len(ledger.rows()), 1)

    def test_03_operator_pending_does_not_claim_uploaded(self):
        with QueueLedger(self.db) as ledger:
            job = ledger.add_product(self.p, self.r)
            ledger.require_operator(job["job_key"])
            self.assertEqual(ledger.rows()[0]["status"], "PENDING_OPERATOR")

    def test_04_cannot_reapprove_same_job(self):
        with QueueLedger(self.db) as ledger:
            job = ledger.add_product(self.p, self.r)
            ledger.require_operator(job["job_key"])
            with self.assertRaises(ValueError):
                ledger.require_operator(job["job_key"])

    def test_05_unknown_never_self_retries(self):
        with QueueLedger(self.db) as ledger:
            job = ledger.add_product(self.p, self.r)
            ledger.require_operator(job["job_key"])
            ledger.record_ambiguous_result(job["job_key"])
            self.assertEqual(ledger.add_product(self.p, self.r)["status"], "UNKNOWN")
            with self.assertRaises(ValueError):
                ledger.require_operator(job["job_key"])

    def test_06_unknown_blocks_new_version_same_store_id(self):
        other = copy.deepcopy(self.r)
        other["package_sha256"] = "c" * 64
        with QueueLedger(self.db) as ledger:
            old = ledger.add_product(self.p, self.r)
            ledger.require_operator(old["job_key"])
            ledger.record_ambiguous_result(old["job_key"])
            newer = ledger.add_product(self.p, other)
            self.assertEqual(newer["status"], "HOLD")
            self.assertEqual(newer["reason"], "PRIOR_STORE_OUTCOME_UNCONFIRMED")

    def test_11_ready_same_store_different_package_is_held(self):
        newer = copy.deepcopy(self.r)
        newer["package_sha256"] = "c" * 64
        with QueueLedger(self.db) as ledger:
            first = ledger.add_product(self.p, self.r)
            second = ledger.add_product(self.p, newer)
            self.assertEqual(first["status"], "READY_FOR_WINDOWS_QA")
            self.assertEqual(second["status"], "HOLD")
            self.assertEqual(second["reason"], "PRIOR_STORE_OUTCOME_UNCONFIRMED")
            with self.assertRaises(ValueError):
                ledger.require_operator(second["job_key"])

    def test_07_sqlite_reopens_with_unknown_state(self):
        with QueueLedger(self.db) as ledger:
            job = ledger.add_product(self.p, self.r)
            ledger.require_operator(job["job_key"])
            ledger.record_ambiguous_result(job["job_key"])
        with QueueLedger(self.db) as reopened:
            self.assertEqual(reopened.rows()[0]["status"], "UNKNOWN")

    def test_08_hold_cannot_advance_to_operator(self):
        hold = {"status": "HOLD", "package_sha256": "b" * 64, "findings": ["SECURITY_REQUIRED"]}
        with QueueLedger(self.db) as ledger:
            j = ledger.add_product(self.p, hold)
            with self.assertRaises(ValueError):
                ledger.require_operator(j["job_key"])

    def test_09_blocked_cannot_advance_to_operator(self):
        blocked = {"status": "BLOCKED", "package_sha256": "b" * 64, "findings": ["IDENTITY_MISMATCH"]}
        with QueueLedger(self.db) as ledger:
            j = ledger.add_product(self.p, blocked)
            with self.assertRaises(ValueError):
                ledger.require_operator(j["job_key"])

    def test_10_event_ledger_records_every_transition(self):
        with QueueLedger(self.db) as ledger:
            j = ledger.add_product(self.p, self.r)
            ledger.require_operator(j["job_key"])
            ledger.record_ambiguous_result(j["job_key"])
            count = ledger.db.execute("SELECT COUNT(*) FROM events WHERE job_key=?", (j["job_key"],)).fetchone()[0]
            self.assertEqual(count, 3)


if __name__ == "__main__":
    unittest.main()
