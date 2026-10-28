"""Strict JSON contract boundaries for the three upstream tools.

These functions parse evidence only. They never execute builds, uploads, browser
automation, Partner Center writes, certification submission, or publication.

Unknown schema/status values fail closed with ContractError.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")

WINDOWS_DATA_STATUSES = {
    "HOLD",
    "READY_CANDIDATE_NOT_CERTIFIED",
    "IDENTITY_COLLECTED_NOT_CERTIFIED",
}
CHECKER_STATUSES = {"BLOCKED", "NEEDS_REVIEW", "READY_CANDIDATE_NOT_CERTIFIED"}
AUTOMATOR_STATUSES = {"DONE", "DRAFT_SAVED", "HOLD", "UNKNOWN", "ERROR", "AUTH_ERROR"}
AUTOMATOR_REQUIRED_SECTIONS = {
    "pricing_availability",
    "properties",
    "age_ratings",
    "packages",
    "store_listings",
    "submission_options",
}


class ContractError(ValueError):
    """Raised when an upstream report does not match the verified contract."""


def _dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{label} must be an array")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def _hex(value: Any, pattern: re.Pattern[str], label: str) -> str:
    text = _text(value, label)
    if not pattern.fullmatch(text):
        raise ContractError(f"{label} has invalid hex length/format")
    return text.lower()


def parse_windows_data(
    payload: Any, *, expected_repository_url: str | None = None
) -> dict[str, Any]:
    """Normalize Windows-data RunReport schema_version=1 without guessing."""
    report = _dict(payload, "windows-data report")
    if report.get("schema_version") != 1:
        raise ContractError("windows-data schema_version must be 1")
    status = report.get("status")
    if status not in WINDOWS_DATA_STATUSES:
        raise ContractError(f"unsupported windows-data status: {status!r}")

    holds = _list(report.get("holds"), "windows-data holds")
    for index, hold in enumerate(holds):
        obj = _dict(hold, f"windows-data holds[{index}]")
        _text(obj.get("code"), f"windows-data holds[{index}].code")

    repository_url = str(report.get("repository_url") or "").strip()
    if expected_repository_url is not None and repository_url != expected_repository_url:
        raise ContractError("windows-data repository_url does not match requested repository")

    normalized: dict[str, Any] = {
        "schema_version": "windows-data/1",
        "status": status,
        "hold_codes": [str(x.get("code")) for x in holds],
        "ready_for_checker": False,
    }
    if status != "READY_CANDIDATE_NOT_CERTIFIED":
        return normalized

    if holds:
        raise ContractError("windows-data READY report must not contain holds")
    repository_url = _text(repository_url, "windows-data repository_url")
    source_sha = _hex(report.get("source_head"), HEX40, "windows-data source_head")
    store_id = _text(report.get("store_id"), "windows-data store_id")

    identity = _dict(report.get("identity"), "windows-data identity")
    normalized_identity = {
        key: _text(identity.get(key), f"windows-data identity.{key}")
        for key in ("name", "publisher", "version", "architecture")
    }

    artifacts = _list(report.get("artifacts"), "windows-data artifacts")
    msix = []
    for index, artifact in enumerate(artifacts):
        obj = _dict(artifact, f"windows-data artifacts[{index}]")
        if obj.get("kind") == "MSIX":
            msix.append(obj)
    if len(msix) != 1:
        raise ContractError("windows-data READY report must contain exactly one MSIX artifact")
    package = msix[0]
    package_path = _text(package.get("path"), "windows-data MSIX path")
    package_sha256 = _hex(package.get("sha256"), HEX64, "windows-data MSIX sha256")

    normalized.update(
        {
            "repository_url": repository_url,
            "source_sha": source_sha,
            "store_id": store_id,
            "identity": normalized_identity,
            "package_path": package_path,
            "package_sha256": package_sha256,
            "ready_for_checker": True,
        }
    )
    return normalized


def parse_windows_checker(payload: Any, *, product_id: str) -> dict[str, Any]:
    """Normalize Windows-checker batch summary schema_version=1."""
    summary = _dict(payload, "windows-checker summary")
    if summary.get("schema_version") != 1:
        raise ContractError("windows-checker schema_version must be 1")
    items = _list(summary.get("items"), "windows-checker items")
    if summary.get("total") != len(items):
        raise ContractError("windows-checker total does not match items")

    matches = [
        _dict(item, "windows-checker item")
        for item in items
        if isinstance(item, dict) and item.get("id") == product_id
    ]
    if len(matches) != 1:
        raise ContractError("windows-checker product id must match exactly one item")
    item = matches[0]
    verdict = item.get("verdict")
    if verdict not in CHECKER_STATUSES:
        raise ContractError(f"unsupported windows-checker verdict: {verdict!r}")
    report_name = _text(item.get("report"), "windows-checker report path")

    counts = {
        "BLOCKED": summary.get("blocked"),
        "NEEDS_REVIEW": summary.get("needs_review"),
        "READY_CANDIDATE_NOT_CERTIFIED": summary.get("ready_candidates"),
    }
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise ContractError("windows-checker summary counts must be non-negative integers")
    calculated = {
        key: sum(
            1 for entry in items
            if isinstance(entry, dict) and entry.get("verdict") == key
        )
        for key in counts
    }
    if calculated != counts:
        raise ContractError("windows-checker summary counts do not match item verdicts")

    return {
        "schema_version": "windows-checker/1",
        "status": verdict,
        "report": report_name,
        "ready_for_submission_preparation": verdict == "READY_CANDIDATE_NOT_CERTIFIED",
        "certified": False,
    }


def parse_windows_automator(
    payload: Any,
    *,
    product_name: str,
    expected_product_id: str | None = None,
    expected_package_sha256: str | None = None,
    expected_source_sha: str | None = None,
    expected_identity_name: str | None = None,
    expected_identity_publisher: str | None = None,
    expected_version: str | None = None,
) -> dict[str, Any]:
    """Normalize the current Windows-Automator queue report.

    DONE remains a dry-run result.  DRAFT_SAVED is accepted only from the
    explicit live v2 contract and only when the immutable handoff values match
    the expected Store ID, package SHA, source SHA, identity, and version.
    """
    report = _dict(payload, "windows-automator report")
    results = _list(report.get("results"), "windows-automator results")
    matches = [
        _dict(item, "windows-automator result")
        for item in results
        if isinstance(item, dict) and item.get("product_name") == product_name
    ]
    if len(matches) != 1:
        raise ContractError("windows-automator product name must match exactly one result")
    item = matches[0]
    status = item.get("status")
    if status not in AUTOMATOR_STATUSES:
        raise ContractError(f"unsupported windows-automator status: {status!r}")
    actions = _list(item.get("actions"), "windows-automator actions")
    if any(not isinstance(action, str) for action in actions):
        raise ContractError("windows-automator actions must be strings")

    execution_mode = item.get("execution_mode", "dry_run")
    if execution_mode not in {"dry_run", "live"}:
        raise ContractError("windows-automator execution_mode must be dry_run or live")
    if status == "DONE" and execution_mode != "dry_run":
        raise ContractError("windows-automator DONE is valid only for dry_run")
    if status == "DRAFT_SAVED":
        if report.get("schema_version") != 2:
            raise ContractError("windows-automator live result requires schema_version 2")
        if execution_mode != "live":
            raise ContractError("DRAFT_SAVED requires execution_mode=live")
        required_expected = {
            "expected_product_id": expected_product_id,
            "expected_package_sha256": expected_package_sha256,
            "expected_source_sha": expected_source_sha,
            "expected_identity_name": expected_identity_name,
            "expected_identity_publisher": expected_identity_publisher,
            "expected_version": expected_version,
        }
        missing = [key for key, value in required_expected.items() if not str(value or "").strip()]
        if missing:
            raise ContractError("DRAFT_SAVED requires immutable expectations: " + ", ".join(missing))
        expected_package_sha256 = _hex(expected_package_sha256, HEX64, "expected package SHA")
        expected_source_sha = _hex(expected_source_sha, HEX40, "expected source SHA")
        product_id = _text(item.get("product_id"), "windows-automator product_id")
        if product_id != expected_product_id:
            raise ContractError("windows-automator product_id does not match immutable handoff")
        package_sha = _hex(item.get("package_sha256"), HEX64, "windows-automator package_sha256")
        if package_sha != expected_package_sha256:
            raise ContractError("windows-automator package SHA does not match immutable handoff")
        source_sha = _hex(item.get("source_sha"), HEX40, "windows-automator source_sha")
        if source_sha != expected_source_sha:
            raise ContractError("windows-automator source SHA does not match immutable handoff")
        identity = _dict(item.get("identity"), "windows-automator identity")
        normalized_identity = {
            key: _text(identity.get(key), f"windows-automator identity.{key}")
            for key in ("name", "publisher", "version")
        }
        if normalized_identity != {
            "name": expected_identity_name,
            "publisher": expected_identity_publisher,
            "version": expected_version,
        }:
            raise ContractError("windows-automator identity/version does not match immutable handoff")
        for key in ("draft_saved", "save_verified_after_reload", "package_uploaded"):
            if item.get(key) is not True:
                raise ContractError(f"DRAFT_SAVED requires {key}=true")
        if item.get("package_validation") != "VALID":
            raise ContractError("DRAFT_SAVED requires package_validation=VALID")
        if item.get("package_section_completion") != "COMPLETE":
            raise ContractError("DRAFT_SAVED requires package section completion")
        for key in ("submitted", "certified", "published"):
            if item.get(key) is not False:
                raise ContractError(f"DRAFT_SAVED requires {key}=false")
        draft_id = _text(item.get("draft_id"), "windows-automator draft_id")
        draft_url = _text(item.get("current_draft_url"), "windows-automator current_draft_url")
        parsed = urlparse(draft_url)
        if parsed.scheme != "https" or parsed.hostname != "partner.microsoft.com":
            raise ContractError("windows-automator draft URL must be on partner.microsoft.com")
        if product_id not in parsed.path or draft_id not in parsed.path:
            raise ContractError("windows-automator draft URL is not bound to product_id/draft_id")
        sections = _dict(item.get("sections"), "windows-automator sections")
        if set(sections) != AUTOMATOR_REQUIRED_SECTIONS:
            raise ContractError("windows-automator required section set is incomplete")
        if any(value not in {"SAVED", "NOT_REQUIRED"} for value in sections.values()):
            raise ContractError("windows-automator contains an unsaved required section")
        if sections["packages"] != "SAVED":
            raise ContractError("windows-automator Packages section must be SAVED")
        evidence = _list(item.get("evidence"), "windows-automator evidence")
        if not evidence:
            raise ContractError("DRAFT_SAVED requires evidence")
        for index, raw_evidence in enumerate(evidence):
            evidence_item = _dict(raw_evidence, f"windows-automator evidence[{index}]")
            _text(evidence_item.get("kind"), f"windows-automator evidence[{index}].kind")
            if not any(str(evidence_item.get(key) or "").strip() for key in ("path", "url")):
                raise ContractError(f"windows-automator evidence[{index}] requires path or url")
        return {
            "schema_version": "windows-automator/live-2",
            "status": "DRAFT_SAVED",
            "execution_mode": "live",
            "actions": list(actions),
            "draft_saved": True,
            "save_verified_after_reload": True,
            "package_uploaded": True,
            "package_validation": "VALID",
            "product_id": product_id,
            "draft_id": draft_id,
            "package_sha256": package_sha,
            "source_sha": source_sha,
            "identity": normalized_identity,
            "sections": dict(sections),
            "evidence": list(evidence),
            "current_draft_url": draft_url,
            "submitted": False,
            "certified": False,
            "published": False,
        }

    normalized_status = "DRY_RUN_DONE" if status == "DONE" else status
    return {
        "schema_version": "windows-automator/dryrun-1" if execution_mode == "dry_run" else "windows-automator/live-2",
        "status": normalized_status,
        "execution_mode": execution_mode,
        "actions": list(actions),
        "draft_saved": False,
        "submitted": False,
        "certified": False,
        "published": False,
    }
