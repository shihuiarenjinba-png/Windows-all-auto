from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from all_auto.pre_store_static_block import (
    PreStoreStaticBlockError,
    build_pre_store_static_block_receipt,
)


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--handoff", required=True, type=Path)
    p.add_argument("--artifact-receipt", required=True, type=Path)
    p.add_argument("--launch-reconciliation", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()

    if a.output.exists() or a.output.is_symlink():
        raise SystemExit("refusing to overwrite existing pre-Store static QA evidence")

    try:
        result = build_pre_store_static_block_receipt(
            load(a.handoff),
            load(a.artifact_receipt),
            load(a.launch_reconciliation),
        )
    except (PreStoreStaticBlockError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"PRE_STORE_STATIC_BLOCK_HOLD: {str(exc)[:240]}", file=sys.stderr)
        return 2

    result["artifact_receipt_sha256"] = sha256_file(a.artifact_receipt)
    result["launch_reconciliation_receipt_sha256"] = sha256_file(a.launch_reconciliation)
    result["artifact_receipt_path"] = str(a.artifact_receipt)
    result["launch_reconciliation_path"] = str(a.launch_reconciliation)

    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "output": str(a.output),
                "private_store_signing_lane_candidate": True,
                "store_write_performed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
