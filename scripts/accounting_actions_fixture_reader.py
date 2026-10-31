"""Read-only, independently pinned GitHub Actions accounting fixture attestation.

A successful generic Factory workflow or self-authored JSON is not evidence.
The operator must independently review and supply the workflow's Git blob SHA;
the job only supplies the immutable source SHA and exact run ID. No GitHub
writes, credentials in logs, local fallback, Partner Center or Store actions.
"""
from __future__ import annotations

import json
import re
import subprocess
from functools import partial

from scripts.accounting_country_gate import FACTORY, SPECS
from scripts.accounting_e2e_gate import CASES, INFERENCE_CASES, US, US_CASES

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_BRANCH = re.compile(r"codex/[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
_WORKFLOW = ".github/workflows/accounting-e2e-fixtures.yml"
_MAX_RESPONSE = 512 * 1024


class AccountingActionsHold(RuntimeError):
    """A fixed, non-secret HOLD reason; never include API stderr."""


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise AccountingActionsHold(code)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "HOLD_ACCOUNTING_ACTIONS_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_constant(_):
    raise AccountingActionsHold("HOLD_ACCOUNTING_ACTIONS_JSON_INVALID")


def _get(endpoint: str) -> dict:
    try:
        proc = subprocess.run(
            ["gh", "api", "--method", "GET", endpoint],
            capture_output=True, text=True, encoding="utf-8", timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AccountingActionsHold("HOLD_ACCOUNTING_ACTIONS_API_UNAVAILABLE") from exc
    _require(proc.returncode == 0, "HOLD_ACCOUNTING_ACTIONS_API_UNAVAILABLE")
    _require(isinstance(proc.stdout, str)
             and len(proc.stdout.encode("utf-8")) <= _MAX_RESPONSE,
             "HOLD_ACCOUNTING_ACTIONS_RESPONSE_INVALID")
    try:
        result = json.loads(proc.stdout, object_pairs_hook=_unique,
                            parse_constant=_reject_constant)
    except AccountingActionsHold:
        raise
    except (TypeError, ValueError, UnicodeError) as exc:
        raise AccountingActionsHold("HOLD_ACCOUNTING_ACTIONS_JSON_INVALID") from exc
    _require(type(result) is dict, "HOLD_ACCOUNTING_ACTIONS_JSON_INVALID")
    return result


def read_verified_accounting_actions(
    job: dict, *, reviewed_workflow_blob_sha: str | None = None,
) -> dict:
    """Attest every named fixture job in one exact-SHA Actions run.

    reviewed_workflow_blob_sha is an out-of-band, code-reviewed trust anchor,
    not a field read from the queue. Without it the adapter cannot PASS.
    The Factory workflow must expose only matrix jobs named
    accounting-fixture/<slug>/<case>, each testing that exact case.
    """
    _require(type(job) is dict and job.get("slug") in SPECS
             and job.get("product_type") == "APP"
             and job.get("source_repository") == FACTORY,
             "HOLD_ACCOUNTING_ACTIONS_JOB_INVALID")
    slug, sha, branch = job["slug"], job.get("source_sha"), job.get("source_branch")
    _require(type(sha) is str and _SHA.fullmatch(sha) is not None
             and type(branch) is str and _BRANCH.fullmatch(branch) is not None
             and ".." not in branch and "//" not in branch
             and job.get("request_id") == f"app-{slug}-{sha[:12]}",
             "HOLD_ACCOUNTING_ACTIONS_BINDING_INVALID")
    run_id = job.get("accounting_fixture_run_id")
    _require(type(run_id) is int and run_id > 0,
             "HOLD_ACCOUNTING_ACTIONS_RUN_NOT_PINNED")
    _require(type(reviewed_workflow_blob_sha) is str
             and _SHA.fullmatch(reviewed_workflow_blob_sha) is not None,
             "HOLD_ACCOUNTING_ACTIONS_WORKFLOW_NOT_REVIEWED")

    run = _get(f"repos/{FACTORY}/actions/runs/{run_id}")
    expected_path = f"{FACTORY}/{_WORKFLOW}@refs/heads/{branch}"
    _require(run.get("id") == run_id and type(run.get("id")) is int
             and run.get("head_sha") == sha and run.get("head_branch") == branch
             and run.get("path") == expected_path
             and run.get("event") in {"push", "workflow_dispatch"}
             and run.get("status") == "completed"
             and run.get("conclusion") == "success"
             and type(run.get("run_attempt")) is int
             and run["run_attempt"] == 1
             and type(run.get("workflow_id")) is int
             and run["workflow_id"] > 0
             and type(run.get("repository")) is dict
             and run["repository"].get("full_name") == FACTORY
             and type(run.get("head_repository")) is dict
             and run["head_repository"].get("full_name") == FACTORY,
             "HOLD_ACCOUNTING_ACTIONS_RUN_CONFLICT")

    workflow = _get(f"repos/{FACTORY}/contents/{_WORKFLOW}?ref={sha}")
    _require(workflow.get("type") == "file"
             and workflow.get("path") == _WORKFLOW
             and workflow.get("sha") == reviewed_workflow_blob_sha
             and type(workflow.get("size")) is int
             and 0 < workflow["size"] <= 65536,
             "HOLD_ACCOUNTING_ACTIONS_WORKFLOW_CONFLICT")

    kind = "freelance" if "freelance" in slug else "bookkeeping"
    required = CASES[kind] | INFERENCE_CASES | (US_CASES if slug in US else frozenset())
    expected = {f"accounting-fixture/{slug}/{case}": case for case in required}
    result = _get(f"repos/{FACTORY}/actions/runs/{run_id}/jobs?per_page=100&page=1")
    jobs = result.get("jobs")
    _require(type(result.get("total_count")) is int
             and result["total_count"] == len(expected)
             and type(jobs) is list and len(jobs) == len(expected),
             "HOLD_ACCOUNTING_ACTIONS_JOB_SET_CONFLICT")
    seen = set()
    for item in jobs:
        _require(type(item) is dict and type(item.get("name")) is str
                 and item["name"] in expected and item["name"] not in seen
                 and type(item.get("run_id")) is int and item["run_id"] == run_id
                 and type(item.get("run_attempt")) is int
                 and item["run_attempt"] == 1
                 and item.get("status") == "completed"
                 and item.get("conclusion") == "success"
                 and (item.get("head_sha") is None or item["head_sha"] == sha),
                 "HOLD_ACCOUNTING_ACTIONS_FIXTURE_FAILED_OR_AMBIGUOUS")
        seen.add(item["name"])
    _require(seen == set(expected), "HOLD_ACCOUNTING_ACTIONS_JOB_SET_CONFLICT")
    return {
        "verification_method": "AUTHENTICATED_GITHUB_ACTIONS_EXACT_SHA",
        "verified": True, "conclusion": "success", "repository": FACTORY,
        "source_sha": sha, "request_id": job["request_id"], "slug": slug,
        "run_id": run_id, "test_results": {case: "PASS" for case in sorted(required)},
    }


def check_accounting_with_reviewed_actions(
    job: dict, *, phase: str, reviewed_workflow_blob_sha: str | None,
    fetch_official_review=None, fetch_verified_store_availability=None,
    other_jobs=(),
) -> tuple[str, str]:
    """Bind independently pinned Actions to the authenticated Factory reader.

    Missing review/IRS/Store evidence remains HOLD; never self-authorize a SKU.
    """
    from scripts.accounting_immutable_github_reader import (
        check_accounting_e2e_with_authenticated_factory,
    )
    return check_accounting_e2e_with_authenticated_factory(
        job, phase=phase,
        fetch_verified_ci=partial(read_verified_accounting_actions,
                                  reviewed_workflow_blob_sha=reviewed_workflow_blob_sha),
        fetch_official_review=fetch_official_review,
        fetch_verified_store_availability=fetch_verified_store_availability,
        other_jobs=other_jobs,
    )
