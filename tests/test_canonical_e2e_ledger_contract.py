"""Canonical ledger compatibility for read-only POST Identity reconciliation.

This is an offline structural regression, not Store/Identity or package QA.
"""
import json
from pathlib import Path
import unittest
from scripts.reconcile_post_identity import _all_jobs


def canonical():
    path = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
    return json.loads(path.read_text(encoding="utf-8"))


class CanonicalLedgerContractTests(unittest.TestCase):
    def test_canonical_queue_is_not_the_historical_snapshot(self):
        ledger = canonical()
        self.assertIn("user_id_requests", ledger)
        self.assertIn("registration_router", ledger)
        self.assertIn("post_identity_pipeline", ledger)
        jobs = _all_jobs(ledger)
        self.assertGreaterEqual(len(jobs), 5)
        self.assertEqual(len({job["request_id"] for job in jobs}), len(jobs))
        self.assertTrue(all(job.get("identity_return_target") for job in jobs))
        self.assertFalse(ledger["e2e_pass"])

    def test_post_identity_records_retain_exact_store_binding(self):
        ledger = canonical()
        pipeline = ledger["post_identity_pipeline"]["products"]
        for job in _all_jobs(ledger):
            matching = [entry for entry in pipeline
                        if entry.get("request_id") == job["request_id"]]
            self.assertEqual(len(matching), 1, job["slug"])
            entry = matching[0]
            self.assertEqual(entry["product"], job["display_name"])
            self.assertEqual(entry["lane"], job["product_type"])
            self.assertEqual(entry["source_sha"], job["source_sha"])
            self.assertEqual(entry["identity_return_target"],
                             job["identity_return_target"])
            if job["status"] == "POST_IDENTITY_READY":
                self.assertEqual(entry["state"], "POST_IDENTITY_READY")
                for field in ("identity_return_commit_sha", "identity_store_id",
                              "identity_pfn"):
                    self.assertEqual(entry.get(field), job.get(field),
                                     (job["slug"], field))
                self.assertEqual(job["package_version_gate"], "HOLD")
            else:
                self.assertNotEqual(entry["state"], "POST_IDENTITY_READY")


if __name__ == "__main__":
    unittest.main()
