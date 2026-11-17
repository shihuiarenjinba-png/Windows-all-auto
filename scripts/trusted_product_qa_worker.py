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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--action-log", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        plan = load_bound_plan(args.plan)
        result = execute_bound_product_plan(
            plan, artifact_path=args.artifact, action_log=args.action_log,
        )
    except (ProductQAExecutionHold, ValueError) as exc:
        print(json.dumps({
            "status": "PRODUCT_QA_EXECUTION_HOLD", "reason": str(exc),
            "product_e2e_pass": False, "release_ready": False,
            "store_submission_allowed": False,
        }, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps({
        "status": result.status, "actions": list(result.actions),
        "product_e2e_pass": False, "release_ready": False,
        "store_submission_allowed": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
