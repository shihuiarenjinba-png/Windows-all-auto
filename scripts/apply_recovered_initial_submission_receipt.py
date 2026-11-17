from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from all_auto.store_product_handoff import apply_recovered_initial_submission_receipt


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--handoff", required=True, type=Path)
    p.add_argument("--receipt", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    handoff = json.loads(a.handoff.read_text(encoding="utf-8"))
    receipt = json.loads(a.receipt.read_text(encoding="utf-8"))
    normalized = apply_recovered_initial_submission_receipt(handoff, receipt)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "RECOVERED_INITIAL_DRAFT_APPLIED",
                "draft_id": normalized["product"]["draft_id"],
                "draft_url": normalized["product"]["draft_url"],
                "source": normalized["product"]["initial_submission_start_source"],
                "missing": normalized["missing_for_draft"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
