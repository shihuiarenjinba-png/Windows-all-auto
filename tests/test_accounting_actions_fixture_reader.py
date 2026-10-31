"""Offline mock contract tests; never interpreted as live Actions evidence."""
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.accounting_actions_fixture_reader import (
    AccountingActionsHold, read_verified_accounting_actions,
)
from scripts.accounting_country_gate import FACTORY
from scripts.accounting_e2e_gate import CASES, INFERENCE_CASES, US, US_CASES

SHA = "a" * 40
REVIEWED = "b" * 40
BRANCH = "codex/accounting-review"
RUN_ID = 12345


def job(slug="jp-freelance-ledger"):
    return {"slug": slug, "product_type": "APP", "source_repository": FACTORY,
            "source_branch": BRANCH, "source_sha": SHA,
            "request_id": f"app-{slug}-{SHA[:12]}",
            "accounting_fixture_run_id": RUN_ID}


def fixture_jobs(slug):
    kind = "freelance" if "freelance" in slug else "bookkeeping"
    names = CASES[kind] | INFERENCE_CASES | (US_CASES if slug in US else frozenset())
    return [{"name": f"accounting-fixture/{slug}/{name}",
             "run_id": RUN_ID, "run_attempt": 1, "status": "completed",
             "conclusion": "success", "head_sha": SHA} for name in sorted(names)]


def responses(slug):
    run = {"id": RUN_ID, "head_sha": SHA, "head_branch": BRANCH,
           "path": f"{FACTORY}/.github/workflows/accounting-e2e-fixtures.yml@refs/heads/{BRANCH}",
           "event": "push", "status": "completed", "conclusion": "success",
           "run_attempt": 1, "workflow_id": 45,
           "repository": {"full_name": FACTORY}, "head_repository": {"full_name": FACTORY}}
    workflow = {"type": "file", "path": ".github/workflows/accounting-e2e-fixtures.yml",
                "sha": REVIEWED, "size": 1234}
    jobs = fixture_jobs(slug)
    return [run, workflow, {"total_count": len(jobs), "jobs": jobs}]


def fake_run(payloads):
    def run(*args, **kwargs):
        payload = payloads.pop(0)
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    return run


class AccountingActionsFixtureReaderTests(unittest.TestCase):
    @patch("scripts.accounting_actions_fixture_reader.subprocess.run")
    def test_exact_source_all_named_jobs_jp_and_us(self, run):
        for slug in ("jp-freelance-ledger", "us-bookkeeping-desk"):
            with self.subTest(slug=slug):
                run.side_effect = fake_run(responses(slug))
                result = read_verified_accounting_actions(
                    job(slug), reviewed_workflow_blob_sha=REVIEWED)
                self.assertEqual(result["source_sha"], SHA)
                self.assertEqual(result["request_id"], job(slug)["request_id"])
                self.assertEqual(set(result["test_results"]),
                                 {j["name"].split("/")[-1] for j in fixture_jobs(slug)})
                self.assertTrue(all(v == "PASS" for v in result["test_results"].values()))
                self.assertEqual(run.call_count % 3, 0)
                self.assertTrue(all(c.kwargs["timeout"] == 45 for c in run.call_args_list))

    @patch("scripts.accounting_actions_fixture_reader.subprocess.run")
    def test_unpinned_unreviewed_or_wrong_source_fails_before_io(self, run):
        for change, expected in (
            ({"accounting_fixture_run_id": None}, "RUN_NOT_PINNED"),
            ({"accounting_fixture_run_id": True}, "RUN_NOT_PINNED"),
            ({"source_sha": "main"}, "BINDING_INVALID"),
            ({"source_branch": "main"}, "BINDING_INVALID"),
            ({"source_branch": "codex/../main"}, "BINDING_INVALID"),
            ({"request_id": "another-product"}, "BINDING_INVALID"),
            ({"source_repository": "evil/repo"}, "JOB_INVALID"),
            ({"slug": "unknown"}, "JOB_INVALID"),
        ):
            with self.subTest(change=change):
                with self.assertRaisesRegex(AccountingActionsHold, expected):
                    read_verified_accounting_actions(job() | change,
                                                     reviewed_workflow_blob_sha=REVIEWED)
        with self.assertRaisesRegex(AccountingActionsHold, "WORKFLOW_NOT_REVIEWED"):
            read_verified_accounting_actions(job())
        run.assert_not_called()

    @patch("scripts.accounting_actions_fixture_reader.subprocess.run")
    def test_wrong_run_workflow_and_head_fail_closed(self, run):
        for change in ({"head_sha": "c" * 40}, {"head_branch": "codex/other"},
                       {"path": "evil.yml"}, {"run_attempt": 2},
                       {"conclusion": "skipped"}, {"event": "pull_request"},
                       {"repository": {"full_name": "evil/repo"}}):
            with self.subTest(change=change):
                items = responses(job()["slug"])
                items[0].update(change)
                run.side_effect = fake_run(items)
                with self.assertRaisesRegex(AccountingActionsHold, "RUN_CONFLICT"):
                    read_verified_accounting_actions(job(), reviewed_workflow_blob_sha=REVIEWED)
        for change in ({"sha": "c" * 40}, {"path": "other.yml"},
                       {"size": True}, {"type": "dir"}):
            with self.subTest(change=change):
                items = responses(job()["slug"])
                items[1].update(change)
                run.side_effect = fake_run(items)
                with self.assertRaisesRegex(AccountingActionsHold, "WORKFLOW_CONFLICT"):
                    read_verified_accounting_actions(job(), reviewed_workflow_blob_sha=REVIEWED)

    @patch("scripts.accounting_actions_fixture_reader.subprocess.run")
    def test_missing_failed_duplicate_cross_product_jobs_are_rejected(self, run):
        for mutation in ("missing", "failed", "duplicate", "cross", "rerun", "extra"):
            with self.subTest(mutation=mutation):
                items = responses(job()["slug"])
                jobs = items[2]["jobs"]
                if mutation == "missing":
                    jobs.pop()
                elif mutation == "failed":
                    jobs[0]["conclusion"] = "failure"
                elif mutation == "duplicate":
                    jobs[1]["name"] = jobs[0]["name"]
                elif mutation == "cross":
                    jobs[0]["name"] = "accounting-fixture/us-bookkeeping-desk/monthly_net"
                elif mutation == "rerun":
                    jobs[0]["run_attempt"] = 2
                else:
                    jobs.append(dict(jobs[0], name="setup"))
                items[2]["total_count"] = len(jobs)
                run.side_effect = fake_run(items)
                with self.assertRaises(AccountingActionsHold):
                    read_verified_accounting_actions(job(), reviewed_workflow_blob_sha=REVIEWED)

    @patch("scripts.accounting_actions_fixture_reader.subprocess.run")
    def test_auth_error_and_duplicate_api_keys_are_secret_safe(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "token=DO_NOT_LEAK")
        with self.assertRaisesRegex(AccountingActionsHold, "^HOLD_ACCOUNTING_ACTIONS_API_UNAVAILABLE$") as caught:
            read_verified_accounting_actions(job(), reviewed_workflow_blob_sha=REVIEWED)
        self.assertNotIn("DO_NOT_LEAK", str(caught.exception))
        run.return_value = subprocess.CompletedProcess([], 0, '{"id":1,"id":2}', "")
        with self.assertRaisesRegex(AccountingActionsHold, "DUPLICATE_KEY"):
            read_verified_accounting_actions(job(), reviewed_workflow_blob_sha=REVIEWED)
        run.return_value = subprocess.CompletedProcess([], 0, "x" * (512 * 1024 + 1), "")
        with self.assertRaisesRegex(AccountingActionsHold, "RESPONSE_INVALID"):
            read_verified_accounting_actions(job(), reviewed_workflow_blob_sha=REVIEWED)


if __name__ == "__main__":
    unittest.main()
