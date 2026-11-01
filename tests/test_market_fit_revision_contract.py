"""Factory-aligned immutable market-fit read-only contract regressions."""
import base64
import copy
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
PATH = "docs/market/offline-image-inventory-desk.market-fit.json"
JOB = {
    "product_type": "APP", "slug": "offline-image-inventory-desk",
    "source_repository": REPO,
    "source_branch": "codex/app-cohort-image-inventory-20261028",
    "source_sha": SOURCE, "request_id": "app-offline-image-inventory-desk-16b6a772952c",
    "market_fit_review_sha": REVIEW,
}
SCORE_PARTS = {
    "problem_severity": (16, 20), "differentiation": (16, 20),
    "willingness_to_pay": (16, 20), "usability": (12, 15),
    "trust_privacy": (8, 10), "discoverability": (8, 10),
    "implementation_risk": (4, 5),
}
EVIDENCE = {
    "schema_version": "app5-market-fit-v1", "slug": JOB["slug"],
    "repo": REPO, "source_branch": JOB["source_branch"],
    "baseline_sha": SOURCE, "request_id": JOB["request_id"],
    "decision": "MARKET_FIT_PASS", "commercial_msix_allowed": True,
    "feature_expansion_allowed": True,
    "review_status": "APPROVED",
    "scoring": {**{k: {"score": a, "max": b} for k, (a, b) in SCORE_PARTS.items()},
                "total": 80, "max": 100},
    "why_pay_statement": "Saves verified manual Store listing review rework",
    "free_alternatives": ["Free A", "Free B", "Free C"],
    "direct_competitors": [{"name": "Comp A"}, {"name": "Comp B"}, {"name": "Comp C"}],
    "paid_price_range": "USD 10 to 50 one-time",
    "buyer_persona": "Independent Microsoft Store developer",
    "store_search_keywords": ["offline image", "store preflight"],
    "price_hypothesis": {"one_time_jpy": 900},
    "common_review_complaints": [{"complaint": "Manual review errors"}],
    "free_alternative_differences": [
        {"alternative": "Free A", "difference": "Verified workflow difference A"},
        {"alternative": "Free B", "difference": "Verified workflow difference B"},
    ],
    "go_criteria": {
        "one_sentence_why_pay": True,
        "two_distinctions_from_free_alternatives": True,
        "addresses_review_complaint": True,
        "feasible_windows_local": True,
        "no_saas_dependency": True,
        "minimum_score_70": True,
    },
}


def assess(data, job=None, ancestry=True):
    return assess_market_fit(
        JOB if job is None else job,
        lambda repo, path, sha: json.dumps(data),
        lambda repo, source, review, slug: ancestry,
    )


def gh_response(payload, *, status=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=status,
                                       stdout=json.dumps(payload), stderr=stderr)


class MarketFitRevisionContractTests(unittest.TestCase):
    def test_80_and_all_go_is_only_market_pass(self):
        self.assertEqual(assess(EVIDENCE), ("MARKET_FIT_PASS", "FACTORY_REVIEW_SHA_BOUND_SCORE_80_ALL_GO"))

    def test_64_70_and_79_are_hold_not_commercial(self):
        for score in (64, 70, 79):
            data = copy.deepcopy(EVIDENCE)
            data["scoring"]["differentiation"]["score"] -= 80 - score
            data["scoring"]["total"] = score
            # 64/70/79 are valid component totals and still HOLD.
            self.assertEqual(assess(data)[0], "MARKET_FIT_HOLD")
        data = copy.deepcopy(EVIDENCE)
        data["scoring"]["total"] = True
        self.assertEqual(assess(data)[0], "MARKET_FIT_HOLD")

    def test_review_is_immutable_separate_commit(self):
        for changed in ({"market_fit_review_sha": SOURCE},
                        {"market_fit_review_sha": None},
                        {"market_fit_review_sha": "main"}):
            self.assertEqual(assess(EVIDENCE, {**JOB, **changed})[0], "MARKET_FIT_HOLD")

    def test_source_binding_conflicts(self):
        for field, value in (("request_id", "wrong"), ("baseline_sha", REVIEW),
                             ("slug", "other"), ("source_branch", "main")):
            self.assertEqual(assess({**EVIDENCE, field: value})[0], "MARKET_FIT_HOLD")

    def test_unreviewed_candidate_never_passes(self):
        for change in ({"review_status": "PENDING"}, {"decision": "MARKET_FIT_HOLD"},
                       {"commercial_msix_allowed": False}):
            self.assertEqual(assess({**EVIDENCE, **change})[0], "MARKET_FIT_HOLD")

    def test_missing_value_and_free_alternatives(self):
        for change in ({"why_pay_statement": ""}, {"free_alternative_differences": []},
                       {"free_alternative_differences": [EVIDENCE["free_alternative_differences"][0]]},
                       {"direct_competitors": []}):
            self.assertEqual(assess({**EVIDENCE, **change})[0], "MARKET_FIT_HOLD")

    def test_all_go_required(self):
        for key in EVIDENCE["go_criteria"]:
            e = {**EVIDENCE, "go_criteria": {**EVIDENCE["go_criteria"], key: False}}
            self.assertEqual(assess(e)[0], "MARKET_FIT_HOLD")

    def test_ancestry_fail_closed(self):
        self.assertEqual(assess(EVIDENCE, ancestry=False)[0], "MARKET_FIT_HOLD")

    def test_missing_duplicate_key_and_forged_total_hold(self):
        self.assertEqual(assess_market_fit(JOB, lambda *a: None, lambda *a: True)[0],
                         "MARKET_FIT_HOLD")
        raw = json.dumps(EVIDENCE).replace('"decision": "MARKET_FIT_PASS"',
                                           '"decision": "MARKET_FIT_PASS", "decision": "MARKET_FIT_PASS"')
        self.assertEqual(assess_market_fit(JOB, lambda *a: raw, lambda *a: True),
                         ("MARKET_FIT_HOLD", "HOLD_MARKET_FIT_DUPLICATE_KEY"))
        bad = copy.deepcopy(EVIDENCE)
        bad["scoring"]["willingness_to_pay"]["score"] = 1
        self.assertEqual(assess(bad)[1], "HOLD_MARKET_FIT_SCORE_SUM_MISMATCH")

    def test_legacy_factory_64_document_is_hold(self):
        old = {"schema_version": "app5-market-fit-v1", "slug": JOB["slug"],
               "repo": REPO, "baseline_sha": SOURCE,
               "decision": "MARKET_FIT_HOLD", "commercial_msix_allowed": False,
               "scoring": {"total": 64, "max": 100}}
        self.assertEqual(assess(old)[0], "MARKET_FIT_HOLD")

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_reader_uses_review_sha_not_source_or_branch(self, run):
        raw = json.dumps(EVIDENCE).encode("utf-8")
        run.return_value = gh_response({
            "type": "file", "path": PATH, "encoding": "base64",
            "size": len(raw), "content": base64.b64encode(raw).decode(),
        })
        self.assertEqual(json.loads(read_factory_market_fit(REPO, PATH, REVIEW))["scoring"]["total"], 80)
        self.assertEqual(run.call_args.args[0][-1],
                         f"repos/{REPO}/contents/{PATH}?ref={REVIEW}")

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_ancestry_exact_commit_refs(self, run):
        run.return_value = gh_response({
            "status": "ahead", "behind_by": 0,
            "base_commit": {"sha": SOURCE}, "head_commit": {"sha": REVIEW},
            "files": [{"filename": "docs/market/offline-image-inventory-desk.market-fit.json"}],
        })
        self.assertTrue(verify_review_ancestry(REPO, SOURCE, REVIEW, JOB["slug"]))
        self.assertEqual(run.call_args.args[0][-1],
                         f"repos/{REPO}/compare/{SOURCE}...{REVIEW}")
        run.return_value = gh_response({
            "status": "diverged", "behind_by": 2,
            "base_commit": {"sha": SOURCE}, "head_commit": {"sha": REVIEW},
        })
        self.assertFalse(verify_review_ancestry(REPO, SOURCE, REVIEW, JOB["slug"]))

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_auth_failure_and_unsafe_refs_fail_closed(self, run):
        run.return_value = gh_response({}, status=1, stderr="HTTP 403")
        self.assertEqual(assess_factory_market_fit(JOB)[0], "MARKET_FIT_HOLD")
        with self.assertRaises(MarketFitReadHold):
            read_factory_market_fit(REPO, PATH, "main")
        with self.assertRaises(MarketFitReadHold):
            verify_review_ancestry(REPO, SOURCE, SOURCE, JOB["slug"])


    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_product_code_changed_after_review_holds(self, run):
        run.return_value = gh_response({
            "status": "ahead", "behind_by": 0,
            "base_commit": {"sha": SOURCE}, "head_commit": {"sha": REVIEW},
            "files": [{"filename": "products/offline-image-inventory-desk/main.py"}],
        })
        self.assertFalse(verify_review_ancestry(REPO, SOURCE, REVIEW, JOB["slug"]))
        run.return_value = gh_response({
            "status": "ahead", "behind_by": 0,
            "base_commit": {"sha": SOURCE}, "head_commit": {"sha": REVIEW},
            "files": [{"filename": "products/offline-image-inventory-desk/store/approved-identity.json"}],
        })
        self.assertTrue(verify_review_ancestry(REPO, SOURCE, REVIEW, JOB["slug"]))

    def test_factory_rationale_minimums_hold(self):
        for change in ({"feature_expansion_allowed": False},
                       {"direct_competitors": [{"name": "A"}]},
                       {"free_alternatives": ["A", "B"]},
                       {"why_pay_statement": "NOT PROVEN as paid"},
                       {"paid_price_range": ""}, {"buyer_persona": ""},
                       {"store_search_keywords": []}, {"price_hypothesis": None}):
            self.assertEqual(assess({**EVIDENCE, **change})[0], "MARKET_FIT_HOLD")

    def test_game_not_applicable(self):
        self.assertEqual(assess_market_fit({"product_type": "GAME"}), ("NOT_APPLICABLE", "NON_APP"))


if __name__ == "__main__":
    unittest.main()
