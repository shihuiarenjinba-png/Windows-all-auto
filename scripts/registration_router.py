"""Final Store registration router; never infer registration from an intermediate EXE.

This module is pure: no Partner Center access, CAS, local filesystem writes,
or credential handling. Unresolved packaging is a HOLD, not a guessed type.
"""
from __future__ import annotations

REGISTRATION_SELECTIONS = {
    "MSIX_OR_PWA_APP": "MSIX or PWA app",
    "EXE_OR_MSI_APP": "EXE or MSI app",
    "GDK_GAME": "GDK game",
    "MSIX_OR_PWA_GAME": "MSIX or PWA game",
}
BASE_IDENTITY_FIELDS = [
    "store_id", "reserved_display_name", "identity_name", "publisher",
    "publisher_display_name", "package_family_name", "package_sid",
]
GDK_IDENTITY_FIELDS = BASE_IDENTITY_FIELDS + ["xbox_title_id", "xbox_scid", "msa_app_id"]
IDENTITY_STATUSES = {"NOT_RECEIVED", "RECEIVED", "IDENTITY_REFERENCE_AVAILABLE"}

# Explicitly approved final packaging strategies for the two pinned canaries.
# The existence of an intermediate unsigned EXE is NOT a strategy.
PINNED_STRATEGIES = {
    ("GAME", "signal-sprint"): "GDK",
    ("APP", "offline-notes-canary"): "MSIX",
}
FINAL_STRATEGY_TO_REGISTRATION = {
    ("APP", "MSIX"): "MSIX_OR_PWA_APP",
    ("APP", "PWA"): "MSIX_OR_PWA_APP",
    ("APP", "EXE_OR_MSI"): "EXE_OR_MSI_APP",
    ("GAME", "GDK"): "GDK_GAME",
    ("GAME", "MSIX"): "MSIX_OR_PWA_GAME",
    ("GAME", "PWA"): "MSIX_OR_PWA_GAME",
}


class RegistrationHold(ValueError):
    pass


def resolve(product_type: str, slug: str, final_strategy: str | None = None,
            declared: str | None = None) -> tuple[str, str]:
    """Return (machine registration_type, Partner Center selection).

    The pinned canaries have an explicitly fixed final strategy. For other
    products the final strategy must be supplied and verified independently.
    A mere .exe artifact is never evidence for EXE_OR_MSI_APP.
    """
    if not isinstance(product_type, str) or not isinstance(slug, str):
        raise RegistrationHold("HOLD_REGISTRATION_TYPE_UNRESOLVED")
    pinned = PINNED_STRATEGIES.get((product_type, slug))
    if final_strategy is None:
        final_strategy = pinned
    if pinned is not None and final_strategy != pinned:
        raise RegistrationHold("REGISTRATION_STRATEGY_CONFLICT")
    registration = FINAL_STRATEGY_TO_REGISTRATION.get((product_type, final_strategy))
    if registration is None:
        raise RegistrationHold("HOLD_REGISTRATION_TYPE_UNRESOLVED")
    if declared is not None and declared != registration:
        raise RegistrationHold("REGISTRATION_TYPE_CONFLICT")
    return registration, REGISTRATION_SELECTIONS[registration]


def registration_contract(product_type: str, slug: str,
                          packaging_family: str | None,
                          build_artifact_kind: str,
                          registration_evidence: list[str],
                          identity_status: str,
                          declared: str | None = None) -> dict:
    """Create the machine- and human-readable Partner Center handoff.

    Classification comes from the final packaging family. The artifact kind
    is recorded as evidence only, so an intermediate EXE can never change an
    MSIX app into an EXE/MSI app.
    """
    registration, selection = resolve(product_type, slug, packaging_family, declared)
    if (not isinstance(build_artifact_kind, str) or not build_artifact_kind
            or not isinstance(registration_evidence, list)
            or not registration_evidence
            or any(not isinstance(item, str) or not item for item in registration_evidence)
            or identity_status not in IDENTITY_STATUSES):
        raise RegistrationHold("HOLD_REGISTRATION_TYPE_UNRESOLVED")
    required = GDK_IDENTITY_FIELDS if registration == "GDK_GAME" else BASE_IDENTITY_FIELDS
    user_required = identity_status == "NOT_RECEIVED"
    if identity_status == "RECEIVED":
        action = "NO_PARTNER_CENTER_ACTION_IDENTITY_ALREADY_RECEIVED"
    elif identity_status == "IDENTITY_REFERENCE_AVAILABLE":
        action = "WAIT_FACTORY_PROMOTION_AND_SOURCE_BINDING"
    else:
        action = "PARTNER_CENTER_SELECT_" + registration + "_AND_PROVIDE_IDENTITY"
    reasons = {
        "MSIX_OR_PWA_APP": "Final APP packaging is MSIX/PWA; an intermediate EXE does not change it.",
        "EXE_OR_MSI_APP": "Final APP distribution remains unpackaged EXE/MSI.",
        "GDK_GAME": "Final GAME packaging uses Microsoft GDK/MSIXVC.",
        "MSIX_OR_PWA_GAME": "Final GAME packaging is MSIX/PWA without GDK.",
    }
    return {
        "product_type": product_type,
        "packaging_family": packaging_family,
        "build_artifact_kind": build_artifact_kind,
        "registration_type": registration,
        "partner_center_selection": selection,
        "registration_reason": reasons[registration],
        "registration_evidence": registration_evidence,
        "user_registration_required": user_required,
        "store_identity_status": identity_status,
        "required_identity_fields": required,
        "registration_event": "USER_ID_REQUEST" if user_required
                              else "PARTNER_CENTER_REGISTRATION_REQUEST",
        "next_action": action,
    }


def validate_handoff_job(job: dict) -> None:
    """Validate optional registration metadata without breaking older queues.

    New PRE-IDENTITY queues always include both fields. Old check-only jobs
    without registration metadata remain readable for safe migration.
    """
    registration = job.get("registration_type")
    selection = job.get("partner_center_selection")
    if registration is None and selection is None:
        return
    if registration not in REGISTRATION_SELECTIONS:
        raise RegistrationHold("HOLD_REGISTRATION_TYPE_UNRESOLVED")
    if selection != REGISTRATION_SELECTIONS[registration]:
        raise RegistrationHold("REGISTRATION_SELECTION_CONFLICT")
    kind = job.get("kind")
    if kind == "GAME_SIGNAL_SPRINT" and registration != "GDK_GAME":
        raise RegistrationHold("REGISTRATION_TYPE_CONFLICT")
    if kind == "APP_CANARY" and registration != "MSIX_OR_PWA_APP":
        raise RegistrationHold("REGISTRATION_TYPE_CONFLICT")
    if kind == "STORE_KNOWN_GOOD" and registration not in {
            "MSIX_OR_PWA_APP", "EXE_OR_MSI_APP"}:
        raise RegistrationHold("REGISTRATION_TYPE_CONFLICT")
    rich = {
        "product_type", "packaging_family", "build_artifact_kind",
        "registration_reason", "registration_evidence",
        "user_registration_required", "store_identity_status",
        "required_identity_fields", "registration_event", "next_action",
    }
    if not any(key in job for key in rich):
        return
    if not rich.issubset(job):
        raise RegistrationHold("REGISTRATION_HANDOFF_INCOMPLETE")
    expected = registration_contract(
        job["product_type"], job.get("slug", ""), job["packaging_family"],
        job["build_artifact_kind"], job["registration_evidence"],
        job["store_identity_status"], job["registration_type"],
    )
    if any(job.get(key) != value for key, value in expected.items()):
        raise RegistrationHold("REGISTRATION_HANDOFF_CONFLICT")
    evidence = job["registration_evidence"]
    expected_factory = ("factory_contract:" + str(job.get("repository")) + "@"
                        + str(job.get("source_sha")) + ":packaging_family="
                        + str(job["packaging_family"]))
    if expected_factory not in evidence:
        raise RegistrationHold("REGISTRATION_HANDOFF_CONFLICT")
    if kind == "GAME_SIGNAL_SPRINT":
        expected_provisioner = (
            "provisioner_contract:" + str(job.get("provisioner_repository")) + "@"
            + str(job.get("provisioner_head_sha")) + ":registration_type="
            + str(job["registration_type"])
        )
        if expected_provisioner not in evidence:
            raise RegistrationHold("REGISTRATION_HANDOFF_CONFLICT")
