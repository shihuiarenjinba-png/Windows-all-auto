"""Product-driven, fail-closed Store workflow planning.

This module deliberately stops at READ_ONLY/DRY_RUN. Existing package upload
mechanics remain in :mod:`uploader`; this orchestrator does not widen their
approval scope or write to Partner Center.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
from uuid import uuid4

from uploader.core import UploadError, read_msix_manifest_metadata, validate_config, verify_file
from uploader.device_families import device_family_plan
from all_auto.product_artifact_pull import ProductArtifactPullError, select_github_artifact_metadata


MODES = {"AUTO", "READ_ONLY", "DRY_RUN", "DRAFT_WRITE", "CERTIFICATION", "PUBLISH"}
LIVE_MODES = {"DRAFT_WRITE", "CERTIFICATION", "PUBLISH"}
SECTION_KEYS = (
    "product_identity", "properties", "age_ratings", "pricing_availability",
    "packages", "store_listings", "submission_options",
)
DCA_BINDING = {
    "product_id": "9PDL4ZWSB45P",
    "submission_id": "1152921505702212222",
    "identity_name": "OkinawaDesktopTools.DataContractAuditor",
    "publisher": "CN=46263F21-A700-41DB-8C9B-114C22FB82FC",
    "version": "1.0.0.0",
    "architecture": "x64",
    "path": "store-output/DataContractSchemaDrift_1.0.0.0_x64.msix",
    "expected_sha256": "e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05",
    "repository": "shihuiarenjinba-png/csv-import-validator",
    "ref": "722ec7a077d2c6109e657c4ee661c9f3d06a4506",
    "source_sha": "722ec7a077d2c6109e657c4ee661c9f3d06a4506",
    "artifact_run_id": 45580565845,
    "artifact_id": 15005358857,
    "artifact_name": "data-contract-QA_UNSIGNED-msix-45580565845",
}


class StoreWorkflowError(ValueError):
    """A product binding or workflow request failed closed validation."""


def _gh_json(args: list[str], *, command_runner: Any = None) -> dict[str, Any]:
    runner = command_runner or subprocess.run
    try:
        result = runner(["gh", *args], capture_output=True, text=True,
                        encoding="utf-8", timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise StoreWorkflowError(f"GitHub CLI unavailable ({type(exc).__name__})") from exc
    if result.returncode != 0:
        raise StoreWorkflowError("GitHub Actions artifact request failed; check gh authentication and repository access")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise StoreWorkflowError("GitHub CLI returned invalid artifact metadata") from exc
    if not isinstance(value, dict):
        raise StoreWorkflowError("GitHub CLI metadata response is not an object")
    return value


def _download_registered_actions_artifact(config: dict[str, Any], *, product: str,
                                          product_root: Path, command_runner: Any = None) -> dict[str, Any] | None:
    artifact_id = config.get("artifact_id")
    artifact_name = config.get("artifact_name")
    run_id = config.get("artifact_run_id")
    if not artifact_id or not artifact_name or not run_id:
        return None
    repository = str(config["repository"])
    artifact = _gh_json(["api", f"repos/{repository}/actions/artifacts/{artifact_id}"],
                        command_runner=command_runner)
    if artifact.get("id") != artifact_id or artifact.get("name") != artifact_name:
        raise StoreWorkflowError("GitHub Artifact ID/name does not match the registered product profile")
    workflow_run = artifact.get("workflow_run") or {}
    if workflow_run.get("id") != run_id or artifact.get("expired") is not False:
        raise StoreWorkflowError("GitHub Artifact is expired or bound to a different workflow run")
    try:
        metadata = select_github_artifact_metadata([artifact], artifact_name=str(artifact_name))
    except ProductArtifactPullError as exc:
        raise StoreWorkflowError(f"GitHub Artifact metadata is invalid: {exc}") from exc
    run = _gh_json(["api", f"repos/{repository}/actions/runs/{run_id}"],
                   command_runner=command_runner)
    if run.get("conclusion") != "success" or str(run.get("head_sha", "")).lower() != str(config.get("source_sha", "")).lower():
        raise StoreWorkflowError("GitHub workflow is not successful at the pinned source SHA")

    expected_name = Path(str(config["path"])).name
    expected_sha = str(config.get("expected_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha):
        raise StoreWorkflowError("Artifact acquisition requires a frozen MSIX SHA-256")
    try:
        with tempfile.TemporaryDirectory(prefix="all-auto-store-artifact-") as temporary:
            target = Path(temporary)
            runner = command_runner or subprocess.run
            try:
                result = runner(["gh", "run", "download", str(run_id), "-R", repository,
                                 "--name", str(artifact_name), "--dir", str(target)],
                                capture_output=True, text=True, encoding="utf-8",
                                timeout=180, check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                raise StoreWorkflowError(f"GitHub Artifact download failed ({type(exc).__name__})") from exc
            if result.returncode != 0:
                raise StoreWorkflowError("GitHub Artifact download failed; check gh authentication and repository access")
            files = [path for path in target.rglob("*") if path.is_file() and not path.is_symlink()]
            packages = [path for path in files if path.name.casefold() == expected_name.casefold()]
            allowed_evidence = {"build_evidence.json", "msix_verification.json", "store_preflight.json"}
            unexpected = [path.name for path in files
                          if path.name.casefold() != expected_name.casefold()
                          and path.name.casefold() not in allowed_evidence]
            if len(packages) != 1 or unexpected:
                raise StoreWorkflowError("Artifact must contain exactly the configured MSIX and only recognized build evidence")
            evidence = {path.name.casefold(): path for path in files
                        if path.name.casefold() in allowed_evidence}
            if evidence:
                _verify_actions_artifact_evidence(evidence, config, expected_sha)
            verified = verify_file(config, packages[0], expected_sha256=expected_sha,
                                   max_bytes=int(config.get("max_bytes", 4_000_000_000)))
            digest_dir = product_root / expected_sha[:12]
            destination = digest_dir / expected_name
            if destination.exists() or destination.is_symlink():
                raise StoreWorkflowError("Artifact cache destination already exists; reconcile before replacement")
            staging = digest_dir / f".{Path(expected_name).stem}.{uuid4().hex}.msix"
            try:
                digest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(packages[0], staging)
                copied = verify_file(config, staging, expected_sha256=expected_sha,
                                     max_bytes=int(config.get("max_bytes", 4_000_000_000)))
                if copied.sha256 != verified.sha256:
                    raise StoreWorkflowError("Artifact bytes changed while copying into the exact cache")
                staging.rename(destination)
            except Exception:
                staging.unlink(missing_ok=True)
                raise
    except StoreWorkflowError:
        raise
    except Exception as exc:
        raise StoreWorkflowError(f"Artifact extraction or MSIX verification failed ({type(exc).__name__})") from exc
    return {"status": "ACTIONS_ARTIFACT_FETCHED_AND_VERIFIED",
            "source": "github_actions_artifact_id_and_run_id",
            "repository": repository, "source_sha": run["head_sha"],
            "workflow_name": run.get("name"), "workflow_conclusion": run.get("conclusion"),
            "artifact_id": metadata["github_artifact_id"], "artifact_name": artifact_name,
            "artifact_digest": metadata["github_artifact_digest"],
            "artifact_size_bytes": metadata["github_artifact_size_in_bytes"],
            "run_id": run_id, "file_name": verified.file_name,
            "sha256": verified.sha256, "local_path": str(destination)}


def _verify_actions_artifact_evidence(evidence: dict[str, Path], config: dict[str, Any],
                                      expected_sha: str) -> None:
    """Bind recognized CI evidence JSON to the exact registered artifact tuple."""
    expected = {
        "store_id": config.get("product_id"),
        "version": config.get("version"),
        "source_sha": str(config.get("source_sha", config.get("ref", ""))).lower(),
        "sha256": expected_sha,
    }
    for filename, path in evidence.items():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreWorkflowError(f"Artifact evidence is unreadable: {filename}") from exc
        if not isinstance(payload, dict):
            raise StoreWorkflowError(f"Artifact evidence must be a JSON object: {filename}")
        if filename == "build_evidence.json":
            actual = {"store_id": payload.get("store_id"), "version": payload.get("msix_version"),
                      "source_sha": str(payload.get("source_sha", "")).lower(),
                      "sha256": str(payload.get("msix_sha256", "")).lower()}
            if payload.get("msix_filename") != Path(str(config["path"])).name:
                raise StoreWorkflowError("BUILD_EVIDENCE filename does not match the configured MSIX")
        elif filename == "msix_verification.json":
            package = payload.get("msix") if isinstance(payload.get("msix"), dict) else {}
            actual = {"store_id": payload.get("store_id"), "version": payload.get("version"),
                      "source_sha": expected["source_sha"],
                      "sha256": str(package.get("sha256", "")).lower()}
            if payload.get("valid") is not True or package.get("filename") != Path(str(config["path"])).name:
                raise StoreWorkflowError("MSIX_VERIFICATION does not validate the configured package")
        else:
            actual = {"store_id": payload.get("store_id"), "version": payload.get("version_to_build"),
                      "source_sha": expected["source_sha"], "sha256": expected_sha}
            if payload.get("ready") is not True:
                raise StoreWorkflowError("STORE_PREFLIGHT is not ready for the configured build")
        if actual != expected:
            raise StoreWorkflowError(f"Artifact evidence does not match the registered product/source/SHA: {filename}")


def acquire_registered_package(config: dict[str, Any], *, product: str,
                               cache_root: Path, token: str | None = None,
                               downloader: Any = None,
                               command_runner: Any = None,
                               search_roots: tuple[Path, ...] | list[Path] = (),
                               archive_root: Path | None = None) -> dict[str, Any]:
    """Resolve or fetch one SHA-pinned package from its configured source path.

    This reuses the uploader's bounded GitHub Contents downloader. It never
    downloads a floating branch: config.ref must be the already registered
    commit/ref and the returned bytes must pass the configured SHA + Manifest.
    """
    expected = str(config.get("expected_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise StoreWorkflowError("automatic package acquisition requires a frozen SHA-256")
    filename = Path(str(config["path"])).name
    resolved_cache_root = cache_root.expanduser().resolve()
    if cache_root.expanduser().is_symlink():
        raise StoreWorkflowError("package cache root must not be a symbolic link")
    unresolved_product_root = resolved_cache_root / product
    if unresolved_product_root.is_symlink():
        raise StoreWorkflowError("product package cache must not be a symbolic link")
    product_root = unresolved_product_root.resolve()
    if resolved_cache_root not in product_root.parents:
        raise StoreWorkflowError("package cache escaped its configured root")
    matches = []
    if product_root.exists():
        for candidate in product_root.rglob(filename):
            # Durable archive copies are immutable retention targets, not
            # working-cache candidates. Keep them out of operational source
            # resolution so the same exact MSIX is not reported as ambiguous.
            if "durable-package-archive" in candidate.parts:
                continue
            if candidate.is_symlink():
                raise StoreWorkflowError("symbolic links are not allowed in the package cache")
            if candidate.is_file():
                resolved_candidate = candidate.resolve(strict=True)
                if product_root not in resolved_candidate.parents:
                    raise StoreWorkflowError("package cache candidate escaped its product directory")
                matches.append(resolved_candidate)
    matches.sort()
    external_matches: dict[str, Path] = {}
    for root in search_roots:
        expanded = root.expanduser()
        if expanded.is_symlink():
            raise StoreWorkflowError("external package search roots must not be symbolic links")
        if not expanded.is_dir():
            continue
        resolved_root = expanded.resolve()
        for candidate in resolved_root.rglob(filename):
            if "durable-package-archive" in candidate.parts:
                continue
            if candidate.is_symlink():
                raise StoreWorkflowError("symbolic links are not allowed in package search roots")
            if candidate.is_file():
                resolved_candidate = candidate.resolve(strict=True)
                if resolved_root not in resolved_candidate.parents:
                    raise StoreWorkflowError("package search candidate escaped its registered root")
                external_matches[str(resolved_candidate).casefold()] = resolved_candidate
    for candidate in external_matches.values():
        if candidate not in matches:
            matches.append(candidate)
    matches.sort()
    identical_candidate_count = 1
    if len(matches) > 1:
        try:
            checked = [verify_file(config, candidate, expected_sha256=expected,
                                   max_bytes=int(config.get("max_bytes", 4_000_000_000)))
                       for candidate in matches]
        except (OSError, UploadError):
            raise StoreWorkflowError(f"multiple exact package cache candidates exist for {filename}; resolve before continuing") from None
        if len({item.sha256 for item in checked}) != 1:
            raise StoreWorkflowError(f"multiple package candidates differ for {filename}; resolve before continuing")
        identical_candidate_count = len(matches)
        matches = [matches[0]]
    if matches:
        verified = verify_file(config, matches[0], expected_sha256=expected,
                               max_bytes=int(config.get("max_bytes", 4_000_000_000)))
        is_cache = product_root in matches[0].parents
        return {"status": ("MULTIPLE_IDENTICAL_COPIES_VERIFIED" if identical_candidate_count > 1
                            else "CACHE_HIT_VERIFIED" if is_cache else "LOCAL_EXACT_FILE_VERIFIED"),
                "source": "local_sha_bound_cache" if is_cache else "registered_local_artifact_root",
                "path": str(matches[0].resolve()), "file_name": verified.file_name,
                "sha256": verified.sha256, "identical_candidate_count": identical_candidate_count}
    if archive_root is not None:
        archived = _restore_registered_archive(config, archive_root=archive_root,
                                               destination_root=product_root)
        if archived is not None:
            return archived
    artifact_result = _download_registered_actions_artifact(
        config, product=product, product_root=product_root, command_runner=command_runner)
    if artifact_result is not None:
        return artifact_result
    if downloader is None:
        from uploader.run import github_download
        downloader = github_download
    digest_dir = product_root / expected[:12]
    destination = digest_dir / filename
    if destination.exists() or destination.is_symlink():
        raise StoreWorkflowError("exact package cache destination already exists ambiguously")
    staging = digest_dir / f".{Path(filename).stem}.{uuid4().hex}.msix"
    try:
        digest_dir.mkdir(parents=True, exist_ok=True)
        downloader(str(config["repository"]), str(config["ref"]), str(config["path"]),
                   token or os.environ.get("GH_READ_TOKEN"), staging,
                   max_bytes=int(config.get("max_bytes", 4_000_000_000)))
        verified = verify_file(config, staging, expected_sha256=expected,
                               max_bytes=int(config.get("max_bytes", 4_000_000_000)))
        if destination.exists() or destination.is_symlink():
            raise StoreWorkflowError("package cache destination appeared during acquisition")
        staging.rename(destination)
        return {"status": "PINNED_SOURCE_FETCHED_AND_VERIFIED",
                "source": "github_contents_registered_repo_ref_path",
                "repository": config["repository"], "ref": config["ref"],
                "path": config["path"], "file_name": verified.file_name,
                "sha256": verified.sha256, "local_path": str(destination)}
    except Exception as exc:
        staging.unlink(missing_ok=True)
        if isinstance(exc, StoreWorkflowError):
            raise
        code = getattr(exc, "code", None)
        detail = f"{code}: " if isinstance(code, str) else ""
        raise StoreWorkflowError(f"registered package source could not be acquired/verified ({detail}{type(exc).__name__})") from exc


def _restore_registered_archive(config: dict[str, Any], *, archive_root: Path,
                                destination_root: Path) -> dict[str, Any] | None:
    """Rehydrate a verified immutable local archive without modifying it."""
    expected = str(config.get("expected_sha256") or "").lower()
    filename = Path(str(config["path"])).name
    root = archive_root.expanduser()
    if root.is_symlink():
        raise StoreWorkflowError("durable package archive root must not be a symbolic link")
    if not root.is_dir():
        return None
    expected_dir = root / str(config["product_id"]) / str(config["version"]) / expected
    package = expected_dir / filename
    receipt_path = package.with_suffix(package.suffix + ".receipt.json")
    if not package.exists() and not receipt_path.exists():
        return None
    if package.is_symlink() or receipt_path.is_symlink() or not package.is_file() or not receipt_path.is_file():
        raise StoreWorkflowError("durable archive package/receipt pair is incomplete or unsafe")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreWorkflowError("durable archive receipt is unreadable") from exc
    expected_receipt = {
        "product_id": config["product_id"], "submission_id": config["submission_id"],
        "package_file_name": filename, "sha256": expected,
        "identity": config.get("identity_name"), "publisher": config.get("publisher"),
        "version": config.get("version"),
        "architecture": str(config.get("architecture", "x64")).lower(),
    }
    actual_receipt = {key: (str(receipt.get(key)).lower() if key == "architecture" else receipt.get(key))
                      for key in expected_receipt}
    if receipt.get("schema_version") != "all-auto-local-package-archive/1" or actual_receipt != expected_receipt:
        raise StoreWorkflowError("durable archive receipt does not match the registered Product/Draft/package tuple")
    try:
        verified = verify_file(config, package, expected_sha256=expected,
                               max_bytes=int(config.get("max_bytes", 4_000_000_000)))
    except (OSError, UploadError) as exc:
        raise StoreWorkflowError("durable archive bytes failed package verification") from exc
    digest_dir = destination_root / expected[:12]
    destination = digest_dir / filename
    if destination.exists() or destination.is_symlink():
        raise StoreWorkflowError("archive rehydration destination already exists; reconcile before replacement")
    staging = digest_dir / f".{Path(filename).stem}.{uuid4().hex}.msix"
    try:
        digest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package, staging)
        copied = verify_file(config, staging, expected_sha256=expected,
                             max_bytes=int(config.get("max_bytes", 4_000_000_000)))
        if copied.sha256 != verified.sha256:
            raise StoreWorkflowError("package SHA changed during archive rehydration")
        staging.rename(destination)
    except Exception:
        staging.unlink(missing_ok=True)
        raise
    return {"status": "LOCAL_ARCHIVE_REHYDRATED_AND_VERIFIED",
            "source": "durable_local_package_archive", "path": str(destination),
            "archive_path": str(package), "receipt": str(receipt_path),
            "file_name": verified.file_name, "sha256": verified.sha256}


def _sha256_path(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_job(product: str, config_root: Path) -> tuple[dict[str, Any], Path]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", product):
        raise StoreWorkflowError("product must be a registered lowercase slug")
    root = config_root.resolve()
    path = (root / f"{product}.job.json").resolve()
    if root not in path.parents or not path.is_file():
        raise StoreWorkflowError(f"no registered product profile: {product}")
    try:
        config = validate_config(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, UploadError) as exc:
        raise StoreWorkflowError(f"product profile is invalid: {exc}") from exc
    if product == "data-contract-auditor":
        mismatches = [key for key, fixed in DCA_BINDING.items() if config.get(key) != fixed]
        if mismatches:
            raise StoreWorkflowError("fixed DCA binding mismatch: " + ", ".join(mismatches))
    return config, path


def _source_observation(root: Path | None, config: dict[str, Any]) -> dict[str, Any]:
    if root is None:
        repo_leaf = str(config.get("repository", "")).rsplit("/", 1)[-1]
        home = Path.home()
        candidates = [Path.cwd(), home / "Desktop" / repo_leaf,
                      home / "Desktop" / "portfolio-audit" / repo_leaf,
                      home / "Desktop" / "portfolio-audit" / "_task_worktrees" / repo_leaf]
        for candidate in candidates:
            if candidate.is_dir() and (candidate / ".git").exists():
                try:
                    origin = subprocess.run(["git", "-C", str(candidate), "remote", "get-url", "origin"],
                                            check=True, capture_output=True, text=True, timeout=10).stdout.strip()
                except (OSError, subprocess.SubprocessError):
                    continue
                if origin in {f"https://github.com/{config['repository']}.git",
                              f"https://github.com/{config['repository']}",
                              f"git@github.com:{config['repository']}.git"}:
                    root = candidate
                    break
        if root is None:
            return {"status": "AUTO_DISCOVERY_NO_EXACT_CHECKOUT",
                    "repository_matches": False, "head_matches": False,
                    "readme": None, "evidence_files": [],
                    "checked_locations": [str(path) for path in candidates]}
    root = root.resolve()
    if not root.is_dir():
        return {"status": "SOURCE_ROOT_MISSING", "repository_matches": False,
                "head_matches": False, "readme": None, "evidence_files": []}
    def git(*args: str) -> str | None:
        try:
            return subprocess.run(["git", "-C", str(root), *args], check=True,
                                  capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    origin = git("remote", "get-url", "origin")
    head = git("rev-parse", "HEAD")
    expected_ref_commit = config["ref"] if re.fullmatch(r"[0-9a-fA-F]{40}", str(config["ref"])) else git("rev-parse", f"{config['ref']}^{{commit}}")
    repo = str(config["repository"])
    expected_origin = {f"https://github.com/{repo}.git", f"https://github.com/{repo}",
                      f"git@github.com:{repo}.git"}
    repository_matches = origin in expected_origin
    head_matches = bool(head and expected_ref_commit and head.lower() == expected_ref_commit.lower())
    candidates = ["README.md", "README.rst", "store/product.json", "store/approval.json",
                  "store/assets/approval.json", "store/listing.json", "store/listings.json"]
    found = [name for name in candidates if (root / name).is_file()]
    readme = next((name for name in ("README.md", "README.rst") if (root / name).is_file()), None)
    documents = []
    for name in found:
        path = root / name
        documents.append({"path": name, "bytes": path.stat().st_size,
                          "sha256": _sha256_path(path)})
    asset_files = []
    for relative in ("store/assets", "store-assets"):
        asset_root = root / relative
        if asset_root.is_dir():
            for path in sorted(asset_root.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    asset_files.append({"path": path.relative_to(root).as_posix(),
                                        "bytes": path.stat().st_size,
                                        "sha256": _sha256_path(path)})
    status = "SOURCE_EXACT_MATCH" if repository_matches and head_matches else "SOURCE_MISMATCH"
    return {"status": status, "repository_matches": repository_matches,
            "origin_redacted": origin is not None, "head": head,
            "expected_repository": repo, "expected_ref": config["ref"],
            "resolved_expected_ref": expected_ref_commit,
            "head_matches": head_matches, "readme": readme, "evidence_files": found,
            "document_fingerprints": documents, "image_asset_fingerprints": asset_files}


def _package_observation(config: dict[str, Any], package: Path | None) -> dict[str, Any]:
    if package is None:
        return {"status": "PACKAGE_PATH_NOT_PROVIDED", "file_name": Path(config["path"]).name,
                "sha256": None, "identity_verified": False, "path": None}
    try:
        resolved = package.expanduser().resolve(strict=True)
        if resolved.name.casefold() != Path(config["path"]).name.casefold():
            raise StoreWorkflowError("package filename differs from registered product profile")
        job = verify_file(config, resolved, expected_sha256=config.get("expected_sha256"),
                          max_bytes=int(config.get("max_bytes", 4_000_000_000)))
        manifest = read_msix_manifest_metadata(resolved)
        family_plan = device_family_plan(config, manifest["target_device_families"])
        return {"status": "EXACT_PACKAGE_VERIFIED", "file_name": job.file_name,
                "sha256": job.sha256, "identity_verified": True,
                "signature_state": manifest["signature_state"],
                "manifest_target_device_families": manifest["target_device_families"],
                "device_family_plan": family_plan,
                "version": job.version, "architecture": job.architecture,
                "identity_name": job.identity_name, "publisher": job.publisher,
                "bytes": job.size, "path": str(resolved)}
    except (OSError, UploadError, StoreWorkflowError) as exc:
        return {"status": "PACKAGE_HOLD", "file_name": Path(config["path"]).name,
                "sha256": None, "identity_verified": False,
                "error": str(exc), "path": None}


def build_store_workflow_report(*, product: str, config_root: Path,
                                mode: str = "DRY_RUN", source_root: Path | None = None,
                                package: Path | None = None) -> dict[str, Any]:
    mode = mode.upper()
    if mode not in MODES:
        raise StoreWorkflowError(f"unsupported mode: {mode}")
    if mode in LIVE_MODES:
        raise StoreWorkflowError(
            f"{mode} is outside this orchestrator; use a separately authorized, existing workflow"
        )
    config, config_path = _load_job(product, config_root)
    from uploader.store_policy import build_product_decision_batch, load_shared_store_policy
    shared_store_policy = load_shared_store_policy()
    product_decision_batch = build_product_decision_batch(shared_store_policy, config)
    source = _source_observation(source_root, config)
    package_state = _package_observation(config, package)
    profile_package = config.get("source_package_provenance")
    if not isinstance(profile_package, dict):
        profile_package = {"status": "NOT_RECORDED", "formal_package_sha256": None}
    profile_sha = profile_package.get("formal_package_sha256")
    if isinstance(profile_sha, str) and profile_sha.lower() != str(config.get("expected_sha256", "")).lower():
        profile_package = {**profile_package, "status": "MISMATCH",
                           "job_expected_sha256": config.get("expected_sha256")}
    family_plan = package_state.get("device_family_plan", {})
    if not family_plan:
        saved_targets = (config.get("device_family_settings") or {}).get("manifest_target_device_families", [])
        family_plan = device_family_plan(config, saved_targets if isinstance(saved_targets, list) else [])
        family_plan["evidence_status"] = "PROFILE_CANDIDATE_NOT_RECHECKED_THIS_RUN"
    execution_policy = config.get("execution_policy") if isinstance(config.get("execution_policy"), dict) else {}
    identity = {key: config.get(key) for key in
                ("product_id", "submission_id", "identity_name", "publisher", "version", "architecture")}

    gaps: list[dict[str, str]] = []
    if source["status"] != "SOURCE_EXACT_MATCH":
        gaps.append({"key": "source_revision", "status": "HOLD",
                     "why": "A local source checkout at the exact registered repository/ref was not verified."})
    if package_state["status"] != "EXACT_PACKAGE_VERIFIED":
        gaps.append({"key": "package", "status": "HOLD",
                     "why": "The exact configured MSIX bytes and Manifest have not been verified in this run."})
    if profile_package.get("status") == "MISMATCH":
        gaps.append({"key": "source_package_provenance", "status": "RECONCILE_REQUIRED",
                     "why": "Pinned source store/product.json formalPackage.msixSha256 differs from the immutable Job Config SHA."})
    gaps.extend([
        {"key": "partner_center_draft", "status": "UNVERIFIED",
         "why": "Live CDP/Partner Center read-only identity and Draft reconciliation was not performed."},
        {"key": "pricing_and_markets", "status": "AWAITING_OWNER_INPUT",
         "why": "No approved exact price or market profile is present in this package-only job config."},
        {"key": "store_listing", "status": "AWAITING_EVIDENCE",
         "why": "Localized listing text and screenshot approval are not sourced by this job config."},
        {"key": "compliance_and_commercial", "status": "HOLD",
         "why": "Commercial-license evidence is explicitly uncertified; legal declarations require source evidence/owner decision."},
        {"key": "packaged_runtime_qa", "status": "HOLD",
         "why": str(config.get("local_runtime_qa_status", "No exact-package runtime QA receipt is recorded."))},
    ])
    if family_plan.get("status") != "OWNER_APPROVED":
        gaps.append({"key": "device_family_selection", "status": "AWAITING_OWNER_APPROVAL",
                     "why": "Manifest-derived Store device-family candidates are not an owner approval."})
    if execution_policy.get("status") != "OWNER_APPROVED" or execution_policy.get("auto_execute_approved_sections") is not True:
        gaps.append({"key": "automatic_run_policy", "status": "PLAN_ONLY",
                     "why": "No persisted owner approval authorizes store run to execute live Store writes automatically."})
    sections = {key: "UNVERIFIED" for key in SECTION_KEYS}
    sections["product_identity"] = "CONFIGURED_NOT_LIVE_VERIFIED"
    sections["packages"] = "CANDIDATE_VERIFIED_LOCALLY" if package_state["status"] == "EXACT_PACKAGE_VERIFIED" else "HOLD"
    sections["pricing_availability"] = "AWAITING_OWNER_INPUT"
    sections["store_listings"] = "AWAITING_EVIDENCE"

    def approval_summary(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {"status": "NOT_RECORDED", "approval_ref": None}
        return {"status": value.get("status", "RECORDED"),
                "approval_ref": value.get("approval_ref")}

    family_settings = config.get("device_family_settings") if isinstance(config.get("device_family_settings"), dict) else {}
    price = config.get("pricing_approval")
    markets = config.get("markets_approval")
    owner_decisions = [
        {"key": "source_package_provenance", "status": profile_package.get("status", "NOT_RECORDED"),
         "job_expected_sha256": config.get("expected_sha256"),
         "source_profile_sha256": profile_package.get("formal_package_sha256"),
         "evidence_ref": profile_package.get("evidence_ref"),
         "note": profile_package.get("note")},
        {"key": "device_families", "status": family_settings.get("status", "NOT_RECORDED"),
         "manifest_candidates": family_plan.get("recommended_store_device_families", []),
         "approved_values": family_plan.get("approved_store_device_families", []),
         "approval": approval_summary(family_settings.get("approval"))},
        {"key": "pricing", "status": "APPROVED" if isinstance(price, dict) and price.get("status") == "OWNER_APPROVED" else "OWNER_DECISION_REQUIRED",
         "configured_value": config.get("price"), "approval": approval_summary(price)},
        {"key": "markets", "status": "APPROVED" if isinstance(markets, dict) and markets.get("status") == "OWNER_APPROVED" else "OWNER_DECISION_REQUIRED",
         "configured_value": config.get("markets"), "approval": approval_summary(markets)},
        {"key": "store_listings_and_assets", "status": "PROFILED" if isinstance(config.get("approved_store_sections"), dict) and config.get("approved_store_sections") else "EVIDENCE_OR_OWNER_APPROVAL_REQUIRED",
         "source_evidence_files": source.get("evidence_files", [])},
        {"key": "exact_package_runtime_qa", "status": config.get("local_runtime_qa_status", "NOT_RECORDED"),
         "qa_receipt": "PRESENT" if isinstance(config.get("runtime_qa_receipt"), dict) else "NOT_RECORDED"},
        {"key": "commercial_and_legal_declarations", "status": "OWNER_OR_EVIDENCE_REVIEW_REQUIRED",
         "source_evidence_files": source.get("evidence_files", [])},
    ]

    return {
        "schema_version": "all-auto-store-workflow/1",
        "run_id": uuid4().hex,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "product_key": product,
        "profile": {"path": str(config_path), "sha256": sha256(config_path.read_bytes()).hexdigest()},
        "binding": identity,
        "configured_approval": {
            "upload_approved_in_profile": config.get("upload_approved") is True,
            "approval_ref": config.get("approval_ref"),
            "scope": config.get("upload_scope"),
            "certification_authorized": config.get("certification_submission_authorized") is True,
            "publish_authorized": config.get("publish_authorized") is True,
        },
        "device_family_plan": family_plan or {
            "status": "UNVERIFIED", "recommended_store_device_families": [],
            "approved_store_device_families": []},
        "execution_policy": {"status": execution_policy.get("status", "PLAN_ONLY"),
                              "auto_execute_approved_sections": execution_policy.get("auto_execute_approved_sections") is True,
                              "approval_present": isinstance(execution_policy.get("approval"), dict)},
        "source": source,
        "package": package_state,
        "source_package_provenance": profile_package,
        "owner_decision_candidates": config.get("owner_decision_candidates", []),
        "shared_store_policy": {"policy_id": shared_store_policy["policy_id"],
                                "policy_version": shared_store_policy["policy_version"],
                                "approval_scope": shared_store_policy["approval_scope"],
                                "candidate_defaults": shared_store_policy["candidate_defaults"],
                                "section_dependencies": shared_store_policy["section_dependencies"],
                                "independent_sections": shared_store_policy["independent_sections"]},
        "owner_decision_batch": product_decision_batch,
        "partner_center": {"status": "NOT_CONNECTED", "writes_performed": False,
                            "certification_submitted": False, "published": False},
        "sections": sections,
        "owner_decisions": owner_decisions,
        "missing_or_unverified": gaps,
        "next_safe_actions": ["confirm exact source checkout and product evidence",
                              "verify exact local/artifact package",
                              "approve the Manifest-compatible Store device-family selection once in the product profile",
                              "persist the exact owner-approved automatic execution scopes before enabling store run live actions",
                              "run read-only Partner Center product/Draft reconciliation when authenticated CDP is available",
                              "collect owner-approved listing, pricing/market, legal and commercial inputs"],
        "write_scope": {"allowed_by_this_run": [], "prohibited": ["product creation", "submission creation",
                           "pricing/market changes", "store listing writes", "package upload/save",
                           "certification", "publish"]},
        "status": "READY_FOR_REVIEW" if not gaps else "INPUTS_REQUIRED",
    }


def write_unique_report(report: dict[str, Any], output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / f"{report['product_key']}-{report['created_at_utc'][:19].replace(':', '-')}-{report['run_id']}.json"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    return path


def write_store_report_with_fallback(
    report: dict[str, Any], output_root: Path, fallback_roots: list[Path]
) -> Path:
    """Write an append-only local report and fall back only on access denial.

    Store reports are local run evidence, not the durable upload ledger. If a
    repository's default report directory is read-only (for example in a
    managed desktop sandbox), keep the run usable by writing under a
    user-writable state/temp directory. Never overwrite an existing report.
    """
    try:
        return write_unique_report(report, output_root)
    except OSError as primary_error:
        last_error: OSError = primary_error
        for fallback_root in fallback_roots:
            if fallback_root.resolve() == output_root.resolve():
                continue
            try:
                path = write_unique_report(report, fallback_root)
                return path
            except OSError as exc:
                last_error = exc
        raise last_error
