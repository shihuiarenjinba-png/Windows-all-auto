"""Verify and stage an exact Store artifact from a product repository.

This module is local-only. It validates bytes already downloaded from GitHub
Actions and never opens Partner Center, installs an MSIX, signs anything, or
authorizes upload/certification/publish.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

from all_auto.store_product_handoff import normalize_store_product_handoff


RECEIPT_SCHEMA = "local-store-product-artifact-pull-receipt/1"
PRODUCT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
WINDOWS_PATH_LENGTH_GUARD = os.name == "nt"
WINDOWS_LEGACY_MAX_PATH = 260


class ProductArtifactPullError(ValueError):
    pass


def _one(root: Path, name: str) -> Path:
    matches = [p for p in root.rglob(name) if p.is_file()]
    if len(matches) != 1:
        raise ProductArtifactPullError(
            f"expected exactly one {name}; got {len(matches)}"
        )
    return matches[0]


def _one_msix(root: Path) -> Path:
    matches = [p for p in root.rglob("*.msix") if p.is_file()]
    if len(matches) != 1:
        raise ProductArtifactPullError(
            f"expected exactly one MSIX; got {len(matches)}"
        )
    return matches[0]


def _hash(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ProductArtifactPullError(f"{path.name} must contain a JSON object")
    return value


def validate_extracted_store_artifact(
    root: Path,
    *,
    repository_full_name: str,
    run_id: int,
    artifact_name: str,
) -> dict[str, Any]:
    if not root.is_dir():
        raise ProductArtifactPullError("downloaded artifact directory is missing")
    if not repository_full_name or "/" not in repository_full_name:
        raise ProductArtifactPullError("repository_full_name is invalid")
    if type(run_id) is not int or run_id <= 0:
        raise ProductArtifactPullError("run_id must be a positive integer")
    if not artifact_name.strip():
        raise ProductArtifactPullError("artifact_name is required")

    handoff_path = _one(root, "store-product-handoff.json")
    validation_path = _one(root, "msix_validation.json")
    checksum_path = _one(root, "msix.sha256.txt")
    msix_path = _one_msix(root)

    handoff = normalize_store_product_handoff(_load(handoff_path))
    validation = _load(validation_path)

    expected_repo = f"https://github.com/{repository_full_name}"
    if handoff["product"].get("repository") != expected_repo:
        raise ProductArtifactPullError("handoff repository mismatch")
    if handoff["package"].get("artifact_run_id") != run_id:
        raise ProductArtifactPullError("handoff artifact_run_id mismatch")
    if handoff["package"]["file_name"] != msix_path.name:
        raise ProductArtifactPullError("handoff package filename mismatch")

    actual_sha = _hash(msix_path)
    expected_sha = handoff["package"]["package_sha256"].lower()
    if actual_sha != expected_sha:
        raise ProductArtifactPullError("MSIX SHA256 mismatch with handoff")
    if str(validation.get("msix_sha256") or "").lower() != expected_sha:
        raise ProductArtifactPullError("MSIX SHA256 mismatch with validation report")

    checksum_line = checksum_path.read_text(encoding="utf-8-sig").strip()
    if checksum_line != f"{expected_sha}  {msix_path.name}":
        raise ProductArtifactPullError("MSIX checksum file mismatch")

    expected = {
        "source_commit": handoff["product"]["source_sha"],
        "store_id": handoff["identity"]["store_id"],
        "identity_name": handoff["identity"]["name"],
        "identity_publisher": handoff["identity"]["publisher"],
        "msix_version": handoff["identity"]["version"],
    }
    for key, value in expected.items():
        if validation.get(key) != value:
            raise ProductArtifactPullError(f"validation/handoff mismatch: {key}")

    exe_sha = handoff["package"]["exe_sha256"].lower()
    if str(validation.get("source_exe_sha256") or "").lower() != exe_sha:
        raise ProductArtifactPullError("source EXE SHA mismatch")
    if str(validation.get("unpacked_exe_sha256") or "").lower() != exe_sha:
        raise ProductArtifactPullError("unpacked EXE SHA mismatch")

    if validation.get("manifest_identity_verified") is not True:
        raise ProductArtifactPullError("Manifest Identity is not verified")
    if validation.get("makeappx_pack_unpack") != "PASS":
        raise ProductArtifactPullError("MakeAppx roundtrip is not PASS")
    for flag in ("signed", "store_submission_approved", "sale_approved"):
        if validation.get(flag) is not False:
            raise ProductArtifactPullError(f"unsafe validation flag: {flag}")

    return {
        "schema_version": RECEIPT_SCHEMA,
        "status": "LOCAL_STORE_PRODUCT_ARTIFACT_VERIFIED",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository_full_name": repository_full_name,
        "artifact_run_id": run_id,
        "artifact_name": artifact_name,
        "product_id": handoff["product"]["id"],
        "product_name": handoff["product"]["name"],
        "source_sha": handoff["product"]["source_sha"],
        "store_id": handoff["identity"]["store_id"],
        "identity": {
            "name": handoff["identity"]["name"],
            "publisher": handoff["identity"]["publisher"],
            "version": handoff["identity"]["version"],
            "architecture": handoff["identity"]["architecture"],
            "package_family_name": handoff["identity"].get("package_family_name", ""),
            "package_sid": handoff["identity"].get("package_sid", ""),
        },
        "package": {
            "file_name": msix_path.name,
            "sha256": actual_sha,
            "bytes": msix_path.stat().st_size,
        },
        "package_rebuilt": False,
        "security_bypass_used": False,
        "package_installed": False,
        "submitted_to_store": False,
        "certification_submitted": False,
        "published": False,
        "_source_paths": {
            "msix": str(msix_path),
            "handoff": str(handoff_path),
            "validation": str(validation_path),
            "checksum": str(checksum_path),
        },
    }


def select_github_artifact_metadata(
    artifacts: Any,
    *,
    artifact_name: str,
) -> dict[str, Any]:
    if not isinstance(artifacts, list):
        raise ProductArtifactPullError("GitHub artifact listing is invalid")
    matches = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict)
        and artifact.get("name") == artifact_name
        and artifact.get("expired") is False
    ]
    if len(matches) != 1:
        raise ProductArtifactPullError(
            f"expected exactly one live GitHub artifact named {artifact_name}; got {len(matches)}"
        )
    artifact = matches[0]
    artifact_id = artifact.get("id")
    size = artifact.get("size_in_bytes")
    digest = str(artifact.get("digest") or "")
    if type(artifact_id) is not int or artifact_id <= 0:
        raise ProductArtifactPullError("GitHub artifact id is invalid")
    if type(size) is not int or size <= 0:
        raise ProductArtifactPullError("GitHub artifact size is invalid")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ProductArtifactPullError("GitHub artifact digest is invalid")
    return {
        "github_artifact_id": artifact_id,
        "github_artifact_digest": digest,
        "github_artifact_size_in_bytes": size,
        "github_artifact_expired": False,
    }


def require_expected_identity(
    verified: dict[str, Any],
    *,
    store_id: str,
    identity_name: str,
    version: str,
    architecture: str,
) -> None:
    identity = verified.get("identity")
    if not isinstance(identity, dict):
        raise ProductArtifactPullError("verified identity is missing")
    expected = {
        "store_id": store_id,
        "identity_name": identity_name,
        "version": version,
        "architecture": architecture,
    }
    actual = {
        "store_id": str(verified.get("store_id") or ""),
        "identity_name": str(identity.get("name") or ""),
        "version": str(identity.get("version") or ""),
        "architecture": str(identity.get("architecture") or ""),
    }
    for key, value in expected.items():
        if actual[key] != value:
            raise ProductArtifactPullError(f"central registry mismatch: {key}")


def stage_verified_store_artifact(
    verified: dict[str, Any],
    *,
    target_root: Path,
) -> dict[str, Any]:
    if verified.get("schema_version") != RECEIPT_SCHEMA:
        raise ProductArtifactPullError("unsupported verified receipt schema")
    product_id = str(verified.get("product_id") or "").strip()
    source_sha = str(verified.get("source_sha") or "").strip().lower()
    run_id = verified.get("artifact_run_id")
    if (
        not PRODUCT_ID.fullmatch(product_id)
        or not HEX40.fullmatch(source_sha)
        or type(run_id) is not int
        or run_id <= 0
    ):
        raise ProductArtifactPullError("verified artifact binding is incomplete or unsafe")

    target_root = target_root.resolve()
    destination = target_root / product_id / f"{source_sha[:12]}-run{run_id}"
    staging = destination.parent / f".{destination.name}.staging"
    if destination.exists() or destination.is_symlink():
        raise ProductArtifactPullError("destination already exists; refusing to overwrite exact artifact")
    if staging.exists() or staging.is_symlink():
        raise ProductArtifactPullError("staging destination already exists; refusing ambiguous recovery")
    if target_root not in destination.resolve().parents:
        raise ProductArtifactPullError("destination escaped target root")

    sources = verified.get("_source_paths")
    if not isinstance(sources, dict):
        raise ProductArtifactPullError("verified source paths are missing")

    # Keep the atomic staging suffix from turning an otherwise acceptable
    # destination into an opaque WinError 3 on Windows hosts where legacy
    # MAX_PATH handling is still active.  Receipt paths remain ordinary paths;
    # callers only need to choose a shorter target root/workspace.
    if WINDOWS_PATH_LENGTH_GUARD:
        staging_paths = [staging]
        for key in ("msix", "handoff", "validation", "checksum"):
            source_name = Path(str(sources.get(key) or "")).name
            if source_name:
                staging_paths.append(staging / source_name)
        if any(len(str(path)) >= WINDOWS_LEGACY_MAX_PATH for path in staging_paths):
            raise ProductArtifactPullError(
                "Windows staging path exceeds the legacy MAX_PATH limit; "
                "choose a shorter --target-root/workspace"
            )

    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=False, exist_ok=False)
    copied: dict[str, Path] = {}
    try:
        for key in ("msix", "handoff", "validation", "checksum"):
            src = Path(str(sources.get(key) or ""))
            if not src.is_file():
                raise ProductArtifactPullError(f"verified source file disappeared: {key}")
            dst = staging / src.name
            shutil.copy2(src, dst)
            copied[key] = dst

        if _hash(copied["msix"]) != verified["package"]["sha256"]:
            raise ProductArtifactPullError("staged MSIX changed during copy")

        staging.rename(destination)
    except Exception:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    result = dict(verified)
    result.pop("_source_paths", None)
    result["staged_directory"] = str(destination)
    result["local_package_path"] = str(destination / copied["msix"].name)
    result["local_handoff_path"] = str(destination / copied["handoff"].name)
    result["local_validation_path"] = str(destination / copied["validation"].name)
    result["local_checksum_path"] = str(destination / copied["checksum"].name)
    return result


def write_immutable_receipt(path: Path, receipt: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise ProductArtifactPullError("receipt already exists; refusing to overwrite evidence")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
