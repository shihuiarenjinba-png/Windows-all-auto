"""Incremental live review-head projection: immutable source and physical gates stay closed."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
APP_HEAD = "b375fd9ed39ce5ceef635d9df169d7e23f2e2eac"
GAME_HEAD = "4ad61ccc48744e9f696d737c449fe6021cdd5b3f"
APP_SOURCE = "16b6a772952ca0988f2ae2f8b5f4db2e59ec5877"
GAME_SOURCE = "c058cbf7fe38e02d929c67d047d717ff74bd522e"
ARTIFACT_RUN_HEAD = "a1af3448cd2edeae5bd54cbaca486a53fd991944"


def validate(data):
    r = data["revision_review_reconciliation"]
    proof = r["latest_incremental_review_head_recheck"]
    image = r["observations"]["offline-image-inventory-desk"]
    game = r["observations"]["signal-sprint-new-lineage"]
    assert proof["writer"] == "36_WINDOWS_E2E_ONLY"
    assert (proof["app_pr76"]["current_review_head"], proof["game_factory_pr15"]["current_review_head"]) == (APP_HEAD, GAME_HEAD)
    assert (proof["app_pr76"]["ahead"], proof["app_pr76"]["behind"]) == (8, 0)
    assert (proof["game_factory_pr15"]["ahead"], proof["game_factory_pr15"]["behind"]) == (6, 0)
    assert image["current_review_head_sha"] == APP_HEAD
    assert image["immutable_pre_identity_source_sha"] == APP_SOURCE
    assert image["new_revision_source_sha"] is None and image["new_revision_request_id"] is None
    assert image["current_review_revision_promoted"] is False
    assert image["market_fit_gate"] == "MARKET_FIT_HOLD"
    assert (image["score"], image["independent_buyers_completed"]) == (64, 0)
    assert game["current_review_head_sha"] == GAME_HEAD
    assert game["immutable_source_sha"] == GAME_SOURCE
    assert game["run_head_sha"] == ARTIFACT_RUN_HEAD
    assert game["current_review_head_is_run_head"] is False
    assert game["new_artifact_id"] == 13105352227
    assert game["new_lineage_cas_applied"] is False and game["gdk_msixvc_built"] is False
    assert proof["game_factory_pr15"]["old_artifact_sha_conflict"] == "HOLD"
    assert proof["app_batch4"]["github_identity_returned"] == 2
    assert proof["app_batch4"]["physical_local_processed"] == 0
    assert proof["app_batch4"]["local_scheduler_proven"] is False
    assert proof["local_code_sync"]["physical_exact_sha_reuse_scheduler_pass"] is False
    assert data["post_identity_pipeline"]["post_identity_ready_count"] == 3
    assert proof["sale_ready"] is False and proof["real_msix"] is False
    assert proof["github_backlog"] is False and proof["checker"] is False
    assert data["e2e_pass"] is False


class IncrementalLiveReviewHead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_current_review_drift_is_reconciled(self):
        validate(self.data)

    def test_mutated_app_promotion_rejected(self):
        bad = copy.deepcopy(self.data)
        bad["revision_review_reconciliation"]["observations"]["offline-image-inventory-desk"]["current_review_revision_promoted"] = True
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_mutated_game_run_head_rejected(self):
        bad = copy.deepcopy(self.data)
        bad["revision_review_reconciliation"]["observations"]["signal-sprint-new-lineage"]["run_head_sha"] = GAME_HEAD
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_fake_local_or_cas_pass_rejected(self):
        for path, value in [
            (["latest_incremental_review_head_recheck", "app_batch4", "physical_local_processed"], 4),
            (["latest_incremental_review_head_recheck", "local_code_sync", "physical_exact_sha_reuse_scheduler_pass"], True),
            (["observations", "signal-sprint-new-lineage", "new_lineage_cas_applied"], True),
        ]:
            bad = copy.deepcopy(self.data)
            target = bad["revision_review_reconciliation"]
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.assertRaises(AssertionError):
                validate(bad)


if __name__ == "__main__":
    unittest.main()
