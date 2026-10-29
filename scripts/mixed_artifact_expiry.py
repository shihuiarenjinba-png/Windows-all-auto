"""Fail-closed expiry correlation for mixed PRE/POST APP local preflight.

The GitHub 'expired' flag may lag the actual expiration timestamp.
Never download an expired or uncorrelated Factory artifact.
"""
from __future__ import annotations

from datetime import datetime, timezone


class ExpiryHold(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ExpiryHold("HOLD_ARTIFACT_EXPIRY_UNVERIFIED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExpiryHold("HOLD_ARTIFACT_EXPIRY_UNVERIFIED") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExpiryHold("HOLD_ARTIFACT_EXPIRY_UNVERIFIED")
    return parsed.astimezone(timezone.utc)


def validate(job: dict, artifact: dict, *, now: datetime | None = None) -> str:
    """Return verified UTC expiry; raise before any local download on failure.

    Both the central job and live GitHub Artifact API must agree on expiry.
    A remote 'expired=false' alone is insufficient after the UTC deadline.
    """
    if not isinstance(job, dict) or not isinstance(artifact, dict):
        raise ExpiryHold("HOLD_ARTIFACT_EXPIRY_UNVERIFIED")
    recorded = _utc(job.get("factory_artifact_expiry_utc"))
    remote = _utc(artifact.get("expires_at"))
    if recorded != remote:
        raise ExpiryHold("HOLD_ARTIFACT_EXPIRY_CONFLICT")
    current = datetime.now(timezone.utc) if now is None else now
    if current.tzinfo is None or current.utcoffset() is None:
        raise ExpiryHold("HOLD_ARTIFACT_EXPIRY_UNVERIFIED")
    if artifact.get("expired") is not False or remote <= current.astimezone(timezone.utc):
        raise ExpiryHold("HOLD_ARTIFACT_EXPIRED")
    return remote.isoformat()
