"""Run Windows-checker on verified APP/GAME/GAME_3D local QA MSIX bytes.

Read-only toward packages. Never installs, signs, submits or claims E2E PASS.
Run after local_handoff_pull, with an independently checked-out Windows-checker.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import stat

from all_auto.handoff_bridge import validate_bundle
from all_auto.lane_queue import check_request_conflict

VERDICTS = {
    0: "READY_CANDIDATE_NOT_CERTIFIED",
    1: "NEEDS_REVIEW",
    2: "BLOCKED",
}
# GAME_3D has a distinct immutable transport lane. Windows-checker's CLI
# currently accepts only app/game, so its *preflight* uses game while the
# product_type and receipts remain GAME_3D. Never silently skip this lane.
LANES = {"APP": "app", "GAME": "game", "GAME_3D": "game"}
MAX_QUEUED_BYTES = 2 * 1024 * 1024 * 1024
MAX_HANDOFF_JSON_BYTES = 1_000_000
MAX_CHECKER_REPORT_BYTES = 2_000_000


def _strict_json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("LOCAL_QA_HOLD: duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value):
    raise ValueError("LOCAL_QA_HOLD: non-finite JSON number")


def _read_bounded_json(path: Path, *, limit: int, label: str) -> dict:
    """Read an untrusted receipt once, with no symlink, duplicate or NaN escape.

    Both downloaded handoff.json and the Checker subprocess report cross a
    trust boundary. The caller must not infer a successful GUI/install/E2E QA.
    """
    if path.is_symlink():
        raise ValueError("LOCAL_QA_HOLD: linked " + label)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if (not stat.S_ISREG(metadata.st_mode)
                    or not 0 < metadata.st_size <= limit):
                raise ValueError("LOCAL_QA_HOLD: invalid " + label + " size/type")
            raw = handle.read(limit + 1)
            if len(raw) != metadata.st_size:
                raise ValueError("LOCAL_QA_HOLD: changed/oversize " + label)
    except OSError as exc:
        raise ValueError("LOCAL_QA_HOLD: unavailable " + label) from exc
    try:
        parsed = json.loads(raw.decode("utf-8"),
                            object_pairs_hook=_strict_json_pairs,
                            parse_constant=_reject_json_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("LOCAL_QA_HOLD: invalid " + label + " JSON") from exc
    if type(parsed) is not dict:
        raise ValueError("LOCAL_QA_HOLD: invalid " + label + " object")
    return parsed


def check_local_queue(inbox: Path, checker: Path, reports: Path) -> dict:
    if inbox.is_symlink() or not inbox.is_dir():
        raise ValueError("LOCAL_QA_HOLD: missing or linked inbox")
    if reports.is_symlink() or reports.resolve() == inbox.resolve() or inbox.resolve() in reports.resolve().parents:
        raise ValueError("LOCAL_QA_HOLD: reports must be outside package inbox")
    bundles = []
    for lane, kind in LANES.items():
        root = inbox / lane
        if root.is_symlink():
            raise ValueError("LOCAL_QA_HOLD: linked lane")
        if not root.exists():
            continue
        if not root.is_dir():
            raise ValueError("LOCAL_QA_HOLD: invalid lane")
        for folder in sorted(root.iterdir()):
            if folder.is_symlink() or not folder.is_dir():
                raise ValueError("LOCAL_QA_HOLD: unsafe queue folder")
            bundles.append((lane, kind, folder))
    if not bundles:
        return {"status": "HOLD", "reason": "NO_REAL_MSIX_IN_LOCAL_QA_QUEUE",
                "checked": 0, "e2e_pass": False, "submitted_to_store": 0}
    if len(bundles) > 20:
        raise ValueError("LOCAL_QA_HOLD: too many queued packages")
    runner = checker / "run.py"
    if checker.is_symlink() or runner.is_symlink() or not runner.is_file():
        raise ValueError("LOCAL_QA_HOLD: trusted local Windows-checker checkout missing")
    if reports.exists() and not reports.is_dir():
        raise ValueError("LOCAL_QA_HOLD: report destination invalid")

    # Validate *all* MSIX bytes before executing any checker subprocess.
    checked = []
    total_bytes = 0
    for lane, kind, folder in bundles:
        if (folder / "handoff.json").is_symlink() or (folder / "package.msix").is_symlink():
            raise ValueError("LOCAL_QA_HOLD: linked package")
        meta = _read_bounded_json(
            folder / "handoff.json", limit=MAX_HANDOFF_JSON_BYTES,
            label="handoff")
        # The 3D build HEAD may be a separate post-Identity commit. Never
        # substitute its immutable pre-Identity source_sha for the build HEAD.
        expected = meta.get("factory_build_head",
                            meta.get("factory_head_sha", meta.get("source_sha")))
        info = validate_bundle(folder, expected)
        if (info.get("product_type") != lane
                or info.get("contract_status") != "IMMUTABLE_QA_ONLY"):
            raise ValueError("LOCAL_QA_HOLD: only immutable APP/GAME/GAME_3D queue accepted")
        # The staging gate already rejects global request-id collisions. Recheck
        # independently at the last Checker boundary so a modified inbox or a
        # manually copied bundle cannot bypass that protection. The check also
        # binds Store ID, embedded identity and 3D PFN/SID across revisions.
        check_request_conflict(inbox, info)
        total_bytes += info["package_bytes"]
        if total_bytes > MAX_QUEUED_BYTES:
            raise ValueError("LOCAL_QA_HOLD: local package capacity exceeded")
        checked.append((lane, kind, folder, info))
    reports.mkdir(parents=True, exist_ok=True)
    results = []
    for lane, kind, folder, info in checked:
        name = lane + "-" + info["slug"] + "-" + info["package_sha256"][:12]
        destination = reports / (name + ".checker.json")
        with tempfile.TemporaryDirectory(prefix="checker-qa-") as tmp:
            report = Path(tmp) / "checker.json"
            try:
                proc = subprocess.run(
                    [sys.executable, str(runner), "--cli", "--type", kind,
                     "--msix", str(folder / "package.msix"), "--report", str(report)],
                    cwd=str(checker), capture_output=True, text=True,
                    timeout=180, check=False,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                raise ValueError("LOCAL_QA_HOLD: Windows-checker unavailable: " + type(exc).__name__) from exc
            if proc.returncode not in VERDICTS or not report.is_file():
                raise ValueError("LOCAL_QA_HOLD: Windows-checker failed without valid report")
            parsed = _read_bounded_json(
                report, limit=MAX_CHECKER_REPORT_BYTES, label="checker report")
            if parsed.get("verdict") != VERDICTS[proc.returncode]:
                raise ValueError("LOCAL_QA_HOLD: checker exit/report mismatch")
            receipt = {
                "schema_version": 1, "status": "HOLD",
                "checker_verdict": parsed["verdict"],
                "request_id": info["request_id"], "product_type": lane,
                "checker_cli_type": kind,
                "factory_build_head": info.get("factory_build_head",
                                                info.get("factory_head_sha",
                                                         info["source_sha"])),
                "source_factory": info["source_factory"],
                "source_repository": info["source_repository"],
                "source_branch": info["source_branch"],
                "source_sha": info["source_sha"], "slug": info["slug"],
                "package_sha256": info["package_sha256"],
                "identity": info["identity"],
                "local_gui_qa": "NOT_RUN",
                "official_identity_provenance": "NOT_INDEPENDENTLY_VERIFIED",
                "e2e_pass": False, "submitted_to_store": False,
                "checker_report": destination.name,
            }
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                             dir=reports, delete=False,
                                             prefix=".checker-", suffix=".tmp") as out:
                json.dump({"receipt": receipt, "checker": parsed}, out, ensure_ascii=False, indent=2)
                tmpname = out.name
            os.replace(tmpname, destination)
            results.append(receipt)
    return {"status": "HOLD", "reason": "CHECKER_IS_PREFLIGHT_NOT_WINDOWS_GUI_OR_STORE_CERTIFICATION",
            "checked": len(results), "results": results,
            "e2e_pass": False, "submitted_to_store": 0}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", type=Path, required=True)
    parser.add_argument("--checker", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = check_local_queue(args.inbox, args.checker, args.reports)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["checked"] else 2
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(str(exc)[:240], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
