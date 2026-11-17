"""CLI for the bounded local Ollama QA supervisor."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Callable

from all_auto.local_qa_evidence import EvidenceStore, GitHubContentsTransport
from all_auto.product_qa_plan import (
    BoundProductPlanPlanner, ProductQAPlanHold, load_bound_plan,
    verify_plan_for_job,
)
from all_auto.qa_supervisor import (
    QASupervisor, load_default_catalog, require_new_source_sha,
)
from qa_ai.analyzer import AnalysisEngine, OllamaClient
from qa_ai.planner import OllamaPlannerClient, PlannerEngine


def _synthetic_event_log(started: str, finished: str) -> str:
    return (
        '<Events><Event><Provider Name="WindowsAllAutoSyntheticSupervisor"/>'
        f'<Data Name="Started">{started}</Data>'
        f'<Data Name="Finished">{finished}</Data></Event></Events>'
    )


def _product_event_log_collector(
    executable_name: str, *,
    platform_name: str = os.name,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Callable[[str, str], str]:
    """Return only raw Application events bound to the tested executable.

    The time-bounded Application query is never persisted. Only event XML that
    contains the exact executable basename is retained locally; the existing
    evidence redactor sanitizes that product-specific subset before upload.
    """
    if not executable_name or Path(executable_name).name != executable_name:
        raise ValueError("invalid product executable name")
    needle = executable_name.casefold()

    def collect(started: str, finished: str) -> str:
        if platform_name != "nt":
            raise OSError("product-specific Windows Event Log requires Windows")
        query = (
            "*[System[TimeCreated[@SystemTime>='" + started +
            "' and @SystemTime<='" + finished + "']]]"
        )
        result = runner(
            ["wevtutil", "qe", "Application", "/q:" + query,
             "/f:RenderedXml", "/c:200", "/rd:true"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
        if result.returncode:
            raise OSError("wevtutil exit " + str(result.returncode))
        raw = result.stdout.strip()
        if not raw:
            return ""
        events = re.findall(
            r"<Event(?:\s[^>]*)?>.*?</Event>", raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not events:
            raise OSError("wevtutil returned malformed event XML")
        selected = [event for event in events if needle in event.casefold()]
        return "<Events>" + "".join(selected) + "</Events>" if selected else ""

    return collect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--intake-root", type=Path, required=True)
    parser.add_argument("--model", default="windows-qa-analyst")
    parser.add_argument("--enable-analysis", action="store_true")
    parser.add_argument("--synthetic-phase1", action="store_true")
    parser.add_argument("--allow-github-write", action="store_true")
    parser.add_argument("--repository")
    parser.add_argument("--evidence-branch", default="codex/local-qa-evidence-smoke")
    parser.add_argument("--base-ref")
    parser.add_argument("--previous-repair-handoff", type=Path)
    parser.add_argument("--product-qa-plan", type=Path)
    args = parser.parse_args(argv)

    job = json.loads(args.job.read_text(encoding="utf-8"))
    if args.synthetic_phase1 and not str(job.get("slug", "")).startswith("synthetic-"):
        parser.error("--synthetic-phase1 requires a synthetic-* job slug")
    if args.allow_github_write and (not args.repository or not args.base_ref):
        parser.error("GitHub write requires --repository and --base-ref")
    if args.previous_repair_handoff:
        require_new_source_sha(args.previous_repair_handoff, job)

    store = EvidenceStore(args.state_root)
    store.recover_interrupted()
    catalog = load_default_catalog()
    if args.product_qa_plan:
        try:
            bound_plan = load_bound_plan(args.product_qa_plan)
            capability = verify_plan_for_job(
                bound_plan,
                job=job,
                artifact_path=args.artifact,
                supported_test_ids=set(catalog.tests),
            )
        except ProductQAPlanHold as exc:
            print(json.dumps({
                "status": "PRODUCT_QA_PLAN_HOLD",
                "reason": str(exc),
                "product_e2e_pass": False,
                "release_ready": False,
                "store_submission_allowed": False,
            }, ensure_ascii=False, indent=2))
            return 2
        if capability["status"] != "PRODUCT_QA_PLAN_READY":
            print(json.dumps({
                **capability,
                "product_e2e_pass": False,
                "release_ready": False,
                "store_submission_allowed": False,
            }, ensure_ascii=False, indent=2))
            return 2
        planner = BoundProductPlanPlanner(
            bound_plan, supported_test_ids=set(catalog.tests),
        )
    else:
        planner = PlannerEngine(client=OllamaPlannerClient(), model=args.model)
    analyzer = (
        AnalysisEngine(client=OllamaClient(), model=args.model)
        if args.enable_analysis else None
    )
    transport = (
        GitHubContentsTransport(
            repository=args.repository, branch=args.evidence_branch,
            base_ref=args.base_ref,
        ) if args.allow_github_write else None
    )
    supervisor = QASupervisor(
        catalog=catalog, store=store, planner=planner,
        analyzer=analyzer, transport=transport,
        event_log_collector=(
            _synthetic_event_log if args.synthetic_phase1 else
            _product_event_log_collector(args.artifact.name)
        ),
    )
    supervisor.states.recover_interrupted()
    result = supervisor.run(
        job=job, artifact_path=args.artifact, intake_root=args.intake_root,
    )
    output = {
        "status": result.status,
        "state_path": str(result.state_path),
        "run_ids": list(result.run_ids),
        "test_status": result.test_status,
        "evidence_return_e2e_pass": result.evidence_return_e2e_pass,
        "product_e2e_pass": False,
        "e2e_pass": False,
        "release_ready": False,
        "store_submission_allowed": False,
        "source_edit_authority": False,
        "handoff_path": str(result.handoff_path),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    succeeded = (
        result.status == "SUPERVISOR_COMPLETE" and
        result.test_status == "TEST_PASS" and
        (not args.allow_github_write or result.evidence_return_e2e_pass)
    )
    return 0 if succeeded else 2


if __name__ == "__main__":
    raise SystemExit(main())
