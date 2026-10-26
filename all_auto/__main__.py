"""Command-line entry point. No Store submission or network writes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import export_results, preflight


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="windows-all-auto")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("preflight", help="Offline evidence check; never uploads")
    check.add_argument("--manifest", required=True, type=Path)
    check.add_argument("--out", required=True, type=Path)
    commands.add_parser("gui", help="Windows GUI for offline checks")
    opts = parser.parse_args(argv)
    if opts.command == "gui":
        from .gui import start
        start()
        return 0
    try:
        content = json.loads(opts.manifest.read_text(encoding="utf-8"))
        result = preflight(content, opts.manifest.resolve().parent)
        export_results(result, opts.out)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"MANIFEST ERROR: {exc}", file=sys.stderr)
        return 3
    print(f"OFFLINE PREFLIGHT ONLY — products={result['total']} {result['counts']}")
    print(f"JSON/Markdown results: {opts.out}")
    return 2 if result["counts"]["BLOCKED"] else 1 if result["counts"]["HOLD"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
