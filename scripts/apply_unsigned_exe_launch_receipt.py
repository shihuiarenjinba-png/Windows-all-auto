from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from all_auto.store_product_handoff import normalize_store_product_handoff
from all_auto.unsigned_exe_launch import (
    UnsignedExeLaunchReceiptError,
    bind_unsigned_launch_to_local_qa,
)


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--handoff", required=True, type=Path)
    p.add_argument("--qa-template", required=True, type=Path)
    p.add_argument("--launch-receipt", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()

    if a.output.exists() or a.output.is_symlink():
        raise SystemExit("refusing to overwrite existing launch-bound QA evidence")

    handoff = normalize_store_product_handoff(load(a.handoff))
    qa = load(a.qa_template)
    launch = load(a.launch_receipt)

    try:
        result = bind_unsigned_launch_to_local_qa(
            qa,
            launch,
            expected_exe_sha256=handoff["package"]["exe_sha256"],
        )
    except UnsignedExeLaunchReceiptError as exc:
        print(f"UNSIGNED_EXE_LAUNCH_HOLD: {str(exc)[:240]}", file=sys.stderr)
        return 2

    result["store_id"] = handoff["identity"]["store_id"]
    result["source_sha"] = handoff["product"]["source_sha"]
    result["package_sha256"] = handoff["package"]["package_sha256"]
    result["unsigned_exe_launch_bound"] = True
    result["store_actions"] = {
        "package_upload": "NOT_EXECUTED",
        "certification": "NOT_EXECUTED",
        "publish": "NOT_EXECUTED",
    }

    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "LOCAL_QA_REMAINS_HOLD",
                "launch_status": launch.get("status"),
                "output": str(a.output),
                "store_write_performed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
