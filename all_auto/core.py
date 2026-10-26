"""Fail-closed offline preflight for the Windows Store submission coordinator.

This module NEVER calls Partner Center or submits an application.
All 'ready' outcomes mean ready for Windows operator QA, not Store certification.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

ALLOWED_SUFFIXES = {".msix", ".msixupload", ".msixbundle", ".appx", ".appxupload", ".appxbundle"}
HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
VERSION = re.compile(r"^\d{1,5}\.\d{1,5}\.\d{1,5}\.\d{1,5}$")
SECURITY_KEYS = (
    "personal_data", "external_accounts", "external_communication",
    "user_files", "camera", "microphone", "location",
    "restricted_capabilities", "non_microsoft_driver_service",
)
CHECKER_READY = "READY_CANDIDATE_NOT_CERTIFIED"
NEVER_STORE_CERTIFIED = "READY_FOR_WINDOWS_QA"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for piece in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def check_product(item: Any, base: Path) -> dict[str, Any]:
    """Check a single product, with no network access, no mutation of packages."""
    if not isinstance(item, dict):
        return {"id": "invalid", "status": "BLOCKED", "findings": ["PRODUCT_NOT_OBJECT"]}
    product_id = item.get("id")
    name = product_id if isinstance(product_id, str) and ID.fullmatch(product_id) else "invalid"
    hold: list[str] = []
    blocked: list[str] = []

    if name == "invalid":
        blocked.append("INVALID_PRODUCT_ID")
    if item.get("type") not in ("app", "game"):
        blocked.append("TYPE_MUST_BE_APP_OR_GAME")
    if item.get("submission_kind") not in ("new", "update"):
        hold.append("SUBMISSION_KIND_UNCONFIRMED")
    repo = item.get("repository")
    if not isinstance(repo, str) or not re.fullmatch(
        r"https://github\.com/shihuiarenjinba-png/[A-Za-z0-9_.-]+", repo
    ):
        hold.append("GITHUB_REPO_UNCONFIRMED")
    if not isinstance(item.get("source_ref"), str) or not item.get("source_ref"):
        hold.append("SOURCE_REF_UNCONFIRMED")
    if not isinstance(item.get("source_sha"), str) or not HEX40.fullmatch(item["source_sha"]):
        hold.append("SOURCE_SHA_UNCONFIRMED")

    identity = item.get("identity")
    approved = item.get("approved_identity")
    if not isinstance(identity, dict) or not isinstance(approved, dict):
        hold.append("STORE_IDENTITY_EVIDENCE_MISSING")
    else:
        for field in ("store_id", "name", "publisher", "version", "architecture"):
            val = identity.get(field)
            expected = approved.get(field)
            if not isinstance(val, str) or not val.strip() or not isinstance(expected, str) or not expected.strip():
                hold.append("IDENTITY_NOT_VERIFIED_" + field.upper())
            elif val != expected:
                blocked.append("IDENTITY_MISMATCH_" + field.upper())
        version = identity.get("version")
        if isinstance(version, str) and not VERSION.fullmatch(version):
            blocked.append("INVALID_PACKAGE_VERSION")

    pth = item.get("package_path")
    given_sha = item.get("package_sha256")
    actual_sha: str | None = None
    if not isinstance(pth, str) or not pth.strip():
        hold.append("PACKAGE_MISSING")
    else:
        p = Path(pth)
        if not p.is_absolute():
            p = base / p
        if p.suffix.lower() not in ALLOWED_SUFFIXES:
            blocked.append("UNSUPPORTED_PACKAGE_SUFFIX")
        elif not p.is_file():
            hold.append("PACKAGE_FILE_NOT_FOUND")
        else:
            actual_sha = sha256_file(p)
            if not isinstance(given_sha, str) or not HEX64.fullmatch(given_sha):
                hold.append("PACKAGE_SHA_NOT_PROVIDED")
            elif given_sha.lower() != actual_sha:
                blocked.append("PACKAGE_SHA_MISMATCH")

    checker = item.get("checker")
    if not isinstance(checker, dict):
        hold.append("WINDOWS_CHECKER_EVIDENCE_MISSING")
    else:
        checker_status = checker.get("status")
        if checker_status == "BLOCKED":
            blocked.append("WINDOWS_CHECKER_BLOCKED")
        elif checker_status != CHECKER_READY:
            hold.append("WINDOWS_CHECKER_NOT_READY")
        if checker.get("package_sha256") != actual_sha or not actual_sha:
            hold.append("CHECKER_PACKAGE_SHA_UNVERIFIED")
        if not checker.get("report_path") or not checker.get("report_sha256"):
            hold.append("CHECKER_REPORT_PROVENANCE_MISSING")
        else:
            rp = Path(str(checker["report_path"]))
            if not rp.is_absolute():
                rp = base / rp
            try:
                if sha256_file(rp) != str(checker["report_sha256"]).lower():
                    blocked.append("CHECKER_REPORT_HASH_MISMATCH")
            except OSError:
                hold.append("CHECKER_REPORT_NOT_FOUND")

    build = item.get("build")
    if not isinstance(build, dict):
        hold.append("WINDOWS_DATA_EVIDENCE_MISSING")
    else:
        if build.get("source_sha") != item.get("source_sha"):
            blocked.append("BUILD_SOURCE_SHA_MISMATCH")
        if build.get("package_sha256") != actual_sha or not actual_sha:
            hold.append("BUILD_PACKAGE_SHA_UNVERIFIED")
        if not build.get("report_path") or not build.get("report_sha256"):
            hold.append("WINDOWS_DATA_REPORT_PROVENANCE_MISSING")
        else:
            rp = Path(str(build["report_path"]))
            if not rp.is_absolute():
                rp = base / rp
            try:
                if sha256_file(rp) != str(build["report_sha256"]).lower():
                    blocked.append("WINDOWS_DATA_REPORT_HASH_MISMATCH")
            except OSError:
                hold.append("WINDOWS_DATA_REPORT_NOT_FOUND")

    sec = item.get("security")
    if not isinstance(sec, dict) or sec.get("package_sha256") != actual_sha or not actual_sha:
        hold.append("SECURITY_CONFIRMATION_PACKAGE_MISMATCH")
    else:
        if sec.get("confirmed") is not True or not sec.get("confirmed_at") or not sec.get("confirmed_by"):
            hold.append("SECURITY_HUMAN_CONFIRMATION_REQUIRED")
        fields = sec.get("fields", {})
        if not isinstance(fields, dict) or any(type(fields.get(k)) is not bool for k in SECURITY_KEYS):
            hold.append("SECURITY_NINE_FIELDS_INCOMPLETE")

    price = item.get("price")
    if not isinstance(price, dict) or type(price.get("amount_minor")) is not int or price["amount_minor"] <= 0:
        hold.append("PAID_PRICE_UNCONFIRMED")
    elif price.get("currency") not in ("JPY", "USD"):
        hold.append("CURRENCY_UNCONFIRMED")
    if item.get("assets_reviewed") is not True:
        hold.append("STORE_LISTING_ASSETS_NOT_REVIEWED")
    if item.get("owner_approved_for_draft") is not True:
        hold.append("DRAFT_WRITE_NOT_AUTHORIZED")

    status = "BLOCKED" if blocked else "HOLD" if hold else NEVER_STORE_CERTIFIED
    return {
        "id": name, "type": item.get("type"), "status": status,
        "findings": sorted(set(blocked + hold)),
        "package_sha256": actual_sha,
        "meaning": "Offline evidence preflight only; no Store operation performed.",
    }


def preflight(document: Any, base: Path) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("schema_version") != "1":
        raise ValueError("Unsupported manifest schema_version; expected '1'")
    entries = document.get("products")
    if not isinstance(entries, list) or not entries:
        raise ValueError("products must be a nonempty list")
    results = [check_product(x, base) for x in entries]
    ids = [x["id"] for x in results]
    duplicated = {i for i, n in Counter(ids).items() if n > 1}
    # A duplicate product or Store ID is a dangerous collision even when other evidence is valid.
    store_ids = [x.get("approved_identity", {}).get("store_id") if isinstance(x, dict) and isinstance(x.get("approved_identity"), dict) else None for x in entries]
    repeated_store_ids = {x for x, n in Counter(y for y in store_ids if y).items() if n > 1}
    for row, store_id in zip(results, store_ids):
        if row["id"] in duplicated or store_id in repeated_store_ids:
            row["status"] = "BLOCKED"
            row["findings"] = sorted(set(row["findings"] + ["DUPLICATE_PRODUCT_OR_STORE_ID"]))
    totals = Counter(row["status"] for row in results)
    return {
        "schema_version": "1",
        "mode": "OFFLINE_PREFLIGHT_ONLY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "counts": {name: totals[name] for name in ("READY_FOR_WINDOWS_QA", "HOLD", "BLOCKED")},
        "products": results,
        "store_uploads_attempted": 0,
        "drafts_saved": 0,
        "submissions_made": 0,
        "certified": 0,
    }


def export_results(result: dict[str, Any], directory: Path) -> None:
    _atomic_json(directory / "summary.json", result)
    for row in result["products"]:
        if row["id"] != "invalid":
            _atomic_json(directory / ("audit-" + row["id"] + ".json"), row)
    lines = [
        "# Windows-all-auto — Offline preflight",
        "", "**No Partner Center operation was executed.**", "",
        f"Total: {result['total']}",
        f"Ready for Windows QA: {result['counts']['READY_FOR_WINDOWS_QA']}",
        f"HOLD: {result['counts']['HOLD']}",
        f"BLOCKED: {result['counts']['BLOCKED']}", "",
        "| ID | Status | Findings |", "|---|---|---|",
    ]
    for row in result["products"]:
        safe_id = row["id"].replace("|", " ")
        lines.append(f"| {safe_id} | {row['status']} | {', '.join(row['findings'])} |")
    dest = directory / "summary.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
