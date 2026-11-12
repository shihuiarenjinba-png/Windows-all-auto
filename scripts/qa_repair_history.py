"""Add a regression-verified, secret-safe repair to the local RAG history."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from qa_ai.rag import RepairHistory


def _load(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ValueError("invalid repair record file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("repair record must be an object")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--index-name", default="index-v1-nomic")
    parser.add_argument("--embedding-model", default="nomic-embed-text:latest")
    args = parser.parse_args(argv)
    try:
        history = RepairHistory(args.db, index_name=args.index_name,
                                embedding_model=args.embedding_model)
        record_id = history.add_verified(_load(args.record))
        print(json.dumps({"status": "VERIFIED_REPAIR_INDEXED", "id": record_id,
                          "index_name": args.index_name,
                          "embedding_model": args.embedding_model}))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print((type(exc).__name__ + ": " + str(exc))[:500], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
