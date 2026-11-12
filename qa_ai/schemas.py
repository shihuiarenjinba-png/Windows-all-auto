"""Strict validation for derived AI analysis; never changes test evidence."""
from __future__ import annotations

import re
from typing import Any


SCHEMA_VERSION = "windows-qa-analysis-v1"
CLASSIFICATIONS = {
    "TIMEOUT", "PROCESS_START_FAILED", "NONZERO_EXIT",
    "UIA_CONTROL_NOT_FOUND", "UIA_NAME_MISMATCH", "UIA_INVOKE_FAILED",
    "UIA_FOCUS_FAILED", "UI_STATE_UNCHANGED", "HASH_MISMATCH",
    "SOURCE_SHA_CONFLICT", "ARTIFACT_MISSING", "STALE_ARTIFACT",
    "EVENT_LOG_UNAVAILABLE", "PERMISSION_DENIED", "GITHUB_RETURN_FAILED",
    "GITHUB_READBACK_MISMATCH", "REQUEST_ID_CONFLICT", "PACKAGE_INVALID",
    "MANIFEST_MISMATCH", "IDENTITY_MISMATCH", "JSON_PARSE_ERROR",
    "IMPORT_ERROR", "TYPE_ERROR", "SUBPROCESS_FAILED", "UNKNOWN",
}
OWNERS = {"APP", "GAME", "GAME_3D", "Windows-E2E", "infrastructure"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
CONFIDENCES = {"LOW", "MEDIUM", "HIGH"}
REQUIRED_KEYS = {
    "schema_version", "target_repository", "source_sha", "request_id",
    "classification", "failure_class", "severity", "observed", "inference",
    "unknown", "missing_evidence", "recommended_owner", "recommended_action",
    "suggested_fix_area", "regression_tests", "agent_dispatch_status",
    "e2e_pass_authority", "store_submission_allowed",
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def json_schema() -> dict[str, Any]:
    string_array = {"type": "array", "items": {"type": "string", "minLength": 1}}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/shihuiarenjinba-png/Windows-all-auto/schemas/windows-qa-analysis-v1.schema.json",
        "title": "Derived Windows QA analysis",
        "type": "object", "additionalProperties": False,
        "required": sorted(REQUIRED_KEYS),
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "target_repository": {"type": "string"},
            "source_sha": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
            "request_id": {"type": "string"},
            "classification": {"enum": sorted(CLASSIFICATIONS)},
            "failure_class": {"enum": sorted(CLASSIFICATIONS)},
            "severity": {"enum": sorted(SEVERITIES)},
            "observed": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["fact", "evidence_excerpt"],
                "properties": {"fact": {"type": "string", "minLength": 1},
                               "evidence_excerpt": {"type": "string", "minLength": 1}}}},
            "inference": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["hypothesis", "confidence", "evidence_basis"],
                "properties": {"hypothesis": {"type": "string", "minLength": 1},
                               "confidence": {"enum": sorted(CONFIDENCES)},
                               "evidence_basis": string_array}}},
            "unknown": string_array, "missing_evidence": string_array,
            "recommended_owner": {"enum": sorted(OWNERS)},
            "recommended_action": {"type": "string", "minLength": 1},
            "suggested_fix_area": {"type": "string", "minLength": 1},
            "regression_tests": string_array,
            "agent_dispatch_status": {"const": "AGENT_DISPATCH_PENDING"},
            "e2e_pass_authority": {"const": False},
            "store_submission_allowed": {"const": False},
        },
    }


def _string_list(value: Any, name: str, errors: list[str]) -> None:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        errors.append(name + " must be a list of non-empty strings")


def validate_analysis(value: Any, *, context: dict[str, str], evidence_text: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return ["analysis must be an object"]
    keys = set(value)
    if keys != REQUIRED_KEYS:
        errors.append("fields differ: missing=" + repr(sorted(REQUIRED_KEYS - keys)) +
                      " extra=" + repr(sorted(keys - REQUIRED_KEYS)))
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("wrong schema_version")
    for field in ("target_repository", "source_sha", "request_id"):
        if value.get(field) != context.get(field):
            errors.append(field + " does not match immutable context")
    classification = value.get("classification")
    if classification not in CLASSIFICATIONS:
        errors.append("invalid classification")
    if value.get("failure_class") != classification:
        errors.append("failure_class must equal classification")
    if value.get("severity") not in SEVERITIES:
        errors.append("invalid severity")
    if value.get("recommended_owner") not in OWNERS:
        errors.append("invalid recommended_owner")
    if value.get("agent_dispatch_status") != "AGENT_DISPATCH_PENDING":
        errors.append("agent dispatch authority violation")
    if value.get("e2e_pass_authority") is not False:
        errors.append("AI cannot have E2E authority")
    if value.get("store_submission_allowed") is not False:
        errors.append("AI cannot allow Store submission")
    observed = value.get("observed")
    if not isinstance(observed, list):
        errors.append("observed must be a list")
    else:
        for index, item in enumerate(observed):
            if not isinstance(item, dict) or set(item) != {"fact", "evidence_excerpt"}:
                errors.append(f"observed[{index}] has invalid fields")
                continue
            excerpt = item.get("evidence_excerpt")
            if not isinstance(item.get("fact"), str) or not item["fact"].strip():
                errors.append(f"observed[{index}].fact is empty")
            if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in evidence_text:
                errors.append(f"observed[{index}] excerpt is not present in evidence")
    inference = value.get("inference")
    if not isinstance(inference, list):
        errors.append("inference must be a list")
    else:
        for index, item in enumerate(inference):
            if not isinstance(item, dict) or set(item) != {"hypothesis", "confidence", "evidence_basis"}:
                errors.append(f"inference[{index}] has invalid fields")
                continue
            if not isinstance(item.get("hypothesis"), str) or not item["hypothesis"].strip():
                errors.append(f"inference[{index}].hypothesis is empty")
            if item.get("confidence") not in CONFIDENCES:
                errors.append(f"inference[{index}] confidence invalid")
            basis = item.get("evidence_basis")
            _string_list(basis, f"inference[{index}].evidence_basis", errors)
            if isinstance(basis, list):
                for excerpt in basis:
                    if isinstance(excerpt, str) and excerpt not in evidence_text:
                        errors.append(f"inference[{index}] basis is not present in evidence")
    for field in ("unknown", "missing_evidence", "regression_tests"):
        _string_list(value.get(field), field, errors)
    for field in ("recommended_action", "suggested_fix_area"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            errors.append(field + " must be a non-empty string")
    return errors
