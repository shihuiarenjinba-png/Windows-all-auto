"""Execute a pre-validated bound plan with fixed trusted implementations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from all_auto.product_qa_executor import (  # noqa: E402
    ProductQAExecutionHold, execute_bound_product_plan,
)
from all_auto.product_qa_plan import load_bound_plan  # noqa: E402
from all_auto.trusted_window_capture import (  # noqa: E402
    TrustedWindowCapture, TrustedWindowCaptureHold,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--action-log", required=True, type=Path)
    parser.add_argument("--screenshot-output", type=Path)
    parser.add_argument("--screenshot-root", type=Path)
    args = parser.parse_args(argv)
    try:
        plan = load_bound_plan(args.plan)
        capture_result = None
        if bool(args.screenshot_output) != bool(args.screenshot_root):
            parser.error("--screenshot-output and --screenshot-root must be supplied together")

        def capture(process, _actions):
            nonlocal capture_result
            if args.screenshot_output is None:
                return
            capture_result = TrustedWindowCapture().capture(
                process_id=process.pid,
                artifact_path=args.artifact,
                expected_sha256=plan["executable_sha256"],
                output_path=args.screenshot_output,
                allowed_root=args.screenshot_root,
            )

        result = execute_bound_product_plan(
            plan, artifact_path=args.artifact, action_log=args.action_log,
            before_terminate=capture if args.screenshot_output else None,
        )
    except (ProductQAExecutionHold, TrustedWindowCaptureHold, ValueError) as exc:
        print(json.dumps({
            "status": "PRODUCT_QA_EXECUTION_HOLD", "reason": str(exc),
            "product_e2e_pass": False, "release_ready": False,
            "store_submission_allowed": False,
        }, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({
        "status": result.status, "actions": list(result.actions),
        "screenshot": capture_result,
        "product_e2e_pass": False, "release_ready": False,
        "store_submission_allowed": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
