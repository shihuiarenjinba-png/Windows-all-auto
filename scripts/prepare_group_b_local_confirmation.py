#!/usr/bin/env python3
"""Prepare one Group B product for minimal local Windows confirmation.

This command stages an exact GitHub Store artifact through the central registry,
creates the local QA evidence template, and writes a workspace manifest. It never
installs the MSIX or performs any Partner Center action.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class LocalConfirmationError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise LocalConfirmationError(f"{path.name} must contain a JSON object")
    return value


def build_workspace_manifest(
    artifact_receipt: dict[str, Any],
    qa_template: dict[str, Any],
    *,
    product_id: str,
    artifact_receipt_path: Path,
    qa_template_path: Path,
) -> dict[str, Any]:
    if artifact_receipt.get("schema_version") != "local-store-product-artifact-pull-receipt/1":
        raise LocalConfirmationError("unsupported artifact receipt schema")
    if artifact_receipt.get("status") != "LOCAL_STORE_PRODUCT_ARTIFACT_VERIFIED":
        raise LocalConfirmationError("artifact receipt is not verified")
    if artifact_receipt.get("product_id") != product_id:
        raise LocalConfirmationError("artifact receipt product mismatch")
    if artifact_receipt.get("central_registry_binding_verified") is not True:
        raise LocalConfirmationError("central registry binding was not verified")
    for flag in (
        "package_rebuilt",
        "security_bypass_used",
        "package_installed",
        "submitted_to_store",
        "certification_submitted",
        "published",
    ):
        if artifact_receipt.get(flag) is not False:
            raise LocalConfirmationError(f"unsafe artifact receipt flag: {flag}")

    if qa_template.get("schema_version") != "local-final-qa-receipt/1":
        raise LocalConfirmationError("unsupported local QA template schema")
    if qa_template.get("status") != "HOLD":
        raise LocalConfirmationError("local QA template must start as HOLD")
    if qa_template.get("github_ci_is_primary") is not True:
        raise LocalConfirmationError("GitHub CI must remain the primary test source")
    if qa_template.get("local_full_test_suite_required") is not False:
        raise LocalConfirmationError("local full test suite must not be required")
    if qa_template.get("test_source") != "github_exact_head_ci":
        raise LocalConfirmationError("unexpected local QA test source")

    package = artifact_receipt.get("package")
    identity = artifact_receipt.get("identity")
    if not isinstance(package, dict) or not isinstance(identity, dict):
        raise LocalConfirmationError("artifact receipt package/identity is missing")

    return {
        "schema_version": "group-b-local-confirmation-workspace/1",
        "status": "READY_FOR_LOCAL_WINDOWS_CONFIRMATION",
        "product_id": product_id,
        "product_name": artifact_receipt.get("product_name"),
        "repository_full_name": artifact_receipt.get("repository_full_name"),
        "workflow_name": artifact_receipt.get("workflow_name"),
        "workflow_head_sha": artifact_receipt.get("workflow_head_sha"),
        "artifact_run_id": artifact_receipt.get("artifact_run_id"),
        "artifact_name": artifact_receipt.get("artifact_name"),
        "source_sha": artifact_receipt.get("source_sha"),
        "store_id": artifact_receipt.get("store_id"),
        "identity": identity,
        "local_package_path": artifact_receipt.get("local_package_path"),
        "local_handoff_path": artifact_receipt.get("local_handoff_path"),
        "package": package,
        "artifact_receipt_path": str(artifact_receipt_path),
        "qa_template_path": str(qa_template_path),
        "local_only_checks": list(qa_template.get("product_specific_checks") or []),
        "github_ci_is_primary": True,
        "local_full_test_suite_required": False,
        "store_actions": {
            "package_upload": "NOT_EXECUTED",
            "certification": "NOT_EXECUTED",
            "publish": "NOT_EXECUTED",
        },
    }


def run_command(command: list[str]) -> None:
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise LocalConfirmationError(
            f"subcommand failed with exit code {result.returncode}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--run-id", type=int)
    args = parser.parse_args()

    try:
        workspace = args.workspace_root
        if workspace.exists() and workspace.is_symlink():
            raise LocalConfirmationError("refusing symlink workspace")
        workspace.mkdir(parents=True, exist_ok=True)

        artifact_root = workspace / "artifacts"
        evidence = workspace / "evidence"
        artifact_receipt_path = evidence / "artifact-pull-receipt.json"
        qa_template_path = evidence / "local-final-qa-template.json"
        manifest_path = workspace / "workspace.json"

        for path in (artifact_receipt_path, qa_template_path, manifest_path):
            if path.exists() or path.is_symlink():
                raise LocalConfirmationError(
                    f"workspace evidence already exists: {path.name}"
                )

        pull_cmd = [
            sys.executable,
            str(ROOT / "scripts" / "pull_group_b_store_product.py"),
            "--product-id",
            args.product_id,
            "--target-root",
            str(artifact_root),
            "--receipt",
            str(artifact_receipt_path),
        ]
        if args.run_id is not None:
            pull_cmd.extend(["--run-id", str(args.run_id)])
        run_command(pull_cmd)

        artifact_receipt = _load(artifact_receipt_path)
        handoff_path = Path(str(artifact_receipt.get("local_handoff_path") or ""))
        if not handoff_path.is_file():
            raise LocalConfirmationError("staged handoff file is missing")

        run_command(
            [
                sys.executable,
                str(ROOT / "scripts" / "create_local_final_qa_receipt_template.py"),
                "--handoff",
                str(handoff_path),
                "--output",
                str(qa_template_path),
            ]
        )
        qa_template = _load(qa_template_path)
        manifest = build_workspace_manifest(
            artifact_receipt,
            qa_template,
            product_id=args.product_id,
            artifact_receipt_path=artifact_receipt_path,
            qa_template_path=qa_template_path,
        )
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": manifest["status"],
                    "product_id": args.product_id,
                    "package_path": manifest["local_package_path"],
                    "workspace": str(workspace),
                    "manifest": str(manifest_path),
                    "store_write_performed": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (
        LocalConfirmationError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"GROUP_B_LOCAL_CONFIRMATION_HOLD: {str(exc)[:240]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
