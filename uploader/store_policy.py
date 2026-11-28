"""Shared policy loading and product-evidence candidate assembly."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any


class StorePolicyError(ValueError):
    pass


def load_shared_store_policy() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "config" / "store_submission_policy.json"
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorePolicyError("shared Store submission policy is unreadable") from exc
    if (not isinstance(policy, dict) or policy.get("schema_version") != 1 or
            policy.get("candidate_defaults") != "NONE" or
            not isinstance(policy.get("dimensions"), list)):
        raise StorePolicyError("shared Store submission policy schema is invalid")
    keys = [item.get("key") for item in policy["dimensions"] if isinstance(item, dict)]
    if len(keys) != len(policy["dimensions"]) or len(keys) != len(set(keys)):
        raise StorePolicyError("shared Store submission policy dimension keys are invalid")
    return policy


def build_product_decision_batch(policy: dict[str, Any], product_profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Join common owner-decision dimensions to product-specific evidence candidates.

    This function presents candidate evidence but never converts it into an approval.
    """
    raw = product_profile.get("owner_decision_candidates", [])
    records: dict[str, list[dict[str, Any]]] = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("key"), str):
                records.setdefault(item["key"], []).append(item)
    batch: list[dict[str, Any]] = []
    for dimension in policy["dimensions"]:
        evidence = [record for key in dimension.get("candidate_keys", [])
                    for record in records.get(key, [])]
        required = dimension.get("approval_required") is True
        approved, approved_value = _approved_dimension_value(dimension["key"], product_profile)
        batch.append({
            "key": dimension["key"],
            "section": dimension.get("section"),
            "approval_required": required,
            "legal_or_commercial": dimension.get("legal_or_commercial") is True,
            "status": ("APPROVED_REUSED" if approved else "OWNER_DECISION_REQUIRED" if required and
                       any(record.get("decision_required", True) is True for record in evidence)
                       else "EVIDENCE_REQUIRED" if required and not evidence
                       else "APPROVED_EVIDENCE_REUSED" if evidence and
                       all(record.get("decision_required") is False for record in evidence)
                       else "OWNER_DECISION_REQUIRED" if required else "INFORMATIONAL"),
            "evidence_candidates": [{
                "source_key": record.get("key"),
                "candidate": record.get("candidate"),
                "basis": record.get("basis"),
                "decision_required": record.get("decision_required", True),
            } for record in evidence],
            "value": approved_value if approved else None,
            "owner_approval": "RECORDED" if approved else None,
        })
    return batch


def _approved_dimension_value(key: str, profile: dict[str, Any]) -> tuple[bool, Any]:
    product_id, submission_id = profile.get("product_id"), profile.get("submission_id")

    def exact_approval(approval: Any, section: str | None = None, value: Any = None) -> bool:
        return (isinstance(approval, dict)
                and approval.get("approved") is True
                and approval.get("product_id") == product_id
                and approval.get("submission_id") == submission_id
                and (section is None or (isinstance(approval.get("sections"), list)
                                         and section in approval["sections"]))
                and all(isinstance(approval.get(field), str) and approval[field].strip()
                        for field in ("approval_ref", "approved_by", "approved_at"))
                and isinstance(approval.get("approved_values_digest"), str)
                and approval["approved_values_digest"] == _value_digest(value))

    section_for = {"category": "properties", "privacy_declarations": "properties",
                   "languages": "store_listings", "descriptions": "store_listings",
                   "images": "store_listings", "age_rating": "age_ratings",
                   "publication_mode": "submission_options"}
    if key in section_for:
        section = section_for[key]
        entry = (profile.get("approved_store_sections") or {}).get(section, {})
        fields = entry.get("fields") if isinstance(entry, dict) else None
        value = ({str(field.get("key")): field.get("value") for field in fields
                  if isinstance(field, dict) and isinstance(field.get("key"), str)}
                 if isinstance(fields, list) else None)
        approved = exact_approval(entry.get("approval"), section, value)
        return approved and isinstance(fields, list), value if approved else None

    if key == "device_families":
        settings = profile.get("device_family_settings")
        value = settings.get("approved_store_device_families") if isinstance(settings, dict) else None
        approved = (isinstance(settings, dict) and settings.get("status") == "OWNER_APPROVED"
                    and exact_approval(settings.get("approval"), "packages", value))
        return bool(approved), value if approved else None
    if key in {"price_model", "price"}:
        record = profile.get("pricing_approval")
        field = "price_type" if key == "price_model" else "price"
        value = profile.get(field)
        approved = _owner_record_approved(record, product_id, submission_id, "pricing_availability", value)
        return approved and value is not None, value if approved else None
    if key == "markets":
        record = profile.get("markets_approval")
        value = profile.get("markets")
        approved = _owner_record_approved(record, product_id, submission_id, "pricing_availability", value)
        return approved and value is not None, value if approved else None
    if key == "commercial_license":
        record = profile.get("commercial_license_approval")
        value = profile.get("commercial_license")
        approved = _owner_record_approved(record, product_id, submission_id, "commercial_review", value)
        return bool(approved), value if approved else None
    if key == "automatic_execution_scope":
        record = profile.get("execution_policy")
        approval = record.get("approval") if isinstance(record, dict) else None
        value = record.get("approved_sections") if isinstance(record, dict) else None
        approved = (isinstance(record, dict) and record.get("status") == "OWNER_APPROVED"
                    and record.get("auto_execute_approved_sections") is True
                    and isinstance(record.get("approved_sections"), list)
                    and bool(record["approved_sections"])
                    and exact_approval(approval, "execution_policy", value))
        return bool(approved), value if approved else None
    return False, None


def _value_digest(value: Any) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _owner_record_approved(record: Any, product_id: Any, submission_id: Any,
                           section: str, value: Any) -> bool:
    if not isinstance(record, dict) or record.get("status") != "OWNER_APPROVED":
        return False
    approval = record.get("approval", record)
    return (isinstance(approval, dict)
            and approval.get("product_id") == product_id
            and approval.get("submission_id") == submission_id
            and isinstance(approval.get("sections"), list)
            and section in approval["sections"]
            and approval.get("approved_values_digest") == _value_digest(value)
            and all(isinstance(approval.get(field), str) and approval[field].strip()
                    for field in ("approval_ref", "approved_by", "approved_at")))
