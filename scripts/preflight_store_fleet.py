from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from uploader.fleet_preflight import build_fleet_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only SHA/manifest preflight for the six existing Store Drafts.")
    parser.add_argument("--package-root", type=Path, required=True, help="Root folder containing the seven downloaded MSIX artifacts")
    parser.add_argument("--config-root", type=Path, default=Path("uploader/config"))
    parser.add_argument("--output", type=Path, default=Path("store-fleet-preflight.json"))
    args = parser.parse_args()

    report = build_fleet_preflight(args.package_root.resolve(), args.config_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["static_package_verifications_passed"] == 6 else 2


if __name__ == "__main__":
    raise SystemExit(main())
