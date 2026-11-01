"""Read-only revision-aware market fit contract: no package or Identity side effects."""
import base64
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.market_fit_gate import assess_market_fit
from scripts.market_fit_github_reader import (
    assess_factory_market_fit, read_factory_market_fit, verify_review_ancestry,
    MarketFitReadHold,
)

SOURCE = "16b6a772952ca0988f2ae2f8b5f4db2e59ec5877"
REVIEW = "ec3b867e4c18ddf44a591ebbb9b1017ada1f53be"
REPO = "shihuiarenjinba-png/AI-App-Factory"
PATH = "products/offline-image-inventory-desk/market-fit.json"
JOB = {
    "product_type": "APP", "slug": "offline-image-inventory-desk",
    "source_repository": REPO,
    "source_branch": "codex/app-cohort-image-inventory-20261028",
    "source_sha": SOURCE, "request_id": "app-offline-image-inventory-desk-16b6a772952c",
    "market_fit_review_sha": REVIEW,
}
EVIDENCE = {
    "schema_version": 1, "slug": JOB["slug"], "source_repository": REPO,
    "source_branch": JOB["source_branch"], "source_sha": SOURCE,
    "request_id": JOB["request_id"], "reviewed": True,
    "review_status": "APPROVED", "status": "MARKET_FIT_PASS",
    "score": 80, "why_pay": "Saves Store listing review rework",
    "free_alternative_differences": [
        {"alternative": "Free A", "difference": "Verified workflow difference A"},
        {"alternative": "Free B", "difference": "Verified workflow difference B"},
    ],
    "competitor_research": [
        {"competitor": "Comp A", "difference": "Reproducible user task gap"}
    ],
    "go_criteria": {
        "one_sentence_why_pay": True,
        "two_distinctions_from_free_alternatives": True,
        "addresses_review_complaint": True,
        "feasible_windows_local": True,
        "no_saas_dependency": True,
    },
}


def assess(data, job=None, ancestry=True):
    return assess_market_fit(
        JOB if job is None else job,
        lambda repo, path, sha: json.dumps(data),
        lambda repo, source, review: ancestry,
    )


def gh_response(payload, *, status=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=status,
                                       stdout=json.dumps(payload), stderr=stderr)


class MarketFitRevisionContractTests(unittest.TestCase):
    def test_80_and_all_go_is_only_market_pass(self):
        self.assertEqual(assess(EVIDENCE), ("MARKET_FIT_PASS", "FACTORY_REVIEW_SHA_BOUND_SCORE_80_ALL_GO"))

    def test_70_and_79_are_hold_not_commercial(self):
        for score in (64, 70, 79):
            self.assertEqual(assess({**EVIDENCE, "score": score})[0], "MARKET_FIT_HOLD")
        self.assertEqual(assess({**EVIDENCE, "score": True})[0], "MARKET_FIT_HOLD")

    def test_review_is_immutable_separate_commit(self):
        for changed in ({"market_fit_review_sha": SOURCE},
                        {"market_fit_review_sha": None},
                        {"market_fit_review_sha": "main"}):
            self.assertEqual(assess(EVIDENCE, {**JOB, **changed})[0], "MARKET_FIT_HOLD")

    def test_source_binding_conflicts(self):
        for field, value in (("request_id", "wrong"), ("source_sha", REVIEW),
                             ("slug", "other"), ("source_branch", "main")):
            self.assertEqual(assess({**EVIDENCE, field: value})[0], "MARKET_FIT_HOLD")

    def test_unreviewed_candidate_never_passes(self):
        for change in ({"reviewed": False}, {"review_status": "PENDING"},
                       {"status": "MARKET_FIT_HOLD"}):
            self.assertEqual(assess({**EVIDENCE, **change})[0], "MARKET_FIT_HOLD")

    def test_missing_value_and_free_alternatives(self):
        for change in ({"why_pay": ""}, {"free_alternative_differences": []},
                       {"free_alternative_differences": [EVIDENCE["free_alternative_differences"][0]]},
                       {"competitor_research": []}):
            self.assertEqual(assess({**EVIDENCE, **change})[0], "MARKET_FIT_HOLD")

    def test_all_go_required(self):
        for key in EVIDENCE["go_criteria"]:
            e = {**EVIDENCE, "go_criteria": {**EVIDENCE["go_criteria"], key: False}}
            self.assertEqual(assess(e)[0], "MARKET_FIT_HOLD")

    def test_ancestry_fail_closed(self):
        self.assertEqual(assess(EVIDENCE, ancestry=False)[0], "MARKET_FIT_HOLD")

    def test_missing_or_duplicate_key_fail_closed(self):
        self.assertEqual(assess_market_fit(JOB, lambda *a: None, lambda *a: True)[0],
                         "MARKET_FIT_HOLD")
        raw = json.dumps(EVIDENCE).replace('"score": 80', '"score": 80, "score": 99')
        self.assertEqual(assess_market_fit(JOB, lambda *a: raw, lambda *a: True),
                         ("MARKET_FIT_HOLD", "HOLD_MARKET_FIT_DUPLICATE_KEY"))

    def test_real_factory_legacy_document_not_a_pass(self):
        # Existing Factory docs/market/*.json is not the promoted
        # products/<slug>/market-fit.json evidence at a pinned review commit.
        self.assertEqual(assess_market_fit(JOB, lambda *a: None, lambda *a: True)[0],
                         "MARKET_FIT_HOLD")

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_reader_uses_review_sha_not_source_or_branch(self, run):
        raw = json.dumps(EVIDENCE).encode("utf-8")
        run.return_value = gh_response({
            "type": "file", "path": PATH, "encoding": "base64",
            "size": len(raw), "content": base64.b64encode(raw).decode(),
        })
        self.assertEqual(json.loads(read_factory_market_fit(REPO, PATH, REVIEW))["score"], 80)
        self.assertEqual(run.call_args.args[0][-1],
                         f"repos/{REPO}/contents/{PATH}?ref={REVIEW}")

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_ancestry_exact_commit_refs(self, run):
        run.return_value = gh_response({
            "status": "ahead", "behind_by": 0,
            "base_commit": {"sha": SOURCE}, "head_commit": {"sha": REVIEW},
        })
        self.assertTrue(verify_review_ancestry(REPO, SOURCE, REVIEW))
        self.assertEqual(run.call_args.args[0][-1],
                         f"repos/{REPO}/compare/{SOURCE}...{REVIEW}")
        run.return_value = gh_response({
            "status": "diverged", "behind_by": 2,
            "base_commit": {"sha": SOURCE}, "head_commit": {"sha": REVIEW},
        })
        self.assertFalse(verify_review_ancestry(REPO, SOURCE, REVIEW))

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_auth_failure_and_unsafe_refs_fail_closed(self, run):
        run.return_value = gh_response({}, status=1, stderr="HTTP 403")
        self.assertEqual(assess_factory_market_fit(JOB)[0], "MARKET_FIT_HOLD")
        with self.assertRaises(MarketFitReadHold):
            read_factory_market_fit(REPO, PATH, "main")
        with self.assertRaises(MarketFitReadHold):
            verify_review_ancestry(REPO, SOURCE, SOURCE)

    def test_game_not_applicable(self):
        self.assertEqual(assess_market_fit({"product_type": "GAME"}), ("NOT_APPLICABLE", "NON_APP"))


if __name__ == "__main__":
    unittest.main()
