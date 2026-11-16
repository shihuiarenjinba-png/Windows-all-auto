"""CLI for the bounded local Ollama QA supervisor."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from all_auto.local_qa_evidence import EvidenceStore, GitHubContentsTransport
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
        event_log_collector=_synthetic_event_log if args.synthetic_phase1 else None,
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
