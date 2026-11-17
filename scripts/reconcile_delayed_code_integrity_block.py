from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from all_auto.unsigned_exe_launch import (
    UnsignedExeLaunchReceiptError,
    reconcile_delayed_application_control_evidence,
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
    p.add_argument("--launch-receipt", required=True, type=Path)
    p.add_argument("--code-integrity-evidence", required=True, type=Path)
    p.add_argument("--expected-exe-sha256", required=True)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()

    if a.output.exists() or a.output.is_symlink():
        raise SystemExit("refusing to overwrite existing launch reconciliation evidence")

    launch = load(a.launch_receipt)
    evidence = load(a.code_integrity_evidence)

    try:
        result = reconcile_delayed_application_control_evidence(
            launch,
            evidence,
            expected_exe_sha256=a.expected_exe_sha256,
        )
    except UnsignedExeLaunchReceiptError as exc:
        print(f"UNSIGNED_EXE_RECONCILE_HOLD: {str(exc)[:240]}", file=sys.stderr)
        return 2

    result["original_launch_receipt_sha256"] = sha256_file(a.launch_receipt)
    result["code_integrity_evidence_sha256"] = sha256_file(a.code_integrity_evidence)
    result["original_launch_receipt_path"] = str(a.launch_receipt)
    result["code_integrity_evidence_path"] = str(a.code_integrity_evidence)

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
                "original_receipt_preserved": True,
                "second_launch_performed": False,
                "store_write_performed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
