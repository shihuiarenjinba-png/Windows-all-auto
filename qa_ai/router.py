"""Deterministic first-stage routing before optional local LLM analysis."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Route:
    classification: str
    level: int
    evidence_excerpt: str | None


RULES = (
    ("GITHUB_READBACK_MISMATCH", r"(?i)(github[^\r\n]{0,40}readback[^\r\n]{0,40}mismatch|readback correlation mismatch)"),
    ("SOURCE_SHA_CONFLICT", r"(?i)(source[_ ]sha[^\r\n]{0,40}(?:conflict|mismatch)|request_id reused with changed source)"),
    ("REQUEST_ID_CONFLICT", r"(?i)(request[_ ]id[^\r\n]{0,40}(?:conflict|reused|duplicate))"),
    ("HASH_MISMATCH", r"(?i)(sha-?256|hash)[^\r\n]{0,60}mismatch"),
    ("GITHUB_RETURN_FAILED", r"(?i)(github[^\r\n]{0,40}(?:return|upload)[^\r\n]{0,40}(?:failed|error))"),
    ("PROCESS_START_FAILED", r"(?i)(process_start_failed|failed to (?:start|launch) (?:process|exe)|winerror 2)"),
    ("TIMEOUT", r"(?i)(timed? out|test_timeout|timeout after)"),
    ("UIA_CONTROL_NOT_FOUND", r"(?i)(uia[^\r\n]{0,30}(?:control|element)[^\r\n]{0,30}not found)"),
    ("UIA_NAME_MISMATCH", r"(?i)(uia[^\r\n]{0,30}name[^\r\n]{0,30}mismatch)"),
    ("UIA_INVOKE_FAILED", r"(?i)(uia[^\r\n]{0,30}invoke[^\r\n]{0,30}(?:failed|error))"),
    ("UIA_FOCUS_FAILED", r"(?i)(uia[^\r\n]{0,30}focus[^\r\n]{0,30}(?:failed|error))"),
    ("UI_STATE_UNCHANGED", r"(?i)(state (?:did not change|unchanged)|no state change)"),
    ("ARTIFACT_MISSING", r"(?i)(artifact[^\r\n]{0,30}(?:missing|not found|unavailable))"),
    ("STALE_ARTIFACT", r"(?i)(stale artifact|artifact[^\r\n]{0,30}expired)"),
    ("EVENT_LOG_UNAVAILABLE", r"(?i)(event log[^\r\n]{0,30}(?:unavailable|access denied|failed))"),
    ("PERMISSION_DENIED", r"(?i)(permission denied|access is denied|unauthorizedaccess)"),
    ("MANIFEST_MISMATCH", r"(?i)(manifest[^\r\n]{0,40}mismatch)"),
    ("IDENTITY_MISMATCH", r"(?i)(identity[^\r\n]{0,40}mismatch)"),
    ("PACKAGE_INVALID", r"(?i)(package[^\r\n]{0,40}(?:invalid|corrupt)|invalid msix)"),
    ("JSON_PARSE_ERROR", r"(?i)(jsondecodeerror|json[^\r\n]{0,30}(?:parse|decode)[^\r\n]{0,20}(?:error|failed))"),
    ("IMPORT_ERROR", r"(?i)(importerror|modulenotfounderror)"),
    ("TYPE_ERROR", r"(?i)typeerror"),
    ("SUBPROCESS_FAILED", r"(?i)(subprocess[^\r\n]{0,40}(?:failed|error)|calledprocesserror)"),
    ("NONZERO_EXIT", r"(?i)(nonzero exit|exit(?:ed)? (?:code|with) [1-9][0-9]*)"),
)


def classify(text: str) -> Route:
    for classification, pattern in RULES:
        match = re.search(pattern, text)
        if match:
            simple = classification in {
                "TIMEOUT", "PROCESS_START_FAILED", "HASH_MISMATCH",
                "SOURCE_SHA_CONFLICT", "REQUEST_ID_CONFLICT", "ARTIFACT_MISSING",
                "EVENT_LOG_UNAVAILABLE", "GITHUB_READBACK_MISMATCH",
            }
            return Route(classification, 0 if simple else 2, match.group(0))
    return Route("UNKNOWN", 2, None)
