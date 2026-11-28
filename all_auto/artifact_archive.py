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


def copy_to_approved_external_backup(config: dict, package: Path, receipt: Path,
                                     backup_root: Path) -> dict:
    """Copy an archived package only when the exact destination is owner-approved."""
    approval = config.get("external_backup_approval")
    if (not isinstance(approval, dict) or approval.get("status") != "OWNER_APPROVED" or
            approval.get("product_id") != config.get("product_id") or
            approval.get("submission_id") != config.get("submission_id") or
            not isinstance(approval.get("approval_ref"), str) or not approval["approval_ref"].strip() or
            not isinstance(approval.get("approved_at"), str) or not approval["approved_at"].strip()):
        raise ArtifactArchiveError("external backup transfer requires a Product/Draft-bound owner approval")
    requested_root = backup_root.expanduser().resolve()
    approved_root = Path(str(approval.get("destination_root", ""))).expanduser().resolve()
    if requested_root != approved_root:
        raise ArtifactArchiveError("external backup destination does not match the owner-approved exact path")
    if backup_root.expanduser().is_symlink():
        raise ArtifactArchiveError("external backup destination must not be a symbolic link")
    package = package.expanduser().resolve(strict=True)
    receipt = receipt.expanduser().resolve(strict=True)
    verified = verify_file(config, package, expected_sha256=config.get("expected_sha256"),
                           max_bytes=int(config.get("max_bytes", 4_000_000_000)))
    record = json.loads(receipt.read_text(encoding="utf-8"))
    if (record.get("product_id") != config["product_id"] or
            record.get("submission_id") != config["submission_id"] or
            record.get("sha256") != verified.sha256 or
            record.get("package_file_name") != verified.file_name):
        raise ArtifactArchiveError("archive receipt does not match the exact approved backup package")
    relative = Path(str(config["product_id"])) / str(config["version"]) / verified.sha256
    destination_dir = requested_root / relative
    target = destination_dir / verified.file_name
    target_receipt = target.with_suffix(target.suffix + ".receipt.json")
    if target.exists() or target_receipt.exists():
        if (target.is_file() and target_receipt.is_file() and
                verify_file(config, target, expected_sha256=verified.sha256,
                            max_bytes=int(config.get("max_bytes", 4_000_000_000))).sha256 == verified.sha256 and
                json.loads(target_receipt.read_text(encoding="utf-8")) == record):
            return {"status": "BACKUP_ALREADY_VERIFIED", "path": str(target),
                    "receipt": str(target_receipt), "sha256": verified.sha256}
        raise ArtifactArchiveError("external backup target exists with conflicting or incomplete evidence")
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    stage_dir = destination_dir.parent / f".backup-{uuid4().hex}"
    try:
        stage_dir.mkdir()
        staged_package = stage_dir / verified.file_name
        staged_receipt = staged_package.with_suffix(staged_package.suffix + ".receipt.json")
        shutil.copyfile(package, staged_package)
        copied = verify_file(config, staged_package, expected_sha256=verified.sha256,
                             max_bytes=int(config.get("max_bytes", 4_000_000_000)))
        if copied.sha256 != verified.sha256:
            raise ArtifactArchiveError("external backup copy SHA-256 mismatch")
        shutil.copyfile(receipt, staged_receipt)
        stage_dir.replace(destination_dir)
        return {"status": "BACKUP_COPIED_AND_VERIFIED", "path": str(target),
                "receipt": str(target_receipt), "sha256": copied.sha256,
                "approval_ref": approval["approval_ref"]}
    except Exception:
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        raise
