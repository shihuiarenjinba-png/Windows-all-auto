"""CLI for the bounded local Ollama QA supervisor."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable

from all_auto.local_qa_evidence import (
    EvidenceStore, GitHubContentsTransport, process_retry_queue,
)
from all_auto.product_qa_plan import (
    BoundProductPlanPlanner, ProductQAPlanHold, load_bound_plan,
    verify_plan_for_job,
)
from all_auto.qa_supervisor import (
    QASupervisor, load_default_catalog, require_new_source_sha,
)
from all_auto.trusted_uia import UIA_ACTIONS
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
    parser.add_argument("--package", type=Path)
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
        if args.package is None:
            parser.error("--product-qa-plan requires --package")
        try:
            bound_plan = load_bound_plan(args.product_qa_plan)
            capability = verify_plan_for_job(
                bound_plan,
                job=job,
                artifact_path=args.artifact,
                package_path=args.package,
                supported_test_ids=set(catalog.tests) | UIA_ACTIONS,
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
            bound_plan, supported_test_ids=set(catalog.tests) | UIA_ACTIONS,
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
    if args.product_qa_plan and any(
            step["action"] in UIA_ACTIONS for step in bound_plan["steps"]):
        action_logs = args.state_root / "product-action-logs"
        action_logs.mkdir(parents=True, exist_ok=True)
        action_log = action_logs / (
            hashlib.sha256(job["request_id"].encode("utf-8")).hexdigest() +
            ".jsonl"
        )
        if action_log.exists():
            raise SystemExit("PRODUCT_QA_EXECUTION_HOLD: action log already exists")
        worker = (
            Path(__file__).resolve().parent / "trusted_product_qa_worker.py"
        )
        command = [
            sys.executable, str(worker), "--plan", str(args.product_qa_plan),
            "--artifact", str(args.artifact), "--action-log", str(action_log),
            "--enable-ollama-supervision", "--model", args.model,
        ]

        def collect_uia(run_id: str, _folder: Path) -> None:
            if not action_log.is_file():
                return
            for line in action_log.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                store.record_ui_action(
                    run_id, action=str(item.get("action", "UNKNOWN")),
                    target=str(item.get("target", "")),
                    result=str(item.get("result", "UNKNOWN")),
                    details=dict(item.get("details", {})),
                )

        result = store.execute(
            job, command, cwd=args.intake_root, timeout_seconds=600,
            expected={"exit_code": 0, "completion_policy": "WAIT_FOR_EXIT"},
            gui_test=True,
            event_log_collector=_product_event_log_collector(args.artifact.name),
            evidence_callback=collect_uia,
        )
        github_return = (
            process_retry_queue(store, transport, max_items=20)
            if transport is not None else
            {"verified": 0, "failed": 0, "deferred": 0, "locked": 0}
        )
        manifest = json.loads(
            (result.run_directory / "manifest.json").read_text(encoding="utf-8")
        )
        acknowledgement = (
            json.loads((store.acks / (result.run_id + ".json")).read_text(
                encoding="utf-8"))
            if (store.acks / (result.run_id + ".json")).is_file() else {}
        )
        output = {
            "status": "SUPERVISOR_COMPLETE" if result.status == "TEST_PASS" else "TEST_FAIL",
            "run_ids": [result.run_id], "test_status": result.status,
            "evidence_return_status": acknowledgement.get(
                "status", "EVIDENCE_RETURN_NOT_VERIFIED"),
            "evidence_return_e2e_pass": bool(
                acknowledgement.get("evidence_return_e2e_pass")),
            "collection_complete": manifest.get("collection_complete", False),
            "github_return": github_return,
            "product_e2e_pass": False, "e2e_pass": False,
            "release_ready": False, "store_submission_allowed": False,
            "source_edit_authority": False,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if (
            result.status == "TEST_PASS" and
            (not args.allow_github_write or output["evidence_return_e2e_pass"])
        ) else 2
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
        "evidence_return_status": result.evidence_return_status,
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
