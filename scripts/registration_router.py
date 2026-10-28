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
