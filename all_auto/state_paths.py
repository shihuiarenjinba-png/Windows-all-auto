"""Resolve one durable state root shared by all Windows-all-auto worktrees."""
from __future__ import annotations

import os
from pathlib import Path


def state_root(repo_root: Path | None = None) -> Path:
    configured = os.environ.get("WINDOWS_ALL_AUTO_STATE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    legacy = Path.home() / "Desktop" / "Windows-all-auto-dca-upload" / ".uploader-run"
    if legacy.is_dir():
        return legacy.resolve()
    root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[1]
    return root / ".uploader-run"


def product_state_dir(product: str, repo_root: Path | None = None) -> Path:
    if not product or any(ch in product for ch in ("/", chr(92), ":")) or product in {".", ".."}:
        raise ValueError("invalid product key for state directory")
    return state_root(repo_root) / product
