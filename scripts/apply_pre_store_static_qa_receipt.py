from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from all_auto.store_product_handoff import apply_pre_store_static_qa_receipt


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--handoff", required=True, type=Path)
    p.add_argument("--receipt", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()

    handoff = json.loads(a.handoff.read_text(encoding="utf-8"))
    receipt = json.loads(a.receipt.read_text(encoding="utf-8"))
    normalized = apply_pre_store_static_qa_receipt(handoff, receipt)

    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "PRE_STORE_STATIC_QA_BOUND",
        "private_store_signing_lane_ready": normalized["qa"]["private_store_signing_lane_ready"],
        "missing": normalized["missing_for_draft"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
