"""Explicitly archive a local QA bundle only after checker and GUI/install proof."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

from all_auto.handoff_bridge import validate_bundle

CHECKER_VERDICTS = {"READY_CANDIDATE_NOT_CERTIFIED", "NEEDS_REVIEW", "BLOCKED"}


def read_object(path: Path, limit: int) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("LOCAL_QA_HOLD: missing or unsafe receipt")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("LOCAL_QA_HOLD: receipt root must be object")
    return value


def archive_bundle(inbox: Path, bundle: Path, checker_report: Path,
                   gui_receipt: Path, archive_root: Path) -> dict:
    inbox, bundle, archive_root = inbox.resolve(), bundle.resolve(), archive_root.resolve()
    if (bundle.parent.parent != inbox or bundle.is_symlink() or archive_root.is_symlink()
            or archive_root == inbox or inbox in archive_root.parents):
        raise ValueError("LOCAL_QA_HOLD: unsafe inbox/archive path")
    meta = read_object(bundle / "handoff.json", 32_768)
    info = validate_bundle(bundle, meta.get("factory_head_sha", meta.get("source_sha")))
    checked = read_object(checker_report, 2_000_000)
    checker_receipt = checked.get("receipt")
    if (not isinstance(checker_receipt, dict)
            or checker_receipt.get("checker_verdict") not in CHECKER_VERDICTS):
        raise ValueError("LOCAL_QA_HOLD: completed checker receipt required")
    gui = read_object(gui_receipt, 64_000)
    expected = {
        "request_id": info["request_id"], "product_type": info["product_type"],
        "source_sha": info["source_sha"], "package_sha256": info["package_sha256"],
    }
    if (any(checker_receipt.get(key) != value for key, value in expected.items())
            or any(gui.get(key) != value for key, value in expected.items())):
        raise ValueError("LOCAL_QA_CONFLICT: QA receipt binding mismatch")
    if (gui.get("schema_version") != 1 or gui.get("status") != "PASS"
            or gui.get("install_status") != "PASS"
            or gui.get("gui_launch_status") != "PASS"):
        raise ValueError("LOCAL_QA_HOLD: GUI and installation PASS receipt required")
    destination = archive_root / info["product_type"] / info["slug"] / info["package_sha256"]
    if destination.exists():
        raise ValueError("LOCAL_QA_CONFLICT: archive destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(bundle), str(destination))
    return {"schema_version": 1, "status": "ARCHIVED_LOCAL_QA_COMPLETE",
            **expected, "slug": info["slug"], "archive_path": str(destination),
            "e2e_pass": False, "submitted_to_store": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--checker-report", type=Path, required=True)
    parser.add_argument("--gui-receipt", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = archive_bundle(args.inbox, args.bundle, args.checker_report,
                                args.gui_receipt, args.archive_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(str(exc)[:240], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
