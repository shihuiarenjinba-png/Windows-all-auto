"""Manifest-to-Partner-Center device-family mapping and approval inspection."""
from __future__ import annotations

from typing import Any


STORE_DEVICE_FAMILY_LABELS = {
    "Windows.Desktop": "Windows 10/11 Desktop",
    "Windows.Mobile": "Windows 10 Mobile",
    "Windows.Xbox": "Windows 10/11 Xbox",
    "Windows.Team": "Windows 10 Team",
    "Windows.Holographic": "Windows 10 Mixed Reality",
}


def device_family_plan(config: dict[str, Any], manifest_targets: list[str]) -> dict[str, Any]:
    """Report technical candidates separately from a persisted owner decision."""
    candidates = [STORE_DEVICE_FAMILY_LABELS[name]
                  for name in manifest_targets if name in STORE_DEVICE_FAMILY_LABELS]
    settings = config.get("device_family_settings")
    approval = settings.get("approval") if isinstance(settings, dict) else None
    approved = (isinstance(settings, dict)
                and settings.get("status") == "OWNER_APPROVED"
                and isinstance(approval, dict)
                and approval.get("product_id") == config.get("product_id")
                and approval.get("submission_id") == config.get("submission_id")
                and all(isinstance(approval.get(key), str) and approval[key].strip()
                        for key in ("approval_ref", "approved_by", "approved_at")))
    return {
        "status": "OWNER_APPROVED" if approved else "PENDING_OWNER_APPROVAL",
        "manifest_target_device_families": manifest_targets,
        "recommended_store_device_families": candidates,
        "approved_store_device_families": (
            settings.get("approved_store_device_families", []) if approved else []
        ),
        "approval_ref": approval.get("approval_ref") if approved else None,
    }
