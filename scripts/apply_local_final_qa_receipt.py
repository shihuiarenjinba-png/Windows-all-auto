from __future__ import annotations
import argparse
import json
from pathlib import Path

from all_auto.store_product_handoff import apply_local_final_qa_receipt


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--handoff", required=True, type=Path)
    p.add_argument("--receipt", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()

    handoff = json.loads(a.handoff.read_text(encoding="utf-8-sig"))
    receipt = json.loads(a.receipt.read_text(encoding="utf-8-sig"))
    normalized = apply_local_final_qa_receipt(handoff, receipt)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "LOCAL_FINAL_QA_APPLIED",
        "store_id": normalized["identity"]["store_id"],
        "source_sha": normalized["product"]["source_sha"],
        "package_sha256": normalized["package"]["package_sha256"],
        "missing": normalized["missing_for_draft"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
