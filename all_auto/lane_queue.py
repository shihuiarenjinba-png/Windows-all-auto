"""Immutable APP/GAME transport keys and isolated local QA queue layout.

No Store action is performed here. This module does not infer Partner Center
values; a Store ID in a handoff remains an untrusted claim for local QA.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

REQUEST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{3,127}$")
BRANCH = re.compile(r"^codex/[A-Za-z0-9._/-]+$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
STORE = re.compile(r"^[A-Za-z0-9]{8,32}$")
PFN = re.compile(r"^[A-Za-z0-9._-]+_[a-z0-9]{13}$")
PACKAGE_SID = re.compile(r"^S-1-15-2(?:-\d+){7}$")
LANES = {
    "app": ("APP", "AI-App-Factory", "https://github.com/shihuiarenjinba-png/AI-App-Factory"),
    "game": ("GAME", "AI-Game-Factory", "https://github.com/shihuiarenjinba-png/AI-Game-Factory"),
    "3d-game": ("GAME_3D", "3d-game-factory", "shihuiarenjinba-png/3d-game-factory"),
}
IMMUTABLE = ("request_id", "product_type", "source_factory",
             "source_repository", "source_branch", "source_sha", "slug")


def validate_immutable(data: dict, kind: str) -> dict:
    """Check a complete immutable contract or mark an old artifact as legacy.

    Legacy bundles remain QA-only for compatibility; they never prove E2E PASS.
    A partially populated contract must fail closed rather than downgrade.
    """
    if kind not in LANES:
        return {}
    present = any(key in data for key in
                  ("request_id", "product_type", "source_factory", "source_branch",
                   "expected_head_sha", "factory_head_sha", "store_id"))
    if not present and kind != "3d-game":
        return {"contract_status": "LEGACY_HOLD"}
    product_type, factory, repository = LANES[kind]
    for field in IMMUTABLE:
        if not isinstance(data.get(field), str) or not data[field]:
            raise ValueError("HANDOFF_HOLD: incomplete immutable key " + field)
    if data["product_type"] != product_type or data["source_factory"] != factory:
        raise ValueError("HANDOFF_HOLD: APP/GAME lane collision")
    if data["source_repository"] != repository:
        raise ValueError("HANDOFF_HOLD: source repository/factory mismatch")
    if not REQUEST.fullmatch(data["request_id"]):
        raise ValueError("HANDOFF_HOLD: invalid request_id")
    branch = data["source_branch"]
    if not BRANCH.fullmatch(branch) or ".." in branch or "//" in branch:
        raise ValueError("HANDOFF_HOLD: invalid codex source branch")
    if not SHA40.fullmatch(data["source_sha"]) or data.get("expected_head_sha") != data["source_sha"]:
        raise ValueError("HANDOFF_HOLD: immutable source SHA / expected HEAD mismatch")
    head_field = "factory_build_head" if kind == "3d-game" else "factory_head_sha"
    head = data.get(head_field, data["source_sha"])
    if not isinstance(head, str) or not SHA40.fullmatch(head):
        raise ValueError("HANDOFF_HOLD: invalid Factory MSIX build HEAD")
    identity = data.get("identity") if isinstance(data.get("identity"), dict) else {}
    store_id = identity.get("store_id") if kind == "3d-game" else data.get("store_id")
    if not isinstance(store_id, str) or not STORE.fullmatch(store_id):
        raise ValueError("HANDOFF_HOLD: missing claimed official Store ID")
    if kind == "3d-game":
        if not isinstance(data.get("local_package_sha256"), str) or not SHA64.fullmatch(data["local_package_sha256"]):
            raise ValueError("HANDOFF_HOLD: invalid 3D local package provenance")
        if not isinstance(identity.get("package_family_name"), str) or not PFN.fullmatch(identity["package_family_name"]):
            raise ValueError("HANDOFF_HOLD: missing 3D package family name")
        if not isinstance(identity.get("package_sid"), str) or not PACKAGE_SID.fullmatch(identity["package_sid"]):
            raise ValueError("HANDOFF_HOLD: missing 3D package SID")
    if data.get("signature_status") not in (None, "UNSIGNED"):
        raise ValueError("HANDOFF_HOLD: unsupported signing claim in unsigned QA transfer")
    return {
        "contract_status": "IMMUTABLE_QA_ONLY",
        "request_id": data["request_id"],
        "product_type": product_type,
        "source_factory": factory,
        "source_branch": branch,
        "expected_head_sha": data["source_sha"],
        head_field: head,
        "claimed_store_id": store_id,
        **({
            "local_package_sha256": data["local_package_sha256"],
            "claimed_package_family_name": identity["package_family_name"],
            "claimed_package_sid": identity["package_sid"],
        } if kind == "3d-game" else {}),
    }


def relative_package_path(info: dict) -> Path:
    """The same deterministic layout is used by central and Windows pullers."""
    folder = info["slug"] + "-" + info["package_sha256"][:12]
    if info.get("contract_status") == "IMMUTABLE_QA_ONLY" or info.get("request_id"):
        kind = info.get("product_type")
        if kind not in ("APP", "GAME", "GAME_3D"):
            raise ValueError("HANDOFF_HOLD: invalid local QA lane")
        return Path(kind) / folder
    return Path(folder)


def _unique_receipt_pairs(pairs):
    """An existing QA receipt must not hide a second request or source key."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("HANDOFF_HOLD: duplicate existing QA receipt key")
        result[key] = value
    return result


def _reject_nonfinite_receipt(_value):
    raise ValueError("HANDOFF_HOLD: non-finite existing QA receipt")


def check_request_conflict(target: Path, info: dict) -> None:
    """Reject reuse of a request_id across ALL lanes or product bindings.

    A matching source SHA is insufficient: the same request must never be
    relabeled from APP to GAME, rebound to another slug/Factory/branch, or
    hidden behind an ambiguous persisted receipt. Package revisions with the
    same immutable product binding remain possible; byte/provenance replay
    checks are enforced separately by stage_bundle.
    """
    request_id = info.get("request_id")
    if request_id is None:
        return  # Legacy QA-only bundles have no immutable request contract.
    if target.is_symlink():
        raise ValueError("HANDOFF_HOLD: linked local QA queue")
    if not target.exists():
        return
    if not target.is_dir():
        raise ValueError("HANDOFF_HOLD: invalid local QA queue")
    immutable_keys = (
        "request_id", "product_type", "source_factory", "source_repository",
        "source_branch", "source_sha", "expected_head_sha", "slug", "type",
    )
    # A request_id is global to the transport, not unique only inside its
    # claimed APP/GAME/GAME_3D directory. Bound each scan for local safety.
    for lane_name in ("APP", "GAME", "GAME_3D"):
        lane = target / lane_name
        if lane.is_symlink():
            raise ValueError("HANDOFF_HOLD: linked local QA lane")
        if not lane.exists():
            continue
        if not lane.is_dir():
            raise ValueError("HANDOFF_HOLD: invalid local QA lane")
        folders = list(lane.iterdir())
        if len(folders) > 1000:
            raise ValueError("HANDOFF_HOLD: local QA lane capacity exceeded")
        for folder in folders:
            if folder.is_symlink() or not folder.is_dir():
                raise ValueError("HANDOFF_HOLD: unsafe existing local QA folder")
            path = folder / "handoff.json"
            if (path.is_symlink() or not path.is_file()
                    or not 0 < path.stat().st_size <= 32768):
                raise ValueError("HANDOFF_HOLD: corrupt existing QA receipt")
            try:
                old = json.loads(
                    path.read_text(encoding="utf-8"),
                    object_pairs_hook=_unique_receipt_pairs,
                    parse_constant=_reject_nonfinite_receipt,
                )
            except (ValueError, TypeError, UnicodeError, OSError):
                raise ValueError("HANDOFF_HOLD: corrupt existing QA receipt") from None
            if type(old) is not dict:
                raise ValueError("HANDOFF_HOLD: corrupt existing QA receipt")
            if old.get("request_id") == request_id:
                # Version/build revisions may change, but the Store product
                # and embedded package identity may not be rebound to another
                # SKU under the same request. APP/GAME Store IDs live at the
                # top level; GAME_3D Store IDs live in identity.
                old_identity = old.get("identity")
                new_identity = info.get("identity")
                old_store = (
                    old_identity.get("store_id")
                    if old.get("type") == "3d-game"
                    and type(old_identity) is dict
                    else old.get("store_id")
                )
                identity_conflict = (
                    type(old_identity) is not dict
                    or type(new_identity) is not dict
                    or any(
                        old_identity.get(key) != new_identity.get(key)
                        for key in ("name", "publisher")
                    )
                    or old_store != info.get("claimed_store_id")
                    or (
                        old.get("type") == "3d-game"
                        and (
                            old_identity.get("package_family_name")
                            != info.get("claimed_package_family_name")
                            or old_identity.get("package_sid")
                            != info.get("claimed_package_sid")
                        )
                    )
                )
                if identity_conflict or any(
                    old.get(key) != info.get(key) for key in immutable_keys
                ):
                    raise ValueError(
                        "HANDOFF_CONFLICT: request_id reused with different product provenance"
                    )
