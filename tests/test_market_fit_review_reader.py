"""Offline regressions for immutable, one-file MARKET_FIT review commits."""
import copy
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.market_fit_github_reader import MarketFitReadHold
from scripts.market_fit_review_reader import (
    _check_review_commit, assess_reviewed_market_fit,
    reconcile_with_reviewed_market_fit,
)

SOURCE = "8b00bc4e90828c4282463826873aa8dfd2eb93f4"
REVIEW = "1" * 40
PATH = "products/focus-session-desk/market-fit.json"
JOB = {
    "product_type": "APP", "slug": "focus-session-desk",
    "request_id": "app-focus-session-desk-8b00bc4e9082",
    "source_repository": "shihuiarenjinba-png/AI-App-Factory",
    "source_branch": "codex/app-cohort-focus-controller-20261028",
    "source_sha": SOURCE, "market_fit_review_commit_sha": REVIEW,
    "identity_return_target": "products/focus-session-desk/store/approved-identity.json",
}


def compare(**changes):
    data = {
        "status": "ahead", "ahead_by": 1, "behind_by": 0,
        "total_commits": 1,
        "base_commit": {"sha": SOURCE},
        "merge_base_commit": {"sha": SOURCE},
        "commits": [{"sha": REVIEW}],
        "files": [{"filename": PATH, "status": "added"}],
    }
    data.update(changes)
    return subprocess.CompletedProcess([], 0, json.dumps(data), "")


def evidence():
    return json.dumps({
        "schema_version": 1, "slug": JOB["slug"],
        "request_id": JOB["request_id"],
        "source_repository": JOB["source_repository"],
        "source_branch": JOB["source_branch"],
        "source_sha": SOURCE, "reviewed": True,
        "status": "MARKET_FIT_PASS", "score": 71,
        "why_pay": "Saves repeated checks",
        "free_alternative_difference": "Batch checks without manual steps",
        "competitor_research": [
            {"competitor": "Manual review", "difference": "Automated local audit"}
        ],
    })


class MarketFitReviewReaderTests(unittest.TestCase):
    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_exact_immutable_compare(self, run):
        run.return_value = compare()
        self.assertEqual(_check_review_commit(JOB),
                         (JOB["source_repository"], PATH, REVIEW))
        self.assertEqual(run.call_args.args[0][-1],
                         f"repos/{JOB['source_repository']}/compare/{SOURCE}...{REVIEW}")

    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_no_review_sha_is_hold_without_api(self, run):
        self.assertEqual(assess_reviewed_market_fit(
            dict(JOB, market_fit_review_commit_sha=None))[0], "MARKET_FIT_HOLD")
        run.assert_not_called()

    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_review_sha_cannot_equal_source(self, run):
        self.assertEqual(assess_reviewed_market_fit(
            dict(JOB, market_fit_review_commit_sha=SOURCE))[0], "MARKET_FIT_HOLD")
        run.assert_not_called()

    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_unrelated_commit_holds(self, run):
        run.return_value = compare(merge_base_commit={"sha": "f" * 40})
        with self.assertRaises(MarketFitReadHold):
            _check_review_commit(JOB)

    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_extra_application_file_holds(self, run):
        data = json.loads(compare().stdout)
        data["files"].append({"filename": "src/main.py", "status": "modified"})
        run.return_value = subprocess.CompletedProcess([], 0, json.dumps(data), "")
        self.assertEqual(assess_reviewed_market_fit(JOB)[0], "MARKET_FIT_HOLD")

    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_two_commits_holds(self, run):
        run.return_value = compare(ahead_by=2, total_commits=2)
        with self.assertRaises(MarketFitReadHold):
            _check_review_commit(JOB)

    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_wrong_commit_sha_holds(self, run):
        run.return_value = compare(commits=[{"sha": "f" * 40}])
        with self.assertRaises(MarketFitReadHold):
            _check_review_commit(JOB)

    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_auth_failure_holds(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "HTTP 403")
        self.assertEqual(assess_reviewed_market_fit(JOB)[1],
                         "HOLD_MARKET_FIT_REVIEW_COMPARE_UNAVAILABLE")

    @patch("scripts.market_fit_review_reader.read_factory_market_fit")
    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_valid_review_passes_only_market_fit(self, run, read):
        run.return_value = compare()
        read.return_value = evidence()
        self.assertEqual(assess_reviewed_market_fit(JOB)[0], "MARKET_FIT_PASS")
        read.assert_called_once_with(JOB["source_repository"], PATH, REVIEW)

    @patch("scripts.market_fit_review_reader.read_factory_market_fit")
    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_missing_file_holds(self, run, read):
        run.return_value = compare()
        read.return_value = None
        self.assertEqual(assess_reviewed_market_fit(JOB)[1],
                         "HOLD_MARKET_FIT_REVIEW_FILE_MISSING")

    @patch("scripts.market_fit_review_reader.read_factory_market_fit")
    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_wrong_source_binding_holds(self, run, read):
        run.return_value = compare()
        payload = json.loads(evidence())
        payload["source_sha"] = "f" * 40
        read.return_value = json.dumps(payload)
        self.assertEqual(assess_reviewed_market_fit(JOB)[1],
                         "HOLD_MARKET_FIT_SOURCE_CONFLICT")

    @patch("scripts.reconcile_post_identity.reconcile_approved_return")
    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_market_hold_does_not_undo_valid_identity_post(self, run, reconcile):
        ledger = {
            "rotation_cohorts": {
                "app_jobs": [dict(JOB, market_fit_review_commit_sha=None)],
                "game_jobs": [], "three_d_jobs": [],
            },
            "post_identity_pipeline": {
                "products": [{"request_id": JOB["request_id"]}],
            },
        }
        def fake_reconcile(source, slug, **kwargs):
            self.assertIsNone(kwargs["fetch_market_fit"](
                JOB["source_repository"], PATH, SOURCE))
            updated = copy.deepcopy(source)
            updated["rotation_cohorts"]["app_jobs"][0]["status"] = "POST_IDENTITY_READY"
            updated["rotation_cohorts"]["app_jobs"][0]["market_fit_evidence_verified"] = True
            updated["post_identity_pipeline"]["products"][0]["market_fit_evidence_verified"] = True
            return updated, "POST_IDENTITY_READY"
        reconcile.side_effect = fake_reconcile
        updated, transition = reconcile_with_reviewed_market_fit(
            ledger, JOB["slug"], fetch_branch_head=lambda *a: None,
            fetch_approved_file=lambda *a: None,
            verify_source_ancestry=lambda *a: False,
        )
        self.assertEqual(transition, "POST_IDENTITY_READY")
        self.assertIs(updated["rotation_cohorts"]["app_jobs"][0]["market_fit_evidence_verified"], False)
        self.assertIs(updated["post_identity_pipeline"]["products"][0]["market_fit_evidence_verified"], False)
        self.assertEqual(
            updated["rotation_cohorts"]["app_jobs"][0]["market_fit_gate"],
            "MARKET_FIT_HOLD",
        )
        self.assertEqual(
            updated["post_identity_pipeline"]["products"][0]["market_fit_reason"],
            "HOLD_MARKET_FIT_REVIEW_REF_INVALID",
        )
        run.assert_not_called()

    @patch("scripts.market_fit_review_reader.subprocess.run")
    def test_game_not_applicable(self, run):
        self.assertEqual(assess_reviewed_market_fit(
            dict(JOB, product_type="GAME")), ("NOT_APPLICABLE", "NON_APP"))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
