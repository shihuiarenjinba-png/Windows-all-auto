"""Approve one already-captured GUI screenshot after human privacy review.

This is the only step that marks a screenshot GitHub-shareable. Optionally it
can flush the rebuilt evidence envelope and independently verify the ACK.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from all_auto.local_qa_evidence import (  # noqa: E402
    EvidenceStore, GitHubContentsTransport, process_retry_queue,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--approve-shareable", action="store_true")
    parser.add_argument("--allow-github-write", action="store_true")
    parser.add_argument("--repository")
    parser.add_argument("--evidence-branch", default="codex/final-sale-qa-evidence-20261117")
    parser.add_argument("--base-ref")
    args = parser.parse_args(argv)
    if not args.approve_shareable:
        parser.error("--approve-shareable is required after actual human privacy review")
    if args.allow_github_write and (not args.repository or not args.base_ref):
        parser.error("GitHub write requires --repository and --base-ref")

    store = EvidenceStore(args.state_root)
    manifest = store.approve_screenshot_for_github(
        args.run_id, filename=args.filename, expected_sha256=args.sha256,
    )
    output = {
        "status": "SCREENSHOT_PRIVACY_REVIEW_APPROVED",
        "run_id": args.run_id,
        "collection": manifest.get("collection"),
        "collection_complete": manifest.get("collection_complete"),
        "evidence_return_e2e_pass": False,
        "product_e2e_pass": False,
        "release_ready": False,
        "store_submission_allowed": False,
    }
    if args.allow_github_write:
        transport = GitHubContentsTransport(
            repository=args.repository,
            branch=args.evidence_branch,
            base_ref=args.base_ref,
        )
        stats = process_retry_queue(store, transport, max_items=20)
        ack_path = store.acks / (args.run_id + ".json")
        output["retry_worker"] = stats
        output["ack"] = (
            json.loads(ack_path.read_text(encoding="utf-8"))
            if ack_path.is_file() else None
        )
        if output["ack"]:
            output["evidence_return_e2e_pass"] = bool(
                output["ack"].get("evidence_return_e2e_pass")
            )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
