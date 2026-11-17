"""CLI: download an exact GitHub Actions artifact into local QA intake."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from all_auto.github_artifact_intake import ArtifactIntakeHold, fetch_actions_artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--executable-sha256", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = fetch_actions_artifact(
            repository=args.repository,
            artifact_id=args.artifact_id,
            expected_name=args.artifact_name,
            expected_run_id=args.workflow_run_id,
            expected_head_sha=args.source_sha,
            expected_archive_sha256=args.archive_sha256,
            expected_package_name=args.package_name,
            expected_package_sha256=args.package_sha256,
            expected_executable_sha256=args.executable_sha256,
            destination=args.destination,
        )
    except ArtifactIntakeHold as exc:
        print(json.dumps({
            "status": "GITHUB_ARTIFACT_INTAKE_HOLD",
            "reason": str(exc),
            "store_purchase_required": False,
            "security_policy_changed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({
        "status": "GITHUB_ARTIFACT_INTAKE_READY",
        **result.metadata,
        "manifest_path": str(result.manifest_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
