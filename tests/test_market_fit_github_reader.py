"""Offline regressions for authenticated immutable Factory market-fit reads."""
from __future__ import annotations

import base64
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.market_fit_github_reader import (
    MarketFitReadHold, assess_factory_market_fit, read_factory_market_fit,
)

REPO = "shihuiarenjinba-png/AI-App-Factory"
PATH = "products/focus-session-desk/market-fit.json"
SHA = "8b00bc4e90828c4282463826873aa8dfd2eb93f4"
JOB = {
    "product_type": "APP", "slug": "focus-session-desk",
    "request_id": "app-focus-session-desk-8b00bc4e9082",
    "source_repository": REPO, "source_branch": "codex/example",
    "source_sha": SHA,
}


def response(payload: str, *, path: str = PATH, size=None):
    raw = payload.encode("utf-8")
    return subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=json.dumps({
            "type": "file", "path": path, "encoding": "base64",
            "size": len(raw) if size is None else size,
            "content": base64.b64encode(raw).decode("ascii"),
        }), stderr="",
    )


class MarketFitGithubReaderTests(unittest.TestCase):
    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_exact_sha_authenticated_endpoint(self, run):
        run.return_value = response('{"ok":true}')
        self.assertEqual(read_factory_market_fit(REPO, PATH, SHA), '{"ok":true}')
        command = run.call_args.args[0]
        self.assertEqual(command, [
            "gh", "api", "--method", "GET",
            f"repos/{REPO}/contents/{PATH}?ref={SHA}",
        ])
        self.assertNotIn("codex/example", " ".join(command))

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_missing_evidence_404_only(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="gh: HTTP 404: Not Found"
        )
        self.assertIsNone(read_factory_market_fit(REPO, PATH, SHA))

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_auth_error_not_confused_with_missing_file(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="gh: HTTP 401"
        )
        with self.assertRaisesRegex(MarketFitReadHold, "HOLD_MARKET_FIT_GITHUB_READ"):
            read_factory_market_fit(REPO, PATH, SHA)

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_wrong_path_response_holds(self, run):
        run.return_value = response("{}", path="products/other/market-fit.json")
        with self.assertRaisesRegex(MarketFitReadHold, "HOLD_MARKET_FIT_GITHUB_CONTENT"):
            read_factory_market_fit(REPO, PATH, SHA)

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_wrong_size_holds(self, run):
        run.return_value = response("{}", size=900)
        with self.assertRaisesRegex(MarketFitReadHold, "HOLD_MARKET_FIT_GITHUB_CONTENT"):
            read_factory_market_fit(REPO, PATH, SHA)

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_bad_base64_holds(self, run):
        item = json.loads(response("{}").stdout)
        item["content"] = "***"
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(item), stderr=""
        )
        with self.assertRaisesRegex(MarketFitReadHold, "HOLD_MARKET_FIT_GITHUB_CONTENT"):
            read_factory_market_fit(REPO, PATH, SHA)

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_wrong_source_ref_never_calls_gh(self, run):
        for sha in ("main", SHA.upper(), "../" + SHA):
            with self.assertRaisesRegex(MarketFitReadHold, "HOLD_MARKET_FIT_UNSAFE_SOURCE_REF"):
                read_factory_market_fit(REPO, PATH, sha)
        run.assert_not_called()

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_cross_product_path_never_calls_gh(self, run):
        for path in ("../market-fit.json", "products/other/approved-identity.json"):
            with self.assertRaises(MarketFitReadHold):
                read_factory_market_fit(REPO, path, SHA)
        run.assert_not_called()

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_unauthorized_repo_never_calls_gh(self, run):
        with self.assertRaises(MarketFitReadHold):
            read_factory_market_fit("attacker/repo", PATH, SHA)
        run.assert_not_called()

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_missing_factory_evidence_classifies_hold(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="HTTP 404"
        )
        self.assertEqual(assess_factory_market_fit(JOB),
                         ("MARKET_FIT_HOLD", "HOLD_MARKET_FIT_FACTORY_EVIDENCE_MISSING"))

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_auth_failure_classifies_hold(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="HTTP 403"
        )
        self.assertEqual(assess_factory_market_fit(JOB),
                         ("MARKET_FIT_HOLD", "HOLD_MARKET_FIT_GITHUB_READ"))

    @patch("scripts.market_fit_github_reader.subprocess.run")
    def test_valid_reviewed_evidence_passes_market_gate_only(self, run):
        evidence = {
            "schema_version": 1, "slug": JOB["slug"],
            "request_id": JOB["request_id"],
            "source_repository": REPO, "source_branch": JOB["source_branch"],
            "source_sha": SHA, "reviewed": True, "status": "MARKET_FIT_PASS",
            "score": 70, "why_pay": "Saves repetitive work",
            "free_alternative_difference": "Offline batch verification",
            "competitor_research": [
                {"competitor": "Manual alternative", "difference": "More manual steps"}
            ],
        }
        run.return_value = response(json.dumps(evidence))
        self.assertEqual(assess_factory_market_fit(JOB),
                         ("MARKET_FIT_PASS", "FACTORY_SOURCE_SHA_BOUND_REVIEWED_EVIDENCE"))


if __name__ == "__main__":
    unittest.main()
