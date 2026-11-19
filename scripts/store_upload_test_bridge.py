"""Run final-QA-passed GitHub products through Windows-Automator upload tests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from all_auto.store_upload_test import (  # noqa: E402
    StoreUploadTestHold, classify_automator_report, prepare_queue,
    validate_batch, verify_automator_checkout,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True, type=Path)
    parser.add_argument("--automator-checkout", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument(
        "--execution-mode", choices=("dry_run", "live"), default="dry_run"
    )
    parser.add_argument("--confirm-live-draft", action="store_true")
    parser.add_argument("--cdp-url", default="")
    args = parser.parse_args(argv)

    if args.execution_mode == "live":
        if not args.confirm_live_draft:
            parser.error("live mode requires --confirm-live-draft at action time")
        if not args.cdp_url:
            parser.error("live mode requires --cdp-url for an already-authenticated Partner Center browser")

    try:
        if args.batch.is_symlink() or not args.batch.is_file() or args.batch.stat().st_size > 2 * 1024 * 1024:
            raise StoreUploadTestHold("STORE_UPLOAD_TEST_HOLD: batch file missing, linked, or oversized")
        raw = json.loads(args.batch.read_text(encoding="utf-8"))
        batch = validate_batch(raw)
        verify_automator_checkout(args.automator_checkout, batch["automator"])
        prepared = prepare_queue(batch, args.workspace)

        queue_path = args.workspace / "windows-automator-queue.json"
        json_report = args.workspace / "windows-automator-report.json"
        markdown_report = args.workspace / "windows-automator-report.md"
        queue_path.write_text(
            json.dumps(prepared.queue, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        command = [
            sys.executable, "-m", "store_manager.cli", "night-run",
            "--queue", str(queue_path),
            "--json-report", str(json_report),
            "--markdown-report", str(markdown_report),
            "--execution-mode", args.execution_mode,
        ]
        if args.execution_mode == "live":
            command += [
                "--confirm-live-draft",
                "--cdp-url", args.cdp_url,
                "--evidence-dir", str(args.workspace / "partner-center-evidence"),
            ]

        completed = subprocess.run(
            command,
            cwd=str(args.automator_checkout.resolve()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600 if args.execution_mode == "live" else 600,
            check=False,
        )
        if not json_report.is_file() or json_report.stat().st_size > 10 * 1024 * 1024:
            raise StoreUploadTestHold(
                "STORE_UPLOAD_TEST_HOLD: Windows-Automator did not produce a valid JSON report"
            )
        report = json.loads(json_report.read_text(encoding="utf-8"))
        result = classify_automator_report(
            report, execution_mode=args.execution_mode
        )
        result.update({
            "automator_commit_sha": batch["automator"]["commit_sha"],
            "execution_mode": args.execution_mode,
            "process_exit_code": completed.returncode,
            "queue_path": str(queue_path),
            "json_report": str(json_report),
            "markdown_report": str(markdown_report),
        })
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.execution_mode == "dry_run":
            return 0 if result["status"] == "UPLOAD_TEST_DRY_RUN_PASS" else 2
        return 0 if result["status"] == "UPLOAD_TEST_DRAFT_SAVED" else 2
    except (
        OSError, ValueError, TypeError, KeyError, json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        print(json.dumps({
            "status": "STORE_UPLOAD_TEST_HOLD",
            "reason": str(exc)[:1000],
            "store_submission_allowed": False,
            "certification_allowed": False,
            "publish_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
