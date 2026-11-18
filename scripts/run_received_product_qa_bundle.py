"""Run one received product-QA bundle from GitHub artifact to local GUI evidence.

One JSON bundle contains immutable artifact provenance, the evidence job, and the
Factory-compatible bound product QA plan. This entrypoint downloads/verifies the
exact Actions artifact, writes the validated job/plan locally, then invokes the
Ollama-supervised trusted GUI evidence runner.

It does not upload evidence automatically because the captured screenshot still
requires explicit human privacy review.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from all_auto.github_artifact_intake import (  # noqa: E402
    ArtifactIntakeHold, fetch_actions_artifact,
)
from all_auto.product_qa_plan import (  # noqa: E402
    ProductQAPlanHold, canonical, load_bound_plan,
)
from scripts.trusted_product_gui_evidence import main as run_gui_evidence  # noqa: E402


BUNDLE_SCHEMA = "received-product-qa-bundle-v1"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BUNDLE_KEYS = {"schema_version", "artifact_source", "job", "bound_plan", "model"}
ARTIFACT_KEYS = {
    "repository", "artifact_id", "artifact_name", "workflow_run_id",
    "source_sha", "archive_sha256", "package_name", "package_sha256",
    "executable_sha256",
}


class ReceivedProductBundleHold(ValueError):
    pass


def _hold(reason: str) -> None:
    raise ReceivedProductBundleHold("RECEIVED_PRODUCT_BUNDLE_HOLD: " + reason)


def _load_bundle(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        _hold("bundle is missing, linked, or oversized")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReceivedProductBundleHold(
            "RECEIVED_PRODUCT_BUNDLE_HOLD: invalid JSON"
        ) from exc
    if not isinstance(value, dict) or set(value) != BUNDLE_KEYS:
        _hold("bundle fields are invalid")
    if value.get("schema_version") != BUNDLE_SCHEMA:
        _hold("bundle schema mismatch")
    source = value.get("artifact_source")
    if not isinstance(source, dict) or set(source) != ARTIFACT_KEYS:
        _hold("artifact_source fields are invalid")
    if not isinstance(source.get("repository"), str) or not REPOSITORY.fullmatch(
            source["repository"]):
        _hold("artifact repository invalid")
    for field in ("artifact_id", "workflow_run_id"):
        if type(source.get(field)) is not int or source[field] <= 0:
            _hold("invalid " + field)
    for field in ("artifact_name", "package_name"):
        if not isinstance(source.get(field), str) or not source[field]:
            _hold("invalid " + field)
    if not isinstance(source.get("source_sha"), str) or not SHA40.fullmatch(
            source["source_sha"]):
        _hold("invalid source_sha")
    for field in ("archive_sha256", "package_sha256", "executable_sha256"):
        if not isinstance(source.get(field), str) or not SHA64.fullmatch(
                source[field]):
            _hold("invalid " + field)
    if not isinstance(value.get("job"), dict) or not isinstance(
            value.get("bound_plan"), dict):
        _hold("job and bound_plan must be objects")
    model = value.get("model")
    if not isinstance(model, str) or not 1 <= len(model) <= 120 or any(
            character in model for character in "\r\n\x00"):
        _hold("invalid model")
    return value


def _cross_check(bundle: dict[str, Any]) -> None:
    source = bundle["artifact_source"]
    job = bundle["job"]
    plan = bundle["bound_plan"]
    if plan.get("source_sha") != source["source_sha"]:
        _hold("plan source SHA differs from artifact source")
    if plan.get("package_sha256") != source["package_sha256"]:
        _hold("plan package SHA differs from artifact source")
    if plan.get("executable_sha256") != source["executable_sha256"]:
        _hold("plan executable SHA differs from artifact source")
    if job.get("source_sha") != source["source_sha"]:
        _hold("job source SHA differs from artifact source")
    if job.get("artifact_sha256") != source["executable_sha256"]:
        _hold("job executable SHA differs from artifact source")
    if job.get("package_sha256") != source["package_sha256"]:
        _hold("job package SHA differs from artifact source")
    if job.get("artifact_archive_sha256") != source["archive_sha256"]:
        _hold("job archive SHA differs from artifact source")
    if job.get("github_actions_run_id") != source["workflow_run_id"]:
        _hold("job workflow run differs from artifact source")
    if job.get("github_artifact_id") != source["artifact_id"]:
        _hold("job artifact ID differs from artifact source")
    normalized = str(plan.get("source_repository", "")).removeprefix(
        "https://github.com/"
    ).removesuffix(".git")
    if normalized != source["repository"]:
        _hold("plan repository differs from artifact source")
    normalized_job = str(job.get("source_repository", "")).removeprefix(
        "https://github.com/"
    ).removesuffix(".git")
    if normalized_job != source["repository"]:
        _hold("job repository differs from artifact source")
    if job.get("qa_plan_template_sha256") != plan.get("template_sha256"):
        _hold("job QA template SHA differs from plan")
    if job.get("identity") != plan.get("identity"):
        _hold("job Identity differs from plan")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--approve-execution", action="store_true")
    args = parser.parse_args(argv)
    if not args.approve_execution:
        parser.error(
            "--approve-execution is required because this command starts and "
            "operates the exact received product"
        )

    try:
        bundle = _load_bundle(args.bundle)
        _cross_check(bundle)
        workspace = args.workspace.resolve()
        if args.workspace.is_symlink():
            _hold("workspace may not be a symlink")
        if workspace.exists() and any(workspace.iterdir()):
            _hold("workspace must be empty")
        workspace.mkdir(parents=True, exist_ok=True)

        source = bundle["artifact_source"]
        intake = fetch_actions_artifact(
            repository=source["repository"],
            artifact_id=source["artifact_id"],
            expected_name=source["artifact_name"],
            expected_run_id=source["workflow_run_id"],
            expected_head_sha=source["source_sha"],
            expected_archive_sha256=source["archive_sha256"],
            expected_package_name=source["package_name"],
            expected_package_sha256=source["package_sha256"],
            expected_executable_sha256=source["executable_sha256"],
            destination=workspace / "artifact-intake",
        )
        job_path = workspace / "job.json"
        plan_path = workspace / "bound-plan.json"
        job_path.write_text(
            json.dumps(bundle["job"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        plan_path.write_bytes(canonical(bundle["bound_plan"]) + b"\n")
        # Re-parse through the production validator before any product launch.
        load_bound_plan(plan_path)

        return run_gui_evidence([
            "--state-root", str(workspace / "evidence-state"),
            "--job", str(job_path),
            "--plan", str(plan_path),
            "--artifact", str(intake.executable_path),
            "--package", str(intake.package_path),
            "--model", bundle["model"],
        ])
    except (ReceivedProductBundleHold, ArtifactIntakeHold,
            ProductQAPlanHold, ValueError) as exc:
        print(json.dumps({
            "status": "RECEIVED_PRODUCT_BUNDLE_HOLD",
            "reason": str(exc),
            "product_e2e_pass": False,
            "release_ready": False,
            "store_submission_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
