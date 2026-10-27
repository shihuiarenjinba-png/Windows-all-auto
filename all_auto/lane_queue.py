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
STORE = re.compile(r"^[A-Za-z0-9]{8,32}$")
LANES = {"app": ("APP", "AI-App-Factory"), "game": ("GAME", "AI-Game-Factory")}
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
    if not present:
        return {"contract_status": "LEGACY_HOLD"}
    product_type, factory = LANES[kind]
    for field in IMMUTABLE:
        if not isinstance(data.get(field), str) or not data[field]:
            raise ValueError("HANDOFF_HOLD: incomplete immutable key " + field)
    if data["product_type"] != product_type or data["source_factory"] != factory:
        raise ValueError("HANDOFF_HOLD: APP/GAME lane collision")
    if data["source_repository"] != "https://github.com/shihuiarenjinba-png/" + factory:
        raise ValueError("HANDOFF_HOLD: source repository/factory mismatch")
    if not REQUEST.fullmatch(data["request_id"]):
        raise ValueError("HANDOFF_HOLD: invalid request_id")
    branch = data["source_branch"]
    if not BRANCH.fullmatch(branch) or ".." in branch or "//" in branch:
        raise ValueError("HANDOFF_HOLD: invalid codex source branch")
    if not SHA40.fullmatch(data["source_sha"]) or data.get("expected_head_sha") != data["source_sha"]:
        raise ValueError("HANDOFF_HOLD: immutable source SHA / expected HEAD mismatch")
    head = data.get("factory_head_sha", data["source_sha"])
    if not isinstance(head, str) or not SHA40.fullmatch(head):
        raise ValueError("HANDOFF_HOLD: invalid Factory MSIX build HEAD")
    if not isinstance(data.get("store_id"), str) or not STORE.fullmatch(data["store_id"]):
        raise ValueError("HANDOFF_HOLD: missing claimed official Store ID")
    if data.get("signature_status") not in (None, "UNSIGNED"):
        raise ValueError("HANDOFF_HOLD: unsupported signing claim in unsigned QA transfer")
    return {
        "contract_status": "IMMUTABLE_QA_ONLY",
        "request_id": data["request_id"],
        "product_type": product_type,
        "source_factory": factory,
        "source_branch": branch,
        "expected_head_sha": data["source_sha"],
        "factory_head_sha": head,
        "claimed_store_id": data["store_id"],
    }


def relative_package_path(info: dict) -> Path:
    """The same deterministic layout is used by central and Windows pullers."""
    folder = info["slug"] + "-" + info["package_sha256"][:12]
    if info.get("contract_status") == "IMMUTABLE_QA_ONLY" or info.get("request_id"):
        kind = info.get("product_type")
        if kind not in ("APP", "GAME"):
            raise ValueError("HANDOFF_HOLD: invalid local QA lane")
        return Path(kind) / folder
    return Path(folder)


def check_request_conflict(target: Path, info: dict) -> None:
    """Reject a changed source_sha for the same request_id before copying bytes."""
    request_id = info.get("request_id")
    if request_id is None:
        return
    lane = target / info["product_type"]
    if lane.is_symlink():
        raise ValueError("HANDOFF_HOLD: linked local QA lane")
    if not lane.exists():
        return
    if not lane.is_dir():
        raise ValueError("HANDOFF_HOLD: invalid local QA lane")
    folders = list(lane.iterdir())
    if len(folders) > 1000:
        raise ValueError("HANDOFF_HOLD: local QA lane capacity exceeded")
    for folder in folders:
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("HANDOFF_HOLD: unsafe existing local QA folder")
        path = folder / "handoff.json"
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32768:
            raise ValueError("HANDOFF_HOLD: corrupt existing QA receipt")
        old = json.loads(path.read_text(encoding="utf-8"))
        if old.get("request_id") == request_id and old.get("source_sha") != info["source_sha"]:
            raise ValueError("HANDOFF_CONFLICT: request_id reused with changed source_sha")
