from __future__ import annotations

import argparse
from hashlib import sha256
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
from all_auto.store_product_handoff import (
    StoreHandoffError,
    apply_pre_store_static_qa_receipt,
    normalize_store_product_handoff,
)
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


def write_new(path: Path, value: dict) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to overwrite existing evidence: {path.name}")
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--handoff", required=True, type=Path)
    p.add_argument("--artifact-receipt", required=True, type=Path)
    p.add_argument("--launch-receipt", required=True, type=Path)
    p.add_argument("--code-integrity-evidence", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    a = p.parse_args()

    if a.output_dir.exists():
        if a.output_dir.is_symlink() or any(a.output_dir.iterdir()):
            raise SystemExit("refusing non-empty or symlink output directory")
    else:
        a.output_dir.mkdir(parents=True, exist_ok=False)

    try:
        handoff = load(a.handoff)
        artifact = load(a.artifact_receipt)
        launch = load(a.launch_receipt)
        ci = load(a.code_integrity_evidence)

        normalized = normalize_store_product_handoff(handoff)
        reconciled = reconcile_delayed_application_control_evidence(
            launch,
            ci,
            expected_exe_sha256=normalized["package"]["exe_sha256"],
        )
        reconciled["input_bindings"] = {
            "handoff_sha256": file_sha256(a.handoff),
            "artifact_receipt_sha256": file_sha256(a.artifact_receipt),
            "launch_receipt_sha256": file_sha256(a.launch_receipt),
            "code_integrity_evidence_sha256": file_sha256(a.code_integrity_evidence),
        }

        pre_store = build_pre_store_static_block_receipt(
            handoff,
            artifact,
            reconciled,
        )
        pre_store["input_bindings"] = {
            "artifact_receipt_sha256": file_sha256(a.artifact_receipt),
            "launch_reconciliation_sha256": sha256(
                (json.dumps(reconciled, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            ).hexdigest(),
        }

        bound = apply_pre_store_static_qa_receipt(handoff, pre_store)
        if bound["qa"]["private_store_signing_lane_ready"] is not True:
            raise ValueError("pre-Store static block did not open private Store signing lane")
        if bound["qa"]["local_final_pass"] is not False:
            raise ValueError("pre-Store static block must not mark local final QA PASS")
        if bound["qa"]["store_signed_install_pass"] is not False:
            raise ValueError("pre-Store static block must not mark Store-signed QA PASS")

        reconciled_path = a.output_dir / "unsigned-exe-launch-reconciliation-receipt.json"
        pre_store_path = a.output_dir / "pre-store-static-qa-receipt.json"
        handoff_path = a.output_dir / "handoff-after-pre-store-static-block.json"

        write_new(reconciled_path, reconciled)
        write_new(pre_store_path, pre_store)
        write_new(handoff_path, bound)

        print(
            json.dumps(
                {
                    "status": "PRIVATE_STORE_SIGNING_LANE_READY",
                    "reconciliation_receipt": str(reconciled_path),
                    "pre_store_static_receipt": str(pre_store_path),
                    "bound_handoff": str(handoff_path),
                    "local_final_qa_pass": False,
                    "store_signed_install_pass": False,
                    "store_write_performed": False,
                    "second_launch_performed": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (
        ValueError,
        OSError,
        json.JSONDecodeError,
        PreStoreStaticBlockError,
        StoreHandoffError,
        UnsignedExeLaunchReceiptError,
    ) as exc:
        print(f"APPLICATION_CONTROL_BLOCK_LANE_HOLD: {str(exc)[:240]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
