from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from all_auto.store_product_handoff import normalize_store_product_handoff


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--handoff", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()

    handoff = normalize_store_product_handoff(
        json.loads(a.handoff.read_text(encoding="utf-8-sig"))
    )
    receipt = {
        "schema_version": "local-final-qa-receipt/1",
        "status": "HOLD",
        "store_id": handoff["identity"]["store_id"],
        "source_sha": handoff["product"]["source_sha"],
        "package_sha256": handoff["package"]["package_sha256"],
        "tests_passed": False,
        "package_sha_verified": False,
        "unpacked_exe_sha_verified": False,
        "jp_en_gui_passed": False,
        "dpi_matrix_passed": False,
        "product_specific_acceptance_passed": False,
        "normal_exit_passed": False,
        "package_rebuilt": False,
        "security_bypass_used": False,
        "product_specific_checks": [],
        "notes": "",
    }
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "LOCAL_FINAL_QA_TEMPLATE_CREATED",
        "output": str(a.output),
        "store_id": receipt["store_id"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
