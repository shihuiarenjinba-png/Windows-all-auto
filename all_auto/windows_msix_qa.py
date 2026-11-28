"""Read-only MSIX runtime preflight; never installs or launches the package."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import platform
import struct
import zipfile
import xml.etree.ElementTree as ET
from typing import Any

from uploader.core import read_msix_manifest_metadata, verify_file


def _pe_summary(path: Path) -> dict[str, Any]:
    try:
        import pefile  # type: ignore[import-not-found]
    except ImportError:
        return {"status": "PE_IMPORT_PARSER_UNAVAILABLE", "machine": None, "imports": []}
    try:
        pe = pefile.PE(str(path), fast_load=False)
        machine = int(pe.FILE_HEADER.Machine)
        names = sorted({entry.dll.decode("ascii", errors="replace")
                        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])})
        return {"status": "PE_READ", "machine": f"0x{machine:04x}", "imports": names}
    except (OSError, ValueError, pefile.PEFormatError) as exc:
        return {"status": "PE_READ_FAILED", "machine": None,
                "error_type": type(exc).__name__, "imports": []}


def diagnose_msix_runtime(*, config: dict[str, Any], package: Path,
                          executable: Path | None = None,
                          prior_install_result: str | None = None,
                          prior_launch_result: str | None = None) -> dict[str, Any]:
    """Collect exact-byte and static runtime facts without touching Windows policy."""
    package = package.expanduser().resolve(strict=True)
    if package.is_symlink() or not package.is_file():
        raise ValueError("package must be a regular non-symlink file")
    verified = verify_file(config, package, expected_sha256=config.get("expected_sha256"),
                           max_bytes=int(config.get("max_bytes", 4_000_000_000)))
    manifest_info = read_msix_manifest_metadata(package)
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
        root = ET.fromstring(archive.read("AppxManifest.xml"))
    identity = next((node for node in root.iter() if node.tag.endswith("}Identity")), None)
    application = next((node for node in root.iter() if node.tag.endswith("}Application")), None)
    identity_facts = ({"name": identity.get("Name"), "publisher": identity.get("Publisher"),
                       "version": identity.get("Version"), "architecture": identity.get("ProcessorArchitecture")}
                      if identity is not None else None)
    executable_facts = None
    resolved_executable = None
    if executable is not None:
        resolved_executable = executable.expanduser().resolve(strict=True)
        if resolved_executable.is_symlink() or not resolved_executable.is_file():
            raise ValueError("executable must be a regular non-symlink file")
        executable_facts = {
            "path": str(resolved_executable), "size_bytes": resolved_executable.stat().st_size,
            "sha256": _hash(resolved_executable), "pe": _pe_summary(resolved_executable),
        }
    expected_ok = (verified.sha256.lower() == str(config.get("expected_sha256", "")).lower()
                   and identity_facts is not None
                   and identity_facts.get("name") == config.get("identity_name")
                   and identity_facts.get("publisher") == config.get("publisher")
                   and identity_facts.get("version") == config.get("version")
                   and str(identity_facts.get("architecture", "")).lower() ==
                       str(config.get("architecture", "x64")).lower())
    report = {
        "schema_version": "all-auto-windows-msix-runtime-diagnostic/1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "diagnostic_only": True, "install_attempted": False, "launch_attempted": False,
        "host": {"platform": platform.platform(), "system": platform.system(),
                 "machine": platform.machine(), "python_bits": struct.calcsize("P") * 8},
        "package": {"path": str(package), "file_name": verified.file_name,
                    "size_bytes": verified.size, "sha256": verified.sha256,
                    "identity": identity_facts, "target_device_families": manifest_info["target_device_families"],
                    "signature_state": manifest_info["signature_state"],
                    "appx_signature_file_present": "AppxSignature.p7x" in names,
                    "application_entry_point": application.get("EntryPoint") if application is not None else None,
                    "has_run_full_trust_capability": any(
                        node.get("Name") == "runFullTrust" for node in root.iter()
                        if node.tag.endswith("}Capability")),
                    "exact_identity_sha_match": expected_ok},
        "executable": executable_facts,
        "prior_operator_results": {"install": prior_install_result,
                                    "launch": prior_launch_result},
        "assessment": "RUNTIME_QA_UNRESOLVED" if prior_install_result or prior_launch_result
                     else "STATIC_PACKAGE_PREFLIGHT_ONLY",
        "limitations": ["This report does not install or execute the MSIX.",
                        "Windows policy, AppX registration, event logs, ACLs and VM readiness require the companion PowerShell diagnostic.",
                        "A passing static preflight is not a Windows runtime QA pass."],
    }
    return report


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
