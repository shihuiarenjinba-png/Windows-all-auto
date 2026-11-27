from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_POINTER_PATH = "ops/active_e2e_handoff_pointer_v1.json"


class ActiveHandoffPointerError(ValueError):
    """Raised when the active handoff pointer or its referenced snapshot is invalid."""


def _fail(reason: str) -> None:
    raise ActiveHandoffPointerError("ACTIVE_HANDOFF_POINTER_HOLD: " + reason)


def git_blob_sha1(data: bytes) -> str:
    # Git's text checkout may materialize LF blobs as CRLF on Windows.
    # Normalize only CRLF pairs so the digest remains the repository blob SHA.
    canonical = data.replace(b"\r\n", b"\n")
    header = b"blob " + str(len(canonical)).encode("ascii") + b"\0"
    return hashlib.sha1(header + canonical).hexdigest()


def _read_repo_file(root: Path, relative_path: Any) -> bytes:
    if not isinstance(relative_path, str) or not relative_path:
        _fail("snapshot path is missing")
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
        or "\\" in relative_path
    ):
        _fail("snapshot path is not a safe repository-relative path")

    target = root
    for part in relative.parts:
        target = target / part
        if target.is_symlink():
            _fail("snapshot path contains a symlink")

    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        _fail("snapshot file is missing or escapes repository root")

    if not resolved.is_file():
        _fail("snapshot target is not a regular file")
    try:
        return resolved.read_bytes()
    except OSError:
        _fail("snapshot file cannot be read")


def _read_json(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail(label + " is not valid UTF-8 JSON")
    if not isinstance(value, dict):
        _fail(label + " must be a JSON object")
    return value


def load_active_handoff_pointer(
    repository_root: Path,
    pointer_path: str = DEFAULT_POINTER_PATH,
) -> dict[str, Any]:
    """Load only the SHA-verified pointer-selected overlay and queue.

    The canonical ledger is intentionally never read as a fallback. An invalid
    pointer or snapshot returns HOLD instead of reviving a stale embedded pointer.
    """
    root = repository_root.resolve()
    pointer_bytes = _read_repo_file(root, pointer_path)
    pointer = _read_json(pointer_bytes, "pointer manifest")

    if pointer.get("schema_version") != 1 or pointer.get("pointer_version") != 1:
        _fail("unsupported pointer schema")
    if pointer.get("status") != "ACTIVE":
        _fail("pointer is not active")
    if pointer.get("fallback_to_canonical_ledger") is not False:
        _fail("canonical-ledger fallback must remain disabled")
    if pointer.get("selection_policy") != "VERIFIED_POINTER_REFERENCED_OVERLAY_ONLY":
        _fail("unknown active snapshot selection policy")

    repository = pointer.get("repository")
    if not isinstance(repository, str) or not repository:
        _fail("repository binding is missing")

    active = pointer.get("active_snapshot")
    if not isinstance(active, dict):
        _fail("active snapshot reference is missing")
    overlay_ref = active.get("overlay")
    queue_ref = active.get("queue")
    if not isinstance(overlay_ref, dict) or not isinstance(queue_ref, dict):
        _fail("overlay and queue references must both be present")

    overlay_path = overlay_ref.get("path")
    queue_path = queue_ref.get("path")
    overlay_bytes = _read_repo_file(root, overlay_path)
    queue_bytes = _read_repo_file(root, queue_path)

    overlay_sha = overlay_ref.get("git_blob_sha")
    queue_sha = queue_ref.get("git_blob_sha")
    if not isinstance(overlay_sha, str) or git_blob_sha1(overlay_bytes) != overlay_sha:
        _fail("active overlay Git blob SHA mismatch")
    if not isinstance(queue_sha, str) or git_blob_sha1(queue_bytes) != queue_sha:
        _fail("active queue Git blob SHA mismatch")

    overlay = _read_json(overlay_bytes, "active overlay")
    queue = _read_json(queue_bytes, "completion queue")

    observed_at = active.get("observed_at_utc")
    if (
        overlay.get("repository") != repository
        or overlay.get("path") != overlay_path
        or overlay.get("observed_at_utc") != observed_at
        or queue.get("path") != queue_path
        or queue.get("source_observation") != overlay_path
        or queue.get("generated_at") != observed_at
    ):
        _fail("pointer, overlay and queue bindings disagree")

    canonical = overlay.get("canonical_ledger_reconciliation")
    legacy = pointer.get("legacy_embedded_pointer")
    pointer_canonical = pointer.get("canonical_ledger")
    if not isinstance(canonical, dict) or not isinstance(legacy, dict) or not isinstance(pointer_canonical, dict):
        _fail("canonical-ledger history metadata is incomplete")
    if (
        canonical.get("path") != pointer_canonical.get("path")
        or canonical.get("blob_sha") != pointer_canonical.get("git_blob_sha")
        or canonical.get("bytes") != pointer_canonical.get("bytes")
        or canonical.get("path") != legacy.get("path")
        or canonical.get("recorded_pr165_latest_live_head_sha") != legacy.get("recorded_pr165_head_sha")
        or canonical.get("directly_resolved_pr165_branch_head_sha") != legacy.get("directly_resolved_pr165_head_sha")
        or legacy.get("status") != "STALE_NOT_AUTHORITATIVE"
        or canonical.get("stale") is not True
        or canonical.get("rewritten") is not False
        or pointer_canonical.get("read_status") != "EMPTY_CONTENT"
        or pointer_canonical.get("rewritten") is not False
        or overlay.get("pr165", {}).get("head_sha") != legacy.get("directly_resolved_pr165_head_sha")
    ):
        _fail("stale canonical pointer and current live head are not reconciled")

    safety = pointer.get("safety")
    if not isinstance(safety, dict):
        _fail("safety gates are missing")
    for key in (
        "real_msix",
        "product_e2e_pass",
        "store_submission_allowed",
        "certification_allowed",
        "publish_allowed",
        "merge_allowed",
        "force_push_allowed",
    ):
        if safety.get(key) is not False:
            _fail("safety gate must remain false: " + key)
    if (
        overlay.get("e2e_pass") is not False
        or overlay.get("real_msix") is not False
        or overlay.get("store_submission_allowed") is not False
        or overlay.get("certification_allowed") is not False
        or overlay.get("publish_allowed") is not False
        or queue.get("global", {}).get("real_msix") is not False
        or queue.get("global", {}).get("store_submission_allowed") is not False
    ):
        _fail("snapshot contains an unsafe promotion state")

    return {
        "pointer": pointer,
        "overlay": overlay,
        "queue": queue,
        "overlay_path": overlay_path,
        "queue_path": queue_path,
    }
