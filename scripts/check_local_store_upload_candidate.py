from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from all_auto.store_product_handoff import StoreHandoffError, normalize_store_product_handoff


DRAFT_URL_RE = re.compile(
    r"^https://partner\.microsoft\.com/en-us/dashboard/products/"
    r"(?P<store_id>[^/]+)/submissions/(?P<draft_id>\d+)$"
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def evaluate(handoff: dict, package_path: Path, assets_dir: Path | None = None) -> dict:
    try:
        normalized = normalize_store_product_handoff(handoff)
    except StoreHandoffError as exc:
        return {
            "schema_version": "store-preupload-readiness/1",
            "status": "HOLD_EXACT_PACKAGE_MISMATCH",
            "reason": str(exc),
            "package_upload_executed": False,
            "certification_executed": False,
            "published": False,
        }

    expected_sha = normalized["package"]["package_sha256"]
    expected_name = normalized["package"]["file_name"]
    store_id = normalized["identity"]["store_id"]

    base = {
        "schema_version": "store-preupload-readiness/1",
        "store_id": store_id,
        "source_sha": normalized["product"]["source_sha"],
        "expected_package_sha256": expected_sha,
        "expected_package_filename": expected_name,
        "package_path": str(package_path),
        "package_upload_executed": False,
        "certification_executed": False,
        "published": False,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    if not package_path.is_file():
        return {**base, "status": "HOLD_LOCAL_MSIX_NOT_FOUND", "reason": "local package file does not exist"}

    stat = package_path.stat()
    actual_sha = sha256_file(package_path)
    base.update(
        {
            "package_size": stat.st_size,
            "package_last_write_time_utc": datetime.fromtimestamp(
                stat.st_mtime, timezone.utc
            ).isoformat(),
            "actual_package_sha256": actual_sha,
            "package_filename": package_path.name,
        }
    )

    if actual_sha.lower() != expected_sha.lower():
        return {**base, "status": "HOLD_LOCAL_MSIX_SHA_MISMATCH", "reason": "local package SHA256 does not match frozen handoff"}

    if package_path.name != expected_name:
        return {**base, "status": "HOLD_EXACT_PACKAGE_MISMATCH", "reason": "local package filename does not match frozen handoff"}

    draft_id = str(normalized["product"].get("draft_id") or "").strip()
    draft_url = str(normalized["product"].get("draft_url") or "").strip()
    start_completed = normalized["approvals"].get("initial_submission_start_completed") is True
    if not (start_completed and draft_id.isdigit() and draft_url):
        return {
            **base,
            "status": "HOLD_SUBMISSION_RECONCILE_REQUIRED",
            "reason": "exact Partner Center Draft has not been bound to the handoff",
            "draft_id": draft_id,
            "draft_url": draft_url,
        }

    match = DRAFT_URL_RE.fullmatch(draft_url)
    if (
        match is None
        or match.group("store_id") != store_id
        or match.group("draft_id") != draft_id
    ):
        return {
            **base,
            "status": "HOLD_EXACT_PACKAGE_MISMATCH",
            "reason": "bound Draft URL does not match Store ID and Draft ID",
            "draft_id": draft_id,
            "draft_url": draft_url,
        }

    asset_state = "NOT_CHECKED"
    if assets_dir is not None:
        if not assets_dir.is_dir():
            return {
                **base,
                "status": "HOLD_STORE_ASSETS",
                "reason": "Store assets directory does not exist",
                "draft_id": draft_id,
                "draft_url": draft_url,
                "assets_dir": str(assets_dir),
            }
        files = [p for p in assets_dir.iterdir() if p.is_file()]
        if not files:
            return {
                **base,
                "status": "HOLD_STORE_ASSETS",
                "reason": "Store assets directory is empty",
                "draft_id": draft_id,
                "draft_url": draft_url,
                "assets_dir": str(assets_dir),
            }
        asset_state = "PRESENT"

    return {
        **base,
        "status": "READY_FOR_MSIX_UPLOAD_APPROVAL",
        "reason": "",
        "draft_id": draft_id,
        "draft_url": draft_url,
        "assets_check": asset_state,
        "assets_dir": str(assets_dir) if assets_dir is not None else "",
        "exact_package_match": True,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--handoff", required=True, type=Path)
    p.add_argument("--package-path", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--assets-dir", type=Path)
    a = p.parse_args()

    handoff = json.loads(a.handoff.read_text(encoding="utf-8"))
    result = evaluate(handoff, a.package_path, a.assets_dir)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(a.output)}, ensure_ascii=False))
    return 0 if result["status"] == "READY_FOR_MSIX_UPLOAD_APPROVAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
