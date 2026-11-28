"""Read-only diagnostics for the authenticated loopback Edge CDP session."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from uploader.core import UploadError, validate_config
from uploader.partner_center_browser import PartnerCenterCDPConnection
from uploader.run import resolve_job_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect CDP tabs without navigating or changing them.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path)
    source.add_argument("--product")
    parser.add_argument("--cdp-url", default=os.environ.get("PARTNER_CENTER_CDP_URL", "http://127.0.0.1:9223"))
    args = parser.parse_args()
    connection = None
    try:
        config_path = resolve_job_config(config_path=args.config, product_key=args.product)
        config = validate_config(json.loads(config_path.read_text(encoding="utf-8")))
        connection = PartnerCenterCDPConnection(args.cdp_url, config)
        connection.attach()
        report = connection.doctor()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if str(report.get("status", "")).startswith("READY_") else 2
    except (UploadError, OSError, ValueError, json.JSONDecodeError) as exc:
        payload = {"status": "HOLD_CDP_OR_CONFIG", "error_code": getattr(exc, "code", "DIAGNOSTIC_FAILED"),
                   "message": str(exc), "read_only": True, "navigation_performed": False,
                   "clicks_performed": False, "save_performed": False}
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
        return 2
    finally:
        if connection is not None:
            connection.__exit__(None, None, None)


if __name__ == "__main__":
    raise SystemExit(main())
