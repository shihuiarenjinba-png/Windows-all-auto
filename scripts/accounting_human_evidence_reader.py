"""Read-only local evidence byte verifier for accounting beginner QA.

This authenticates local file hashes and PNG structure, NOT a physical reviewer,
a signed MSIX, Checker correctness, GUI execution or E2E readiness.
The independent human reviewer remains a separate required trust boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import zlib

from scripts.accounting_human_qa_gate import (
    AccountingHumanQAHold, SCENARIO_ASSERTIONS,
)

MAX_EVIDENCE_BYTES = 256 * 1024
MAX_PNG_BYTES = 12 * 1024 * 1024
MAX_CHECKER_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 2 * 1024 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _hold(code: str):
    raise AccountingHumanQAHold(code)


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _hold("HOLD_ACCOUNTING_EVIDENCE_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_constant(_value):
    _hold("HOLD_ACCOUNTING_EVIDENCE_JSON_INVALID")


def _check_no_symlink(path: Path):
    path = path.absolute()
    for component in (path, *path.parents):
        if component.is_symlink():
            _hold("HOLD_ACCOUNTING_EVIDENCE_SYMLINK")


def _read_file(path: Path, limit: int) -> bytes:
    _check_no_symlink(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            meta = os.fstat(handle.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > limit:
                _hold("HOLD_ACCOUNTING_EVIDENCE_FILE_INVALID")
            data = handle.read(limit + 1)
            if len(data) > limit or len(data) != meta.st_size:
                _hold("HOLD_ACCOUNTING_EVIDENCE_FILE_INVALID")
            return data
    except AccountingHumanQAHold:
        raise
    except (OSError, ValueError):
        _hold("HOLD_ACCOUNTING_EVIDENCE_FILE_UNAVAILABLE")


def _png_dimensions(data: bytes):
    if not data.startswith(PNG_SIGNATURE):
        _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
    offset = len(PNG_SIGNATURE)
    first = True
    dimensions = None
    seen_idat = False
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
        chunk_type = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(chunk_type + payload) & 0xffffffff != crc:
            _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
        if first:
            if chunk_type != b"IHDR" or length != 13:
                _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
            dimensions = struct.unpack_from(">II", payload)
            first = False
        if chunk_type == b"IDAT":
            seen_idat = True
        if chunk_type == b"IEND":
            if length != 0 or end != len(data) or not seen_idat:
                _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")
            return dimensions
        offset = end
    _hold("HOLD_ACCOUNTING_EVIDENCE_PNG_INVALID")


def read_local_accounting_human_evidence(
    job: dict, *, evidence_root: str | Path,
    package_path: str | Path, checker_report_path: str | Path,
) -> dict:
    """Return local evidence only when every exact file digest is verified.

    Evidence layout is fixed: evidence.json and screenshots/<scenario>.png.
    The job and evidence are still validated by validate_accounting_human_qa.
    Never trust the returned data as a GUI_QA_PASS or E2E_PASS.
    """
    if type(job) is not dict:
        _hold("HOLD_ACCOUNTING_EVIDENCE_JOB_INVALID")
    root = Path(evidence_root).absolute()
    _check_no_symlink(root)
    if not root.is_dir():
        _hold("HOLD_ACCOUNTING_EVIDENCE_ROOT_INVALID")
    try:
        evidence = json.loads(
            _read_file(root / "evidence.json", MAX_EVIDENCE_BYTES).decode("utf-8"),
            object_pairs_hook=_strict_pairs, parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError):
        _hold("HOLD_ACCOUNTING_EVIDENCE_JSON_INVALID")
    if type(evidence) is not dict or type(evidence.get("scenarios")) is not dict:
        _hold("HOLD_ACCOUNTING_EVIDENCE_SCHEMA")
    if set(evidence["scenarios"]) != set(SCENARIO_ASSERTIONS):
        _hold("HOLD_ACCOUNTING_EVIDENCE_SCHEMA")
    if type(job.get("package_sha256")) is not str or type(job.get("checker_report_sha256")) is not str:
        _hold("HOLD_ACCOUNTING_EVIDENCE_JOB_INVALID")
    package = _read_file(Path(package_path), MAX_PACKAGE_BYTES)
    if not package.startswith(b"PK\x03\x04") or hashlib.sha256(package).hexdigest() != job["package_sha256"]:
        _hold("HOLD_ACCOUNTING_EVIDENCE_PACKAGE_MISMATCH")
    checker = _read_file(Path(checker_report_path), MAX_CHECKER_BYTES)
    if hashlib.sha256(checker).hexdigest() != job["checker_report_sha256"]:
        _hold("HOLD_ACCOUNTING_EVIDENCE_CHECKER_MISMATCH")
    seen = set()
    for name in SCENARIO_ASSERTIONS:
        screenshot = _read_file(root / "screenshots" / (name + ".png"), MAX_PNG_BYTES)
        if _png_dimensions(screenshot) != (1024, 768):
            _hold("HOLD_ACCOUNTING_EVIDENCE_RESOLUTION")
        digest = hashlib.sha256(screenshot).hexdigest()
        scenario = evidence["scenarios"][name]
        if type(scenario) is not dict or scenario.get("screenshot_sha256") != digest:
            _hold("HOLD_ACCOUNTING_EVIDENCE_SCREENSHOT_MISMATCH")
        if digest in seen:
            _hold("HOLD_ACCOUNTING_EVIDENCE_SCREENSHOT_REUSED")
        seen.add(digest)
    return evidence
