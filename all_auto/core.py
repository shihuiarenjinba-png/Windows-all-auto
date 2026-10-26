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


def _same_hex(value: Any, expected: Any, pattern: re.Pattern[str]) -> bool:
    return (
        isinstance(value, str)
        and isinstance(expected, str)
        and bool(pattern.fullmatch(value))
        and bool(pattern.fullmatch(expected))
        and value.lower() == expected.lower()
    )


def _read_evidence(path: Path) -> dict[str, Any] | None:
    """Bound evidence reads; a matching hash alone is not proof of a valid report."""
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _verify_checker_evidence(
    evidence: dict[str, Any] | None,
    expected_status: Any,
    actual_sha: str | None,
    identity: Any,
    item_type: Any,
    hold: list[str],
    blocked: list[str],
) -> None:
    if evidence is None or evidence.get("schema_version") != 1:
        hold.append("CHECKER_REPORT_SCHEMA_UNVERIFIED")
        return
    verdict = evidence.get("verdict")
    if verdict != expected_status:
        blocked.append("CHECKER_REPORT_VERDICT_MISMATCH")
    if verdict != CHECKER_READY:
        return
    if evidence.get("product_type") != item_type:
        blocked.append("CHECKER_REPORT_PRODUCT_TYPE_MISMATCH")
    if type(evidence.get("pending_review_count")) is not int or evidence["pending_review_count"] != 0:
        hold.append("CHECKER_REPORT_PENDING_REVIEW")
    findings = evidence.get("findings")
    if not isinstance(findings, list):
        hold.append("CHECKER_REPORT_FINDINGS_MISSING")
    elif any(not isinstance(f, dict) or f.get("state") not in {"PASS", "REVIEW", "BLOCK"} for f in findings):
        hold.append("CHECKER_REPORT_FINDINGS_INVALID")
    elif any(f.get("state") == "BLOCK" for f in findings):
        blocked.append("CHECKER_REPORT_CONTAINS_BLOCK")
    metadata = evidence.get("metadata")
    if not isinstance(metadata, dict) or not actual_sha or not _same_hex(metadata.get("msix_sha256"), actual_sha, HEX64):
        hold.append("CHECKER_REPORT_PACKAGE_UNVERIFIED")
        return
    manifest = metadata.get("manifest")
    if not isinstance(manifest, dict) or not isinstance(identity, dict):
        hold.append("CHECKER_REPORT_MANIFEST_MISSING")
        return
    for field in ("name", "publisher", "version", "architecture"):
        if not isinstance(manifest.get(field), str) or not manifest.get(field):
            hold.append("CHECKER_REPORT_MANIFEST_" + field.upper() + "_MISSING")
        elif manifest[field] != identity.get(field):
            blocked.append("CHECKER_REPORT_MANIFEST_" + field.upper() + "_MISMATCH")


def _verify_build_evidence(
    evidence: dict[str, Any] | None,
    item: dict[str, Any],
    actual_sha: str | None,
    hold: list[str],
    blocked: list[str],
) -> None:
    if evidence is None or evidence.get("schema_version") != 1:
        hold.append("WINDOWS_DATA_REPORT_SCHEMA_UNVERIFIED")
        return
    if evidence.get("status") != CHECKER_READY:
        hold.append("WINDOWS_DATA_REPORT_NOT_READY")
        return
    holds = evidence.get("holds")
    if not isinstance(holds, list) or holds:
        hold.append("WINDOWS_DATA_REPORT_HAS_HOLDS")
    if not _same_hex(evidence.get("source_head"), item.get("source_sha"), HEX40):
        blocked.append("WINDOWS_DATA_REPORT_SOURCE_MISMATCH")
    if evidence.get("repository_url") != item.get("repository"):
        blocked.append("WINDOWS_DATA_REPORT_REPOSITORY_MISMATCH")
    approved = item.get("approved_identity")
    if not isinstance(approved, dict) or evidence.get("store_id") != approved.get("store_id"):
        blocked.append("WINDOWS_DATA_REPORT_STORE_ID_MISMATCH")
    identity = evidence.get("identity")
    if not isinstance(identity, dict) or not isinstance(approved, dict):
        hold.append("WINDOWS_DATA_REPORT_IDENTITY_MISSING")
    else:
        for field in ("name", "publisher", "version", "architecture"):
            if not isinstance(identity.get(field), str) or not identity[field]:
                hold.append("WINDOWS_DATA_REPORT_IDENTITY_" + field.upper() + "_MISSING")
            elif identity[field] != approved.get(field):
                blocked.append("WINDOWS_DATA_REPORT_IDENTITY_" + field.upper() + "_MISMATCH")
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, list):
        hold.append("WINDOWS_DATA_REPORT_ARTIFACTS_MISSING")
    else:
        packages = [a for a in artifacts if isinstance(a, dict) and a.get("kind") == "MSIX"]
        if len(packages) != 1 or not actual_sha or not _same_hex(packages[0].get("sha256"), actual_sha, HEX64):
            hold.append("WINDOWS_DATA_REPORT_PACKAGE_UNVERIFIED")


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
        if not actual_sha or not _same_hex(checker.get("package_sha256"), actual_sha, HEX64):
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
                else:
                    _verify_checker_evidence(
                        _read_evidence(rp), checker_status, actual_sha, identity,
                        item.get("type"), hold, blocked,
                    )
            except OSError:
                hold.append("CHECKER_REPORT_NOT_FOUND")

    build = item.get("build")
    if not isinstance(build, dict):
        hold.append("WINDOWS_DATA_EVIDENCE_MISSING")
    else:
        if not _same_hex(build.get("source_sha"), item.get("source_sha"), HEX40):
            blocked.append("BUILD_SOURCE_SHA_MISMATCH")
        if not actual_sha or not _same_hex(build.get("package_sha256"), actual_sha, HEX64):
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
                else:
                    _verify_build_evidence(_read_evidence(rp), item, actual_sha, hold, blocked)
            except OSError:
                hold.append("WINDOWS_DATA_REPORT_NOT_FOUND")

    sec = item.get("security")
    if (
        not isinstance(sec, dict)
        or not actual_sha
        or not _same_hex(sec.get("package_sha256"), actual_sha, HEX64)
    ):
        hold.append("SECURITY_CONFIRMATION_PACKAGE_MISMATCH")
    else:
        confirmed_at = sec.get("confirmed_at")
        confirmed_by = sec.get("confirmed_by")
        if (
            sec.get("confirmed") is not True
            or not isinstance(confirmed_at, str)
            or not confirmed_at.strip()
            or not isinstance(confirmed_by, str)
            or not confirmed_by.strip()
        ):
            hold.append("SECURITY_HUMAN_CONFIRMATION_REQUIRED")
        fields = sec.get("fields", {})
        if not isinstance(fields, dict) or any(type(fields.get(k)) is not bool for k in SECURITY_KEYS):
            hold.append("SECURITY_NINE_FIELDS_INCOMPLETE")

    price = item.get("price")
    if not isinstance(price, dict) or type(price.get("amount_minor")) is not int or price["amount_minor"] < 0:
        hold.append("PRICE_UNCONFIRMED")
    elif price.get("amount_minor") == 0:
        # Free products must be explicitly approved too; never default to free
        # or infer the decision from absent pricing information.
        if (price.get("free_approved") is not True
                or not isinstance(price.get("approved_by"), str)
                or not price["approved_by"].strip()
                or item.get("owner_approved_for_draft") is not True):
            hold.append("FREE_PRICE_NOT_APPROVED")
    if isinstance(price, dict) and price.get("currency") not in ("JPY", "USD"):
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
    store_ids = [
        x["approved_identity"].get("store_id")
        if isinstance(x, dict) and isinstance(x.get("approved_identity"), dict)
        else None for x in entries
    ]
    normalized_store_ids = [
        value.strip().casefold() if isinstance(value, str) and value.strip() else None
        for value in store_ids
    ]
    repeated_store_ids = {
        value for value, count in Counter(
            value for value in normalized_store_ids if value
        ).items() if count > 1
    }
    for row, store_id in zip(results, normalized_store_ids):
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
