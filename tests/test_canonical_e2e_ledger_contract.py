"""Canonical ledger compatibility: the POST Identity bridge must see the live queue.

No GitHub/Partner Center IO, no ledger mutation or CAS.
"""
import json
from pathlib import Path
import unittest
from scripts.reconcile_post_identity import _all_jobs


class CanonicalLedgerContractTests(unittest.TestCase):
    def test_canonical_queue_is_not_the_historical_snapshot(self):
        path = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
        ledger = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("user_id_requests", ledger)
        self.assertIn("registration_router", ledger)
        self.assertIn("post_identity_pipeline", ledger)
        jobs = _all_jobs(ledger)
        self.assertGreaterEqual(len(jobs), 5)
        self.assertEqual(len({job["request_id"] for job in jobs}), len(jobs))
        self.assertTrue(all(job.get("identity_return_target") for job in jobs))
        self.assertFalse(ledger["e2e_pass"])


if __name__ == "__main__":
    unittest.main()
