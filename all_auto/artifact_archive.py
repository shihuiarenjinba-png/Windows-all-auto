"""Create-only, content-addressed local archive for verified Store packages."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from uuid import uuid4

from uploader.core import UploadError, read_msix_manifest_metadata, verify_file


class ArtifactArchiveError(ValueError):
    pass


def archive_verified_package(config: dict, package: Path, archive_root: Path) -> dict:
    package = package.expanduser().resolve(strict=True)
    if package.is_symlink() or not package.is_file():
        raise ArtifactArchiveError("archive source must be a regular non-symlink file")
    verified = verify_file(config, package, expected_sha256=config.get("expected_sha256"),
                           max_bytes=int(config.get("max_bytes", 4_000_000_000)))
    manifest = read_msix_manifest_metadata(package)
    if manifest["signature_state"] != "UNSIGNED":
        signature = "SIGNED_BLOCK_PRESENT"
    else:
        signature = "UNSIGNED"
    target_root = archive_root.expanduser().resolve()
    if archive_root.expanduser().is_symlink():
        raise ArtifactArchiveError("archive root must not be a symlink")
    target = target_root / str(config["product_id"]) / str(config["version"]) / verified.sha256
    target = target / verified.file_name
    receipt_path = target.with_suffix(target.suffix + ".receipt.json")
    if target.exists() or receipt_path.exists():
        if target.is_file() and receipt_path.is_file():
            existing = verify_file(config, target, expected_sha256=verified.sha256,
                                   max_bytes=int(config.get("max_bytes", 4_000_000_000)))
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if existing.sha256 == verified.sha256 and receipt.get("sha256") == verified.sha256:
                return {"status": "ARCHIVE_ALREADY_PRESENT", "path": str(target),
                        "receipt": str(receipt_path), "sha256": verified.sha256}
        raise ArtifactArchiveError("archive target already exists with incomplete or conflicting evidence")
    sha_directory = target.parent
    sha_directory.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = sha_directory.parent / f".archive-{uuid4().hex}"
    staging_dir.mkdir()
    staged_package = staging_dir / target.name
    staged_receipt = staging_dir / receipt_path.name
    try:
        shutil.copyfile(package, staged_package)
        copied = verify_file(config, staged_package, expected_sha256=verified.sha256,
                             max_bytes=int(config.get("max_bytes", 4_000_000_000)))
        if copied.sha256 != verified.sha256:
            raise ArtifactArchiveError("SHA-256 changed while copying to archive")
        record = {
            "schema_version": "all-auto-local-package-archive/1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "product_id": config["product_id"], "submission_id": config["submission_id"],
            "product_name": config["product_name"], "repository": config["repository"],
            "source_sha": config.get("source_sha"), "artifact_id": config.get("artifact_id"),
            "artifact_run_id": config.get("artifact_run_id"),
            "package_file_name": copied.file_name, "sha256": copied.sha256,
            "identity": copied.identity_name, "publisher": copied.publisher,
            "version": copied.version, "architecture": copied.architecture,
            "target_device_families": manifest["target_device_families"],
            "signature_state": signature,
            "partner_center_uploaded": False,
        }
        with staged_receipt.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
        # Each exact SHA gets an immutable directory; no prior archive is replaced.
        if sha_directory.exists() or sha_directory.is_symlink():
            raise ArtifactArchiveError("archive SHA directory already exists; reconcile before writing")
        staging_dir.replace(sha_directory)
        return {"status": "ARCHIVED_VERIFIED", "path": str(target),
                "receipt": str(receipt_path), "sha256": verified.sha256}
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
