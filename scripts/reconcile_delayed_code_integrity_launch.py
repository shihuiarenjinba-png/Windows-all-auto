from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from all_auto.store_product_handoff import normalize_store_product_handoff
from all_auto.unsigned_exe_launch import (
    UnsignedExeLaunchReceiptError,
    reconcile_delayed_application_control_evidence,
)


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def file_sha256(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--handoff", required=True, type=Path)
    p.add_argument("--launch-receipt", required=True, type=Path)
    p.add_argument("--code-integrity-evidence", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()

    if a.output.exists() or a.output.is_symlink():
        raise SystemExit("refusing to overwrite existing launch reconciliation evidence")

    handoff = normalize_store_product_handoff(load(a.handoff))
    launch = load(a.launch_receipt)
    evidence = load(a.code_integrity_evidence)

    try:
        result = reconcile_delayed_application_control_evidence(
            launch,
            evidence,
            expected_exe_sha256=handoff["package"]["exe_sha256"],
        )
    except UnsignedExeLaunchReceiptError as exc:
        print(f"UNSIGNED_EXE_RECONCILE_HOLD: {str(exc)[:240]}", file=sys.stderr)
        return 2

    result["store_id"] = handoff["identity"]["store_id"]
    result["source_sha"] = handoff["product"]["source_sha"]
    result["package_sha256"] = handoff["package"]["package_sha256"]
    result["original_launch_receipt_sha256"] = file_sha256(a.launch_receipt)
    result["code_integrity_evidence_sha256"] = file_sha256(a.code_integrity_evidence)
    result["reconciliation_write_performed"] = False
    result["original_launch_receipt_overwritten"] = False
    result["code_integrity_evidence_overwritten"] = False

    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "classification": "DELAYED_CODE_INTEGRITY_RECONCILIATION",
                "output": str(a.output),
                "store_write_performed": False,
                "second_launch_performed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
