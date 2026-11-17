"""Safe GitHub Actions artifact intake for local Windows QA.

This downloads an exact Actions artifact already produced by GitHub, verifies
the immutable workflow provenance and archive digest, safely extracts it, then
verifies and extracts the manifest-selected executable from an exact MSIX.

It never installs the MSIX, changes certificate trust, changes Windows
security, edits source, or performs Store operations.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from typing import Any
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024
MAX_EXTRACTED_BYTES = 800 * 1024 * 1024
MAX_FILES = 5000


class ArtifactIntakeHold(ValueError):
    pass


def _fail(reason: str) -> None:
    raise ArtifactIntakeHold("GITHUB_ARTIFACT_INTAKE_HOLD: " + reason)


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member_name(raw: str) -> PurePosixPath:
    name = raw.replace("\\", "/")
    path = PurePosixPath(name)
    if (not name or name.startswith("/") or path.is_absolute() or
            any(part in {"", ".", ".."} for part in path.parts) or
            any(":" in part or part.endswith((" ", ".")) or
                any(ord(character) < 32 or ord(character) == 127
                    for character in part)
                for part in path.parts)):
        _fail("unsafe archive member path")
    return path


def safe_extract_zip(archive_path: Path, destination: Path) -> list[Path]:
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        _fail("destination may not be a symlink")
    extracted: list[Path] = []
    total = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if not 1 <= len(infos) <= MAX_FILES:
                _fail("unsafe archive file count")
            seen: set[str] = set()
            for info in infos:
                rel = _safe_member_name(info.filename)
                folded = str(rel).casefold()
                if folded in seen:
                    _fail("duplicate archive member")
                seen.add(folded)
                if info.file_size < 0 or info.file_size > MAX_ARCHIVE_BYTES:
                    _fail("unsafe archive member size")
                total += info.file_size
                if total > MAX_EXTRACTED_BYTES:
                    _fail("archive expands beyond local QA limit")
                # Reject Unix symlinks encoded in external attributes.
                mode = (info.external_attr >> 16) & 0xFFFF
                if mode and (mode & 0o170000) == 0o120000:
                    _fail("archive symlink is not allowed")
                target = (destination / Path(*rel.parts)).resolve()
                try:
                    target.relative_to(destination)
                except ValueError:
                    _fail("archive path escapes destination")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                extracted.append(target)
    except ArtifactIntakeHold:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ArtifactIntakeHold(
            "GITHUB_ARTIFACT_INTAKE_HOLD: invalid artifact ZIP: " +
            type(exc).__name__
        ) from exc
    return extracted


def inspect_and_extract_msix(package_path: Path, executable_output: Path) -> dict[str, Any]:
    package = package_path.resolve()
    if package_path.is_symlink() or not package.is_file():
        _fail("MSIX is missing or linked")
    try:
        with zipfile.ZipFile(package) as archive:
            infos = archive.infolist()
            names: dict[str, zipfile.ZipInfo] = {}
            for info in infos:
                rel = _safe_member_name(info.filename)
                folded = str(rel).casefold()
                if folded in names:
                    _fail("duplicate MSIX member")
                names[folded] = info
            manifest = names.get("appxmanifest.xml")
            if manifest is None or not 0 < manifest.file_size <= 2 * 1024 * 1024:
                _fail("MSIX manifest missing or oversized")
            root = ET.fromstring(archive.read(manifest))
            identities = [
                item for item in root.iter()
                if item.tag.rsplit("}", 1)[-1] == "Identity"
            ]
            applications = [
                item for item in root.iter()
                if item.tag.rsplit("}", 1)[-1] == "Application"
            ]
            if len(identities) != 1 or len(applications) != 1:
                _fail("MSIX must have one Identity and one Application")
            identity = {
                "name": identities[0].attrib.get("Name"),
                "publisher": identities[0].attrib.get("Publisher"),
                "version": identities[0].attrib.get("Version"),
            }
            if any(not isinstance(value, str) or not value
                   for value in identity.values()):
                _fail("MSIX Identity is incomplete")
            executable_name = applications[0].attrib.get("Executable")
            if not isinstance(executable_name, str) or not executable_name:
                _fail("MSIX executable is missing from manifest")
            rel_exe = _safe_member_name(executable_name)
            exe_info = names.get(str(rel_exe).casefold())
            if exe_info is None or exe_info.is_dir() or exe_info.file_size <= 0:
                _fail("manifest-selected executable is missing")
            executable_output = executable_output.resolve()
            executable_output.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(exe_info) as source, executable_output.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    except ArtifactIntakeHold:
        raise
    except (OSError, KeyError, RuntimeError, ET.ParseError,
            zipfile.BadZipFile) as exc:
        raise ArtifactIntakeHold(
            "GITHUB_ARTIFACT_INTAKE_HOLD: invalid MSIX: " +
            type(exc).__name__
        ) from exc
    return {
        "package_sha256": sha256_file(package),
        "executable_sha256": sha256_file(executable_output),
        "executable_name": str(rel_exe),
        "identity": identity,
    }


def validate_artifact_metadata(
    metadata: dict[str, Any], *, repository: str, artifact_id: int,
    expected_name: str, expected_run_id: int, expected_head_sha: str,
    expected_archive_sha256: str,
) -> str:
    if not REPOSITORY.fullmatch(repository):
        _fail("invalid repository")
    if metadata.get("id") != artifact_id:
        _fail("artifact ID mismatch")
    if metadata.get("name") != expected_name:
        _fail("artifact name mismatch")
    if metadata.get("expired") is not False:
        _fail("artifact is expired")
    digest = metadata.get("digest")
    if digest != "sha256:" + expected_archive_sha256:
        _fail("artifact archive digest mismatch")
    workflow = metadata.get("workflow_run")
    if not isinstance(workflow, dict):
        _fail("artifact workflow provenance missing")
    if workflow.get("id") != expected_run_id:
        _fail("workflow run mismatch")
    if workflow.get("head_sha") != expected_head_sha:
        _fail("workflow source SHA mismatch")
    url = metadata.get("archive_download_url")
    if not isinstance(url, str) or not url.startswith("https://api.github.com/"):
        _fail("artifact download URL invalid")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Strip GitHub Authorization before following a cross-host signed URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = urllib.parse.urlparse(req.full_url).hostname
        new_host = urllib.parse.urlparse(newurl).hostname
        if old_host != new_host:
            redirected.remove_header("Authorization")
        return redirected


def _github_token() -> str:
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArtifactIntakeHold(
            "GITHUB_ARTIFACT_INTAKE_HOLD: GitHub CLI unavailable"
        ) from exc
    token = result.stdout.strip()
    if result.returncode != 0 or not token:
        _fail("GitHub CLI authentication is unavailable")
    return token


def _get_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "Windows-all-auto-local-QA",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.loads(response.read(2 * 1024 * 1024))
    except (OSError, ValueError) as exc:
        raise ArtifactIntakeHold(
            "GITHUB_ARTIFACT_INTAKE_HOLD: artifact metadata fetch failed"
        ) from exc
    if not isinstance(value, dict):
        _fail("artifact metadata response invalid")
    return value


def _download(url: str, token: str, destination: Path) -> None:
    request = urllib.request.Request(
        url, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "Windows-all-auto-local-QA",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    opener = urllib.request.build_opener(_SafeRedirect())
    try:
        with opener.open(request, timeout=120) as response, destination.open("wb") as output:
            copied = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                copied += len(block)
                if copied > MAX_ARCHIVE_BYTES:
                    _fail("artifact download exceeds local QA limit")
                output.write(block)
    except ArtifactIntakeHold:
        raise
    except OSError as exc:
        raise ArtifactIntakeHold(
            "GITHUB_ARTIFACT_INTAKE_HOLD: artifact download failed"
        ) from exc


@dataclass(frozen=True)
class IntakeResult:
    root: Path
    archive_path: Path
    package_path: Path
    executable_path: Path
    manifest_path: Path
    metadata: dict[str, Any]


def fetch_actions_artifact(
    *, repository: str, artifact_id: int, expected_name: str,
    expected_run_id: int, expected_head_sha: str,
    expected_archive_sha256: str, expected_package_name: str,
    expected_package_sha256: str, expected_executable_sha256: str,
    destination: Path,
) -> IntakeResult:
    if not SHA40.fullmatch(expected_head_sha):
        _fail("invalid expected source SHA")
    for value, label in (
        (expected_archive_sha256, "archive"),
        (expected_package_sha256, "package"),
        (expected_executable_sha256, "executable"),
    ):
        if not SHA64.fullmatch(value):
            _fail("invalid expected " + label + " SHA-256")
    token = _github_token()
    metadata_url = (
        "https://api.github.com/repos/" + repository +
        "/actions/artifacts/" + str(artifact_id)
    )
    metadata = _get_json(metadata_url, token)
    download_url = validate_artifact_metadata(
        metadata, repository=repository, artifact_id=artifact_id,
        expected_name=expected_name, expected_run_id=expected_run_id,
        expected_head_sha=expected_head_sha,
        expected_archive_sha256=expected_archive_sha256,
    )

    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        _fail("destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / "github-artifact.zip"
    _download(download_url, token, archive_path)
    if sha256_file(archive_path) != expected_archive_sha256:
        _fail("downloaded artifact archive SHA mismatch")

    extracted_root = destination / "artifact"
    files = safe_extract_zip(archive_path, extracted_root)
    package_matches = [
        path for path in files
        if path.name.casefold() == expected_package_name.casefold()
    ]
    if len(package_matches) != 1:
        _fail("expected MSIX not found exactly once in Actions artifact")
    package_path = package_matches[0]
    if sha256_file(package_path) != expected_package_sha256:
        _fail("MSIX SHA mismatch")

    executable_path = destination / "intake" / "product.exe"
    package_info = inspect_and_extract_msix(package_path, executable_path)
    if package_info["executable_sha256"] != expected_executable_sha256:
        _fail("contained executable SHA mismatch")

    manifest = {
        "schema_version": "github-actions-artifact-intake-v1",
        "repository": repository,
        "artifact_id": artifact_id,
        "artifact_name": expected_name,
        "workflow_run_id": expected_run_id,
        "source_sha": expected_head_sha,
        "archive_sha256": expected_archive_sha256,
        "package_path": str(package_path),
        "package_sha256": package_info["package_sha256"],
        "executable_path": str(executable_path),
        "executable_sha256": package_info["executable_sha256"],
        "executable_name": package_info["executable_name"],
        "identity": package_info["identity"],
        "installed_package_tested": False,
        "store_purchase_required": False,
        "security_policy_changed": False,
    }
    manifest_path = destination / "intake-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return IntakeResult(
        root=destination, archive_path=archive_path,
        package_path=package_path, executable_path=executable_path,
        manifest_path=manifest_path, metadata=manifest,
    )
