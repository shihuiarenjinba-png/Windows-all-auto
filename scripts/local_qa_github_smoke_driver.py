"""Synthetic-only local Windows <-> GitHub evidence smoke driver.

This is not a production QA runner. It deliberately injects a synthetic Event Log
record so a public-repository transport smoke never uploads unrelated real Windows
Application events from the user's machine.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import uuid

from all_auto.local_qa_evidence import (
    EvidenceStore,
    GitHubContentsTransport,
    process_retry_queue,
)
from qa_ai.analyzer import AnalysisEngine, OllamaClient, analyze_run
from qa_ai.rag import RepairHistory


SHA40 = re.compile(r"^[0-9a-f]{40}$")
FAKE_SECRET = "github_pat_" + "SMOKEONLY" + "12345678901234567890"


def _synthetic_event_log(started: str, finished: str) -> str:
    return (
        "<Events><Event><Provider Name=\"WindowsAllAutoSyntheticSmoke\"/>"
        f"<Data Name=\"Started\">{started}</Data>"
        f"<Data Name=\"Finished\">{finished}</Data>"
        "</Event></Events>"
    )


def _write_fixture(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "smoke_fixture.py"
    path.write_text(
        "import sys\n"
        "print('LOCAL_QA_GITHUB_SMOKE_OK')\n"
        f"print('Authorization: Bearer {FAKE_SECRET}')\n"
        "print('LOCAL_QA_GITHUB_SMOKE_STDERR', file=sys.stderr)\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--code-branch", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--evidence-branch", required=True)
    parser.add_argument("--enable-ai", action="store_true")
    parser.add_argument("--ai-model", default="windows-qa-analyst")
    args = parser.parse_args(argv)

    if not SHA40.fullmatch(args.source_sha):
        raise SystemExit("LOCAL_GITHUB_SMOKE_HOLD: invalid source SHA")

    store = EvidenceStore(args.state_root)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    request_id = f"local-smoke-{stamp}-{uuid.uuid4().hex[:8]}"
    fixture_root = args.state_root / "smoke-fixtures" / request_id
    fixture = _write_fixture(fixture_root)
    artifact_sha = hashlib.sha256(fixture.read_bytes()).hexdigest()

    job = {
        "request_id": request_id,
        "product_type": "APP",
        "source_repository": args.repository,
        "source_branch": args.code_branch,
        "source_sha": args.source_sha,
        "artifact_sha256": artifact_sha,
        "test_suite_version": "local-github-smoke-v1",
        "slug": "windows-all-auto-local-smoke",
    }

    result = store.execute(
        job,
        [sys.executable, str(fixture)],
        cwd=fixture_root,
        timeout_seconds=60,
        expected={"exit_code": 0},
        gui_test=False,
        event_log_collector=_synthetic_event_log,
    )

    ai_status = "DISABLED"
    if args.enable_ai:
        try:
            history = RepairHistory(args.state_root / "qa-ai-repair-history.sqlite3")
            engine = AnalysisEngine(
                client=OllamaClient(),
                model=args.ai_model,
                history=history,
            )
            ai_status = analyze_run(store, result.run_directory, engine=engine).status
        except Exception as exc:  # smoke must preserve evidence even if AI is unavailable
            ai_status = "AI_ANALYSIS_UNAVAILABLE:" + type(exc).__name__

    transport = GitHubContentsTransport(
        repository=args.repository,
        branch=args.evidence_branch,
        base_ref=args.code_branch,
    )
    retry = process_retry_queue(store, transport)

    manifest = json.loads(
        (result.run_directory / "manifest.json").read_text(encoding="utf-8")
    )
    ack_path = store.acks / f"{result.run_id}.json"
    ack = (
        json.loads(ack_path.read_text(encoding="utf-8"))
        if ack_path.is_file()
        else None
    )

    output = {
        "status": (
            "LOCAL_GITHUB_EVIDENCE_SMOKE_DRIVER_PASS"
            if manifest.get("evidence_return_e2e_pass") is True
            else "LOCAL_GITHUB_EVIDENCE_SMOKE_DRIVER_HOLD"
        ),
        "run_id": result.run_id,
        "request_id": request_id,
        "test_status": result.status,
        "ai_analysis_status": ai_status,
        "retry": retry,
        "ack": ack,
        "evidence_return_e2e_pass": bool(
            manifest.get("evidence_return_e2e_pass")
        ),
        "product_e2e_pass": bool(manifest.get("product_e2e_pass")),
        "e2e_pass": bool(manifest.get("e2e_pass")),
        "release_ready": bool(manifest.get("release_ready")),
        "store_submission_allowed": bool(
            manifest.get("store_submission_allowed")
        ),
        "user_product_approval": bool(
            manifest.get("user_product_approval")
        ),
        "user_price_approval": bool(manifest.get("user_price_approval")),
        "synthetic_event_log": True,
        "real_windows_event_log_collected": False,
        "fake_secret_marker_sha256": hashlib.sha256(
            FAKE_SECRET.encode("utf-8")
        ).hexdigest(),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["evidence_return_e2e_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
