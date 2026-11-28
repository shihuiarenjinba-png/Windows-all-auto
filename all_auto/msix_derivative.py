"""Verify that a test-signed MSIX is a signature-only derivative of a frozen package."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile
import xml.etree.ElementTree as ET
from typing import Any


SIGNATURE_MEMBER = "AppxSignature.p7x"
CODE_INTEGRITY_MEMBER = "AppxMetadata/CodeIntegrity.cat"
CONTENT_TYPES_MEMBER = "[Content_Types].xml"
ALLOWED_ADDED_SIGNATURE_MEMBERS = {SIGNATURE_MEMBER, CODE_INTEGRITY_MEMBER}


class DerivativeVerificationError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _members(path: Path) -> tuple[dict[str, str], bytes, int]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)):
                raise DerivativeVerificationError("duplicate member names are not allowed")
            if any(name.startswith(("/", "\\")) or ".." in PurePosixPath(name.replace("\\", "/")).parts
                   for name in names):
                raise DerivativeVerificationError("unsafe package member path")
            digests: dict[str, str] = {}
            manifest_data: bytes | None = None
            signature_size = 0
            for item in infos:
                digest = hashlib.sha256()
                captured = bytearray() if item.filename == "AppxManifest.xml" else None
                size = 0
                with archive.open(item) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        size += len(chunk)
                        digest.update(chunk)
                        if captured is not None:
                            if size > 4 * 1024 * 1024:
                                raise DerivativeVerificationError("AppxManifest.xml exceeds the size limit")
                            captured.extend(chunk)
                digests[item.filename] = digest.hexdigest()
                if captured is not None:
                    manifest_data = bytes(captured)
                if item.filename == SIGNATURE_MEMBER:
                    signature_size = size
            if manifest_data is None:
                raise DerivativeVerificationError("AppxManifest.xml is absent")
            return digests, manifest_data, signature_size
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise DerivativeVerificationError("package archive cannot be read") from exc


def _identity(manifest: bytes) -> dict[str, str]:
    try:
        root = ET.fromstring(manifest)
    except ET.ParseError as exc:
        raise DerivativeVerificationError("AppxManifest.xml is absent or invalid") from exc
    node = next((element for element in root.iter() if element.tag.endswith("}Identity")), None)
    if node is None:
        raise DerivativeVerificationError("manifest Identity is absent")
    return {key: str(node.get(key, "")) for key in
            ("Name", "Publisher", "Version", "ProcessorArchitecture")}


def _content_types_signature_only(source: bytes, derived: bytes) -> tuple[bool, str]:
    namespace = "{http://schemas.openxmlformats.org/package/2006/content-types}"
    try:
        before, after = ET.fromstring(source), ET.fromstring(derived)
    except ET.ParseError:
        return False, "content-types XML is invalid"
    def mappings(root: ET.Element) -> tuple[dict[str, str], dict[str, str]]:
        defaults, overrides = {}, {}
        for item in root:
            if item.tag == namespace + "Default":
                defaults[str(item.get("Extension", "")).lower()] = str(item.get("ContentType", ""))
            elif item.tag == namespace + "Override":
                overrides[str(item.get("PartName", "")).lower()] = str(item.get("ContentType", ""))
        return defaults, overrides
    old_defaults, old_overrides = mappings(before)
    new_defaults, new_overrides = mappings(after)
    allowed_default = {"p7x", "cat"}
    allowed_override = {"/" + CODE_INTEGRITY_MEMBER.lower(), "/" + SIGNATURE_MEMBER.lower()}
    changed_defaults = sorted(key for key in (set(old_defaults) | set(new_defaults)) - allowed_default
                              if old_defaults.get(key) != new_defaults.get(key))
    if changed_defaults:
        return False, f"unexpected content-type defaults changed: {changed_defaults[:8]}"
    changed_overrides = sorted(key for key in (set(old_overrides) | set(new_overrides)) - allowed_override
                               if old_overrides.get(key) != new_overrides.get(key))
    if changed_overrides:
        return False, f"unexpected content-type overrides changed: {changed_overrides[:8]}"
    signature_type = new_defaults.get("p7x", "").lower()
    catalog_default_type = new_defaults.get("cat", "").lower()
    catalog_type = new_overrides.get("/" + CODE_INTEGRITY_MEMBER.lower(), "").lower()
    signature_override_type = new_overrides.get("/" + SIGNATURE_MEMBER.lower(), "").lower()
    if "p7x" in new_defaults and "signature" not in signature_type:
        return False, "p7x extension does not map to a signature content type"
    if ("cat" in new_defaults and not
            any(word in catalog_default_type for word in ("pkiseccat", "codeintegrity", "catalog"))):
        return False, "cat extension does not map to a code-integrity catalog content type"
    if ("/" + CODE_INTEGRITY_MEMBER.lower() in new_overrides and not
            any(word in catalog_type for word in ("codeintegrity", "code-integrity", "catalog", "pkiseccat"))):
        return False, "CodeIntegrity.cat override has an unrelated content type"
    if ("/" + SIGNATURE_MEMBER.lower() in new_overrides and
            "signature" not in signature_override_type):
        return False, "AppxSignature.p7x override has an unrelated content type"
    return True, "signature content-types delta verified"


def verify_test_signed_derivative(*, source: Path, derived: Path,
                                  expected_source_sha256: str,
                                  expected_identity: dict[str, str]) -> dict[str, Any]:
    """Require original bytes to remain frozen and all package members to match except signature."""
    if source.is_symlink() or derived.is_symlink():
        raise DerivativeVerificationError("source and derived package must be regular non-symlink files")
    source = source.resolve(strict=True)
    derived = derived.resolve(strict=True)
    if source == derived:
        raise DerivativeVerificationError("source and derived package must be distinct regular files")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_hash.lower() != expected_source_sha256.lower():
        raise DerivativeVerificationError("frozen source package SHA-256 mismatch")
    original_members, original_manifest, _ = _members(source)
    signed_members, signed_manifest, signature_size = _members(derived)
    if SIGNATURE_MEMBER in original_members:
        raise DerivativeVerificationError("frozen source already contains a package signature")
    if SIGNATURE_MEMBER not in signed_members or signature_size <= 0:
        raise DerivativeVerificationError("derived package has no non-empty AppxSignature.p7x")
    if _identity(original_manifest) != expected_identity or _identity(signed_manifest) != expected_identity:
        raise DerivativeVerificationError("source or derived manifest identity differs from the frozen profile")
    removed = sorted(set(original_members) - set(signed_members))
    added = sorted(set(signed_members) - set(original_members))
    unexpected_added = sorted(set(added) - ALLOWED_ADDED_SIGNATURE_MEMBERS)
    if removed or unexpected_added:
        raise DerivativeVerificationError(
            "derived package has missing or unexpected members; "
            f"removed={removed[:8]}, added={added[:8]}")
    if added and SIGNATURE_MEMBER not in added and SIGNATURE_MEMBER not in original_members:
        raise DerivativeVerificationError("derived package signature member is not a new signature-only member")
    if CONTENT_TYPES_MEMBER in original_members:
        try:
            with zipfile.ZipFile(source) as source_zip, zipfile.ZipFile(derived) as derived_zip:
                allowed, content_type_reason = _content_types_signature_only(
                    source_zip.read(CONTENT_TYPES_MEMBER), derived_zip.read(CONTENT_TYPES_MEMBER))
                if not allowed:
                    raise DerivativeVerificationError(
                        "[Content_Types].xml changed beyond signature metadata: " + content_type_reason)
        except (KeyError, OSError, zipfile.BadZipFile) as exc:
            raise DerivativeVerificationError("package content-type metadata is unreadable") from exc
    elif CONTENT_TYPES_MEMBER in added:
        raise DerivativeVerificationError("signing added an unexpected content-type manifest")
    allowed_changed = {CONTENT_TYPES_MEMBER, CODE_INTEGRITY_MEMBER}
    changed = sorted(name for name, digest in original_members.items()
                     if digest != signed_members[name] and name not in allowed_changed)
    if changed:
        raise DerivativeVerificationError("non-signature package members changed: " + ", ".join(changed[:8]))
    return {
        "schema_version": "all-auto-msix-test-signature-derivative/1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "SIGNATURE_ONLY_DERIVATIVE_VERIFIED",
        "diagnostic_only": True,
        "source": {"path": str(source), "sha256": source_hash,
                   "identity": expected_identity},
        "derived": {"path": str(derived),
                    "sha256": hashlib.sha256(derived.read_bytes()).hexdigest(),
                    "identity": _identity(signed_manifest),
                    "signature_member_sha256": signed_members[SIGNATURE_MEMBER]},
        "changed_payload_members": [],
        "added_members": added,
        "changed_signature_metadata_members": sorted(
            name for name, digest in original_members.items()
            if digest != signed_members[name] and name in allowed_changed),
        "limitations": ["The derived SHA is different and is never a Store submission candidate.",
                        "This verifies package member identity, not application runtime behavior."]
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--derived", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--identity-name", required=True)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = verify_test_signed_derivative(
            source=args.source, derived=args.derived,
            expected_source_sha256=args.expected_source_sha256,
            expected_identity={"Name": args.identity_name, "Publisher": args.publisher,
                               "Version": args.version, "ProcessorArchitecture": args.architecture})
    except (DerivativeVerificationError, OSError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
