"""Deterministic implementations for locally trusted QA test IDs.

This module accepts no arbitrary command or argument list from an LLM.  The
supervisor invokes it only through the hash-pinned trusted catalog.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_hash(path: Path, expected: str) -> int:
    actual = _sha256(path)
    print("ARTIFACT_SHA256=" + actual)
    if actual != expected:
        print("ARTIFACT_HASH_MISMATCH", file=sys.stderr)
        return 2
    print("ARTIFACT_HASH_VERIFIED")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-id", required=True,
                        choices=("ARTIFACT_HASH",))
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--expected-sha")
    args = parser.parse_args(argv)
    artifact = args.artifact.resolve()
    if not artifact.is_file() or args.artifact.is_symlink():
        raise SystemExit("TRUSTED_TEST_HOLD: artifact is missing or linked")
    if not args.expected_sha:
        raise SystemExit("TRUSTED_TEST_HOLD: expected SHA is required")
    return artifact_hash(artifact, args.expected_sha)


if __name__ == "__main__":
    raise SystemExit(main())
