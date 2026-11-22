"""Fail-closed reusable guards for Group C Store teacher rollout.

Product-specific Store/Draft values stay outside this module.  The guard only
decides whether a locally supplied binding is complete enough to enter the next
teacher-data stage.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

HEX40 = re.compile(r"^[0-9a-f]{40}$")
STORE_ID = re.compile(r"^9P[A-Z0-9]{10}$")
DRAFT_ID = re.compile(r"^[0-9]{10,}$")


@dataclass(frozen=True)
class ProductBinding:
    product_id: str
    repository_full_name: str
    source_branch: str | None
    source_sha: str | None
    current_remote_sha: str | None
    store_id: str | None
    draft_id: str | None
    submission_route: str = "msix_pwa_app"


def binding_state(binding: ProductBinding) -> str:
    """Return one deterministic state; never infer missing Partner Center data."""
    if binding.submission_route != "msix_pwa_app":
        return "HOLD_SUBMISSION_ROUTE_NOT_VERIFIED"
    if not binding.source_branch:
        return "HOLD_REGISTRY_BINDING_REQUIRED"
    if not binding.source_sha or not HEX40.fullmatch(binding.source_sha):
        return "HOLD_REGISTRY_BINDING_REQUIRED"
    if not binding.current_remote_sha or not HEX40.fullmatch(binding.current_remote_sha):
        return "HOLD_SOURCE_HEAD_REVERIFY_REQUIRED"
    if binding.source_sha != binding.current_remote_sha:
        return "HOLD_SOURCE_HEAD_REBIND_REQUIRED"
    if not binding.store_id or not STORE_ID.fullmatch(binding.store_id):
        return "HOLD_REGISTRY_BINDING_REQUIRED"
    if not binding.draft_id or not DRAFT_ID.fullmatch(binding.draft_id):
        return "HOLD_REGISTRY_BINDING_REQUIRED"
    return "REGISTRY_BOUND"


def next_stage_after_teacher(
    binding: ProductBinding,
    *,
    teacher_previous_complete: bool,
    windows_real_device_qa_pass: bool,
    formal_store_version_approved: bool,
    final_artwork_approved: bool,
    manifest_languages_approved: bool,
    formal_msix_frozen: bool,
) -> str:
    """Classify the next safe Group C stage without performing any write."""
    if not teacher_previous_complete:
        return "WAITING_FOR_PREVIOUS_PRODUCT"
    bound = binding_state(binding)
    if bound != "REGISTRY_BOUND":
        return bound
    if not windows_real_device_qa_pass:
        return "READY_FOR_WINDOWS_REAL_DEVICE_QA"
    if not (
        formal_store_version_approved
        and final_artwork_approved
        and manifest_languages_approved
    ):
        return "HOLD_FORMAL_STORE_VALUES_REQUIRED"
    if not formal_msix_frozen:
        return "READY_FOR_FORMAL_STORE_MSIX"
    return "READY_FOR_PARTNER_CENTER_PACKAGE_UPLOAD"
