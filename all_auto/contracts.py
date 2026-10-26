"""Strict JSON contract boundaries for the three upstream tools.

These functions parse evidence only. They never execute builds, uploads, browser
automation, Partner Center writes, certification submission, or publication.

Unknown schema/status values fail closed with ContractError.
"""
from __future__ import annotations

import re
from typing import Any

HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")

WINDOWS_DATA_STATUSES = {
    "HOLD",
    "READY_CANDIDATE_NOT_CERTIFIED",
    "IDENTITY_COLLECTED_NOT_CERTIFIED",
}
CHECKER_STATUSES = {"BLOCKED", "NEEDS_REVIEW", "READY_CANDIDATE_NOT_CERTIFIED"}
AUTOMATOR_STATUSES = {"DONE", "HOLD", "UNKNOWN", "ERROR", "AUTH_ERROR"}


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


def parse_windows_automator(payload: Any, *, product_name: str) -> dict[str, Any]:
    """Normalize the current Windows-Automator queue report.

    The verified upstream implementation uses dryrun_uploader. Therefore DONE is
    deliberately normalized to DRY_RUN_DONE, never DRAFT_SAVED.
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

    normalized_status = "DRY_RUN_DONE" if status == "DONE" else status
    return {
        "schema_version": "windows-automator/dryrun-1",
        "status": normalized_status,
        "actions": list(actions),
        "draft_saved": False,
        "submitted": False,
        "certified": False,
        "published": False,
    }
