"""Pinned central-branch integration preflight; never a local schedule/UI proof."""
import json
import os
from pathlib import Path
import unittest

from scripts import local_identity_batch as batch

EXPECTED_CENTRAL_HEAD = "0fe4dc510b37b0574f96d13bc95ade6ef1635032"
EXPECTED = [
    (1, "focus-session-desk", "app-focus-session-desk-8b00bc4e9082", "8b00bc4e90828c4282463826873aa8dfd2eb93f4", 12807496604, "04b2d7e4eae215855217285f07f8835ffe3cf60dc5aab24ede141d28f563416d"),
    (2, "file-integrity-ledger", "app-file-integrity-ledger-d1108d12f7d1", "d1108d12f7d1697af30400f97c7db39cba5e6791", 12826068537, "9100bbcfba20ed2768e5d2dffcb39c987466377d26a34af1e03cc166071e02ca"),
    (3, "offline-text-diff-desk", "app-offline-text-diff-desk-a7d372800898", "a7d37280089893a9ea4b9ac3336020a920e73e0c", 12815845218, "1a0e4f61dfab52e2cac7317bc28bb4ff34b6aa477974e0430ff360d7e2b4381e"),
    (4, "offline-image-inventory-desk", "app-offline-image-inventory-desk-16b6a772952c", "16b6a772952ca0988f2ae2f8b5f4db2e59ec5877", 12817339804, "0e023bcd74f6035a2a3e1cf4cd785f83033c69785723a5c01f7f69d2c5d7b980"),
]


@unittest.skipUnless(os.environ.get("CENTRAL_LEDGER_PATH"), "pinned central ledger not supplied")
class LiveCentralPreflight(unittest.TestCase):
    def test_exact_four_app_jobs_from_pinned_central_commit(self):
        ledger = json.loads(Path(os.environ["CENTRAL_LEDGER_PATH"]).read_text(encoding="utf-8"))
        self.assertEqual(ledger["multi_product_partner_center_batch_4"]["cloud_preflight_discovered_count"], 4)
        spec = {
            "schema_version": 1, "batch_id": "ci-cloud-preflight-only",
            "trigger_origin": batch.TRIGGER_ORIGIN, "automation_id": batch.AUTOMATION_ID,
            "dispatch_origin": batch.DISPATCH_ORIGIN,
            "execution_origin": "MANUAL_WINDOWS_TERMINAL",
            "central_repository": batch.CENTRAL_REPOSITORY,
            "central_branch": batch.CENTRAL_BRANCH,
            "central_head_sha": EXPECTED_CENTRAL_HEAD,
            "scheduled_at": "2026-10-29T00:36:00Z",
            "products": [{
                "batch_index": i, "slug": slug, "request_id": rid,
                "source_sha": sha, "artifact_id": aid,
                "expected_exe_sha256": exe,
                "identity_return_target": f"products/{slug}/store/approved-identity.json",
            } for i, slug, rid, sha, aid, exe in EXPECTED],
        }
        state = batch.discover(ledger, spec)
        self.assertEqual(state["discovered_count"], 4)
        self.assertEqual([x["slug"] for x in state["products"]], [x[1] for x in EXPECTED])
        self.assertEqual(len({x["queue_job_digest"] for x in state["products"]}), 4)
        self.assertFalse(state["execution_trigger_proven"])
        self.assertEqual(state["processed_count"], 0)
        self.assertEqual(state["store_submission"], 0)


if __name__ == "__main__":
    unittest.main()
