"""Run the existing Windows-checker on real, verified local APP/GAME MSIX bytes.

Read-only toward packages. Never installs, signs, submits or claims E2E PASS.
Run after local_handoff_pull, with an independently checked-out Windows-checker.
"""
from __future__ import annotations

import argparse
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
CENTRAL_REPOSITORY = "shihuiarenjinba-png/Windows-all-auto"
ARTIFACT_PREFIX = "verified-msix-local-qa-"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")


def _load_local_custody_index(inbox: Path) -> dict:
    """Load create-only receipts emitted by local_handoff_pull.

    The package-level Factory receipt alone is insufficient here: this gate
    also requires the independent central GitHub archive -> local byte-custody
    receipt before it will invoke Windows-checker.
    """
    root = inbox / ".artifact-custody"
    if root.is_symlink() or not root.is_dir():
        raise ValueError("LOCAL_QA_HOLD: verified local artifact custody receipt directory missing")
    paths = sorted(root.iterdir())
    if not paths or len(paths) > 1000:
        raise ValueError("LOCAL_QA_HOLD: verified local artifact custody receipts missing or excessive")

    index = {}
    request_records = {}
    for path in paths:
        if (path.is_symlink() or not path.is_file() or path.suffix != ".json"
                or not path.stem.isdecimal() or int(path.stem) <= 0
                or path.stat().st_size > 256 * 1024):
            raise ValueError("LOCAL_QA_HOLD: invalid local artifact custody receipt file")
        data = json.loads(path.read_text(encoding="utf-8"))
        artifact_id = data.get("artifact_id") if isinstance(data, dict) else None
        run_id = data.get("run_id") if isinstance(data, dict) else None
        if (not isinstance(data, dict)
                or data.get("status") != "CUSTODY_VERIFIED_ONLY"
                or data.get("e2e_pass") is not False
                or data.get("repository") != CENTRAL_REPOSITORY
                or type(artifact_id) is not int or artifact_id <= 0
                or str(artifact_id) != path.stem
                or type(run_id) is not int or run_id <= 0
                or not isinstance(data.get("artifact_name"), str)
                or not data["artifact_name"].startswith(ARTIFACT_PREFIX)
                or not isinstance(data.get("run_head_sha"), str)
                or not SHA40.fullmatch(data["run_head_sha"])
                or not isinstance(data.get("archive_sha256"), str)
                or not SHA64.fullmatch(data["archive_sha256"])
                or not isinstance(data.get("queue_sha256"), str)
                or not SHA64.fullmatch(data["queue_sha256"])
                or data.get("signature") != "NOT_VERIFIED"
                or data.get("checker") != "NOT_VERIFIED"
                or data.get("gui") != "NOT_VERIFIED"
                or data.get("local_pull_status") != "VERIFIED"):
            raise ValueError("LOCAL_QA_HOLD: invalid local artifact custody receipt")

        packages = data.get("packages")
        if not isinstance(packages, list) or not 1 <= len(packages) <= 20:
            raise ValueError("LOCAL_QA_HOLD: invalid local artifact custody package list")
        for package in packages:
            if not isinstance(package, dict):
                raise ValueError("LOCAL_QA_HOLD: invalid local artifact custody package record")
            product_type = package.get("product_type")
            request_id = package.get("request_id")
            source_sha = package.get("source_sha")
            slug = package.get("slug")
            package_sha = package.get("package_sha256")
            local_sha = package.get("local_sha256")
            package_bytes = package.get("package_bytes")
            if (product_type not in LANES
                    or not isinstance(request_id, str) or not 4 <= len(request_id) <= 128
                    or not isinstance(source_sha, str) or not SHA40.fullmatch(source_sha)
                    or not isinstance(slug, str) or not slug
                    or not isinstance(package_sha, str) or not SHA64.fullmatch(package_sha)
                    or local_sha != package_sha
                    or type(package_bytes) is not int or package_bytes <= 0
                    or package.get("local_pull_status") != "VERIFIED"):
                raise ValueError("LOCAL_QA_HOLD: invalid local artifact custody package record")

            request_key = (product_type, request_id)
            request_record = (source_sha, slug, package_sha, package_bytes)
            prior_request = request_records.get(request_key)
            if prior_request is not None and prior_request != request_record:
                raise ValueError("LOCAL_QA_CONFLICT: local custody request reused with changed package provenance")
            request_records[request_key] = request_record

            key = (product_type, request_id, source_sha, slug, package_sha)
            prior = index.get(key)
            if prior is not None and prior["package_bytes"] != package_bytes:
                raise ValueError("LOCAL_QA_CONFLICT: local custody package size changed")
            if prior is None:
                prior = {"package_bytes": package_bytes, "artifact_ids": set()}
                index[key] = prior
            prior["artifact_ids"].add(artifact_id)
    return index


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

    # Validate all package bytes and immutable product provenance before any
    # checker subprocess or report write.
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

    # Bind each checker input to the independent central artifact archive and
    # local staged-byte receipt. A manually copied package cannot bypass pull.
    custody_index = _load_local_custody_index(inbox)
    verified = []
    for lane, kind, folder, info in checked:
        key = (lane, info["request_id"], info["source_sha"],
               info["slug"], info["package_sha256"])
        custody = custody_index.get(key)
        if custody is None or custody["package_bytes"] != info["package_bytes"]:
            raise ValueError("LOCAL_QA_HOLD: package lacks matching verified local artifact custody receipt")
        verified.append((lane, kind, folder, info, sorted(custody["artifact_ids"])))

    reports.mkdir(parents=True, exist_ok=True)
    results = []
    for lane, kind, folder, info, artifact_ids in verified:
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
                "package_sha256": info["package_sha256"],
                "identity": info["identity"],
                "local_artifact_custody": "VERIFIED",
                "local_artifact_ids": artifact_ids,
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
