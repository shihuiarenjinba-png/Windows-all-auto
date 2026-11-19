"""CLI for one process-scoped trusted UI Automation action."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from all_auto.trusted_uia import TrustedUIAExecutor, TrustedUIAHold, UIA_ACTIONS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True, choices=sorted(UIA_ACTIONS))
    parser.add_argument("--params-json", required=True)
    parser.add_argument("--process-id", required=True, type=int)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--build-root", type=Path)
    args = parser.parse_args(argv)
    try:
        params = json.loads(args.params_json)
        result = TrustedUIAExecutor(build_root=args.build_root).execute(
            action=args.action, params=params, process_id=args.process_id,
            artifact_path=args.artifact,
            expected_sha256=args.expected_sha256,
        )
    except (json.JSONDecodeError, TrustedUIAHold) as exc:
        print(json.dumps({
            "status": "TRUSTED_UIA_HOLD",
            "action": args.action,
            "reason": str(exc),
        }, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
