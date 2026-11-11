"""Trusted-profile local QA runner with durable GitHub evidence return."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from all_auto.local_qa_evidence import (
    EvidenceStore, GitHubContentsTransport, process_retry_queue,
)


def _load(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ValueError("LOCAL_QA_HOLD: invalid JSON input")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("LOCAL_QA_HOLD: JSON object required")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--job", type=Path)
    parser.add_argument("--profile", type=Path,
                        help="Local trusted profile; never accept this file from a handoff artifact")
    parser.add_argument("--retry-only", action="store_true")
    parser.add_argument("--github-repository", default="shihuiarenjinba-png/Windows-all-auto")
    parser.add_argument("--github-branch", default="codex/local-qa-evidence-inbox")
    parser.add_argument("--github-base-ref", default="codex/windows-all-auto-integration-20261026")
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--max-state-bytes", type=int, default=5 * 1024 * 1024 * 1024)
    args = parser.parse_args(argv)
    try:
        store = EvidenceStore(args.state_root)
        recovered = store.recover_interrupted()
        if not args.retry_only:
            if args.job is None or args.profile is None:
                raise ValueError("LOCAL_QA_HOLD: --job and --profile are required")
            job = _load(args.job)
            profile = _load(args.profile)
            command = profile.get("command")
            allowed = profile.get("allowed_executables")
            if (not isinstance(command, list) or not command or
                    not isinstance(allowed, list) or command[0] not in allowed):
                raise ValueError("LOCAL_QA_HOLD: command is not allowed by local profile")
            result = store.execute(
                job, command, cwd=Path(profile["cwd"]),
                timeout_seconds=int(profile.get("timeout_seconds", 300)),
                expected=profile.get("expected", {"exit_code": 0}),
                gui_test=bool(profile.get("gui_test", False)),
            )
        else:
            result = None
        transport = GitHubContentsTransport(
            repository=args.github_repository, branch=args.github_branch,
            base_ref=args.github_base_ref)
        retry = process_retry_queue(store, transport)
        retention = store.prune_verified(retention_days=args.retention_days,
                                         max_total_bytes=args.max_state_bytes)
        output = {"recovered_interrupted_runs": recovered, "retry": retry,
                  "retention": retention,
                  "run_id": result.run_id if result else None,
                  "test_status": result.status if result else None,
                  "e2e_pass": False}
        if result:
            manifest = json.loads((result.run_directory / "manifest.json").read_text(encoding="utf-8"))
            output["e2e_pass"] = bool(manifest.get("e2e_pass"))
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if output["e2e_pass"] or args.retry_only and retry["failed"] == 0 else 2
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(str(exc)[:300], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
