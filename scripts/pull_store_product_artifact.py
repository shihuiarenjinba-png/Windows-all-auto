#!/usr/bin/env python3
"""Download one exact successful product Store artifact and stage it locally.

Requires GitHub CLI authentication. This command is local-only and does not perform
Partner Center writes, package installation, signing, certification or publishing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from all_auto.product_artifact_pull import (
    ProductArtifactPullError,
    require_expected_identity,
    select_github_artifact_metadata,
    stage_verified_store_artifact,
    validate_extracted_store_artifact,
    write_immutable_receipt,
)


def gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise ProductArtifactPullError("GitHub CLI/API operation failed")
    return result.stdout


def fetch_artifact_metadata(repository: str, run_id: int, artifact_name: str) -> dict:
    raw = json.loads(
        gh(
            "api",
            "-X",
            "GET",
            f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",
        )
    )
    return select_github_artifact_metadata(
        raw.get("artifacts"),
        artifact_name=artifact_name,
    )


def verify_run(repository: str, run_id: int) -> dict:
    raw = json.loads(
        gh("api", "-X", "GET", f"repos/{repository}/actions/runs/{run_id}")
    )
    if raw.get("conclusion") != "success":
        raise ProductArtifactPullError("workflow run is not successful")
    head_sha = str(raw.get("head_sha") or "")
    if len(head_sha) != 40:
        raise ProductArtifactPullError("workflow run head SHA is invalid")
    return {
        "workflow_name": str(raw.get("name") or ""),
        "head_sha": head_sha,
        "event": str(raw.get("event") or ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="owner/repository")
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--target-root", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--expected-store-id")
    parser.add_argument("--expected-identity-name")
    parser.add_argument("--expected-version")
    parser.add_argument("--expected-architecture")
    parser.add_argument("--expected-workflow-name")
    parser.add_argument("--expected-artifact-id", type=int)
    parser.add_argument("--expected-artifact-digest")
    parser.add_argument("--expected-msix-sha256")
    parser.add_argument("--expected-exe-sha256")
    args = parser.parse_args()

    try:
        run = verify_run(args.repo, args.run_id)
        artifact_meta = fetch_artifact_metadata(
            args.repo,
            args.run_id,
            args.artifact_name,
        )
        if args.expected_artifact_id is not None:
            if artifact_meta["github_artifact_id"] != args.expected_artifact_id:
                raise ProductArtifactPullError("GitHub artifact id does not match frozen candidate")
        if args.expected_artifact_digest is not None:
            if artifact_meta["github_artifact_digest"] != args.expected_artifact_digest:
                raise ProductArtifactPullError("GitHub artifact digest does not match frozen candidate")
        if args.expected_workflow_name is not None:
            if not args.expected_workflow_name.strip():
                raise ProductArtifactPullError("expected workflow name is empty")
            if run["workflow_name"] != args.expected_workflow_name:
                raise ProductArtifactPullError("workflow name does not match central registry")
        with tempfile.TemporaryDirectory(prefix="store-product-artifact-") as td:
            root = Path(td)
            gh(
                "run",
                "download",
                str(args.run_id),
                "-R",
                args.repo,
                "--name",
                args.artifact_name,
                "--dir",
                str(root),
            )
            verified = validate_extracted_store_artifact(
                root,
                repository_full_name=args.repo,
                run_id=args.run_id,
                artifact_name=args.artifact_name,
            )
            if verified["source_sha"] != run["head_sha"]:
                raise ProductArtifactPullError(
                    "artifact source SHA does not match successful workflow head SHA"
                )
            if args.expected_msix_sha256 is not None:
                if verified["package"]["sha256"].lower() != args.expected_msix_sha256.lower():
                    raise ProductArtifactPullError("MSIX SHA256 does not match frozen candidate")
            if args.expected_exe_sha256 is not None:
                if verified["identity"] is None:
                    raise ProductArtifactPullError("verified identity is missing")
                handoff_exe_sha = str(
                    json.loads(
                        Path(verified["_source_paths"]["handoff"]).read_text(
                            encoding="utf-8-sig"
                        )
                    )["package"]["exe_sha256"]
                ).lower()
                if handoff_exe_sha != args.expected_exe_sha256.lower():
                    raise ProductArtifactPullError("EXE SHA256 does not match frozen candidate")
            expected_values = (
                args.expected_store_id,
                args.expected_identity_name,
                args.expected_version,
                args.expected_architecture,
            )
            if any(value is not None for value in expected_values):
                if not all(isinstance(value, str) and value.strip() for value in expected_values):
                    raise ProductArtifactPullError(
                        "all expected Store identity arguments are required together"
                    )
                require_expected_identity(
                    verified,
                    store_id=args.expected_store_id,
                    identity_name=args.expected_identity_name,
                    version=args.expected_version,
                    architecture=args.expected_architecture,
                )
            staged = stage_verified_store_artifact(
                verified,
                target_root=args.target_root,
            )
            staged["central_registry_binding_verified"] = all(
                isinstance(value, str) and bool(value.strip())
                for value in expected_values
            )
            if staged["central_registry_binding_verified"]:
                staged["central_registry_binding"] = {
                    "store_id": args.expected_store_id,
                    "identity_name": args.expected_identity_name,
                    "version": args.expected_version,
                    "architecture": args.expected_architecture,
                }
            staged["workflow_name"] = run["workflow_name"]
            staged["workflow_event"] = run["event"]
            staged["workflow_head_sha"] = run["head_sha"]
            staged.update(artifact_meta)
            write_immutable_receipt(args.receipt, staged)
        print(
            json.dumps(
                {
                    "status": staged["status"],
                    "product_id": staged["product_id"],
                    "package_path": staged["local_package_path"],
                    "receipt": str(args.receipt),
                    "submitted_to_store": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (
        ProductArtifactPullError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"LOCAL_STORE_ARTIFACT_HOLD: {str(exc)[:240]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
