"""Run the existing Windows-checker on real, verified local APP/GAME MSIX bytes.

Read-only toward packages. Never installs, signs, submits or claims E2E PASS.
Run after local_handoff_pull, with an independently checked-out Windows-checker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from all_auto.handoff_bridge import validate_bundle

VERDICTS = {
    0: "READY_CANDIDATE_NOT_CERTIFIED",
    1: "NEEDS_REVIEW",
    2: "BLOCKED",
}
LANES = {"APP": "app", "GAME": "game"}
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix="." + path.name + ".", suffix=".tmp",
                                     delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def checker_version(checker: Path, runner: Path) -> str:
    runner_hash = hashlib.sha256(runner.read_bytes()).hexdigest()
    try:
        root = subprocess.run(["git", "-C", str(checker), "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, timeout=20, check=False)
        proc = subprocess.run(["git", "-C", str(checker), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        root = proc = None
    if (root is not None and proc is not None and root.returncode == 0 and proc.returncode == 0
            and Path(root.stdout.strip()).resolve() == checker.resolve()
            and SHA40.fullmatch(proc.stdout.strip())):
        status = subprocess.run(["git", "-C", str(checker), "status", "--porcelain"],
                                capture_output=True, text=True, timeout=20, check=False)
        if status.returncode or status.stdout.strip():
            raise ValueError("LOCAL_QA_HOLD: trusted Windows-checker checkout must be clean")
        return "git:" + proc.stdout.strip() + ":run.py-sha256:" + runner_hash
    return "run.py-sha256:" + runner_hash


def load_ledger(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": 1, "entries": {}}
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError("LOCAL_QA_HOLD: unsafe QA ledger")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or not isinstance(value.get("entries"), dict)
            or len(value["entries"]) > 10_000):
        raise ValueError("LOCAL_QA_HOLD: invalid QA ledger")
    return value


def qa_key(info: dict, version: str) -> str:
    fields = {
        "request_id": info["request_id"], "product_type": info["product_type"],
        "source_sha": info["source_sha"],
        "factory_head_sha": info.get("factory_head_sha", info["source_sha"]),
        "package_sha256": info["package_sha256"], "checker_version": version,
    }
    raw = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def check_local_queue(inbox: Path, checker: Path, reports: Path,
                      ledger_path: Path | None = None) -> dict:
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
    ledger_path = ledger_path or (reports / "local-qa-ledger.json")
    if (ledger_path.is_symlink() or ledger_path.resolve() == inbox.resolve()
            or inbox.resolve() in ledger_path.resolve().parents):
        raise ValueError("LOCAL_QA_HOLD: ledger must be outside package inbox")
    version = checker_version(checker, runner)
    ledger = load_ledger(ledger_path)

    # Validate *all* MSIX bytes before executing any checker subprocess.
    checked = []
    seen = {}
    for lane, kind, folder in bundles:
        if (folder / "handoff.json").is_symlink() or (folder / "package.msix").is_symlink():
            raise ValueError("LOCAL_QA_HOLD: linked package")
        meta = json.loads((folder / "handoff.json").read_text(encoding="utf-8"))
        expected = meta.get("factory_head_sha", meta.get("source_sha"))
        info = validate_bundle(folder, expected)
        if info.get("product_type") != lane or info.get("contract_status") != "IMMUTABLE_QA_ONLY":
            raise ValueError("LOCAL_QA_HOLD: only immutable APP/GAME queue accepted")
        request = info["request_id"]
        prior = seen.get((lane, request))
        if prior is not None and prior != info["source_sha"]:
            raise ValueError("LOCAL_QA_CONFLICT: request_id reused with changed source SHA")
        seen[(lane, request)] = info["source_sha"]
        checked.append((lane, kind, folder, info))
    reports.mkdir(parents=True, exist_ok=True)
    results = []
    executed = 0
    skipped = 0
    for lane, kind, folder, info in checked:
        key = qa_key(info, version)
        name = (lane + "-" + info["slug"] + "-" + info["package_sha256"][:12]
                + "-" + key[:12])
        destination = reports / (name + ".checker.json")
        prior = ledger["entries"].get(key)
        if (isinstance(prior, dict) and prior.get("status") == "CHECKED"
                and prior.get("report") == destination.name and destination.is_file()):
            saved = json.loads(destination.read_text(encoding="utf-8"))
            receipt = saved.get("receipt") if isinstance(saved, dict) else None
            if (not isinstance(receipt, dict) or receipt.get("package_sha256") != info["package_sha256"]
                    or receipt.get("checker_version") != version
                    or receipt.get("request_id") != info["request_id"]):
                raise ValueError("LOCAL_QA_CONFLICT: ledger/report binding mismatch")
            results.append({**receipt, "deduplicated": True})
            skipped += 1
            continue
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
            if proc.returncode not in VERDICTS or not report.is_file() or report.stat().st_size > 2_000_000:
                raise ValueError("LOCAL_QA_HOLD: Windows-checker failed without valid report")
            parsed = json.loads(report.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict) or parsed.get("verdict") != VERDICTS[proc.returncode]:
                raise ValueError("LOCAL_QA_HOLD: checker exit/report mismatch")
            receipt = {
                "schema_version": 1, "status": "HOLD",
                "checker_verdict": parsed["verdict"],
                "request_id": info["request_id"], "product_type": lane,
                "source_factory": info["source_factory"],
                "source_repository": info["source_repository"],
                "source_branch": info["source_branch"],
                "source_sha": info["source_sha"], "slug": info["slug"],
                "factory_head_sha": info.get("factory_head_sha", info["source_sha"]),
                "package_sha256": info["package_sha256"],
                "checker_version": version,
                "identity": info["identity"],
                "local_gui_qa": "NOT_RUN",
                "official_identity_provenance": "NOT_INDEPENDENTLY_VERIFIED",
                "e2e_pass": False, "submitted_to_store": False,
                "checker_report": destination.name,
                "deduplicated": False,
            }
            atomic_json(destination, {"receipt": receipt, "checker": parsed})
            ledger["entries"][key] = {
                "status": "CHECKED", "request_id": info["request_id"],
                "product_type": lane, "source_sha": info["source_sha"],
                "factory_head_sha": info.get("factory_head_sha", info["source_sha"]),
                "package_sha256": info["package_sha256"], "checker_version": version,
                "report": destination.name,
            }
            atomic_json(ledger_path, ledger)
            results.append(receipt)
            executed += 1
    return {"status": "HOLD", "reason": "CHECKER_IS_PREFLIGHT_NOT_WINDOWS_GUI_OR_STORE_CERTIFICATION",
            "checked": len(results), "executed": executed, "skipped": skipped,
            "results": results,
            "e2e_pass": False, "submitted_to_store": 0}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", type=Path, required=True)
    parser.add_argument("--checker", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args(argv)
    try:
        result = check_local_queue(args.inbox, args.checker, args.reports, args.ledger)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["checked"] else 2
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(str(exc)[:240], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
