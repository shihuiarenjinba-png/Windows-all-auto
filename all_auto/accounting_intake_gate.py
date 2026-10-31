"""Fail-closed accounting SKU admission at the real MSIX local QA staging boundary.

The handoff JSON is untrusted and cannot attest market fit, calculations,
official tax guidance, or Partner Center availability. Only an out-of-band
trusted callback may supply independently checked PACKAGE evidence. The
existing bridge poller supplies no such callback, so accounting artifacts HOLD.
This gate is NOT a Store release/signature/GUI QA approval.
"""
from __future__ import annotations

import re
from typing import Callable

from scripts.accounting_country_gate import FACTORY, SPECS

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
FACTORY_URL = "https://github.com/" + FACTORY


class AccountingIntakeHold(ValueError):
    """A fixed, non-secret package admission HOLD."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise AccountingIntakeHold(code)


def require_accounting_package_attestation(
    info: dict, *,
    attest: Callable[[dict], dict] | None = None,
) -> None:
    """Require independent, exact-product PACKAGE evidence before staging.

    The callback must be supplied by reviewed application code, never loaded
    from the handoff bundle or queue metadata. It must first run the existing
    authenticated accounting PACKAGE gate (including reviewed market fit,
    per-fixture Actions, official IRS review for US, and authenticated
    single-country Partner Center observation). This function only verifies
    the resulting binding; it does not authenticate the callback itself.

    Re-run on every staging attempt, including idempotent replay. No persisted
    user-authored PASS file or queue field can bypass the gate.
    """
    _require(type(info) is dict, "HOLD_ACCOUNTING_INTAKE_INVALID")
    slug = info.get("slug")
    if slug not in SPECS:
        return
    market = SPECS[slug][0]
    source_sha = info.get("source_sha")
    build_head = info.get("factory_head_sha")
    package_sha = info.get("package_sha256")
    request_id = info.get("request_id")
    identity = info.get("identity")
    _require(
        info.get("type") == "app"
        and info.get("product_type") == "APP"
        and info.get("source_repository") == FACTORY_URL
        and type(source_sha) is str and _SHA40.fullmatch(source_sha) is not None
        and type(build_head) is str and _SHA40.fullmatch(build_head) is not None
        and type(package_sha) is str and _SHA64.fullmatch(package_sha) is not None
        and request_id == f"app-{slug}-{source_sha[:12]}"
        and type(info.get("claimed_store_id")) is str
        and bool(info["claimed_store_id"])
        and type(identity) is dict
        and all(type(identity.get(k)) is str and bool(identity[k])
                for k in ("name", "publisher", "version")),
        "HOLD_ACCOUNTING_INTAKE_PROVENANCE_CONFLICT",
    )
    _require(callable(attest), "HOLD_ACCOUNTING_INTAKE_AUTHENTICATED_GATE_MISSING")
    try:
        evidence = attest(info)
    except Exception as exc:
        raise AccountingIntakeHold("HOLD_ACCOUNTING_INTAKE_GATE_UNAVAILABLE") from None
    _require(type(evidence) is dict, "HOLD_ACCOUNTING_INTAKE_EVIDENCE_INVALID")
    expected = {
        "verification_method": "INDEPENDENT_ACCOUNTING_PACKAGE_GATE",
        "verified": True,
        "phase": "PACKAGE",
        "gate": "ACCOUNTING_E2E_PACKAGE_PRECHECK_PASS",
        "source_repository": FACTORY,
        "slug": slug,
        "request_id": request_id,
        "source_sha": source_sha,
        "factory_build_head": build_head,
        "package_sha256": package_sha,
        "store_id": info["claimed_store_id"],
        "identity_name": identity["name"],
        "identity_publisher": identity["publisher"],
        "package_version": identity["version"],
        "market": market,
        "store_markets": [market],
        "all_markets_default": False,
        "market_fit_verified": True,
    }
    _require(set(evidence) == set(expected)
             and all(type(evidence[k]) is type(value) and evidence[k] == value
                     for k, value in expected.items()),
             "HOLD_ACCOUNTING_INTAKE_EVIDENCE_CONFLICT")
