#!/usr/bin/env python3
"""Pull one Group B standard Store artifact by product id and exact successful run.

This wrapper reads the checked-in registry so repository/artifact names are not
retyped manually. It delegates byte verification to pull_store_product_artifact.py.
It never performs Partner Center writes or package installation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "ops" / "group_b_standard_store_products.json"


def load_product(registry: Path, product_id: str) -> dict:
    data = json.loads(registry.read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != "group-b-standard-store-products/1":
        raise ValueError("unsupported Group B registry schema")
    products = data.get("products")
    if not isinstance(products, dict) or product_id not in products:
        raise ValueError("unknown Group B product_id")
    product = products[product_id]
    if not isinstance(product, dict):
        raise ValueError("Group B product entry is invalid")
    if product.get("direct_product_artifact_pull_supported") is not True:
        raise ValueError(
            str(product.get("reason") or "direct product artifact pull is disabled")
        )
    for key in (
        "repository_full_name",
        "artifact_name",
        "store_id",
        "identity_name",
        "version",
        "architecture",
        "workflow_name",
        "source_ref",
    ):
        if not isinstance(product.get(key), str) or not product[key].strip():
            raise ValueError(f"Group B product entry missing {key}")
    return product


def gh_json(endpoint: str) -> dict:
    result = subprocess.run(
        ["gh", "api", "-X", "GET", endpoint],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("GitHub API lookup failed")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("GitHub API returned invalid JSON")
    return value


def select_exact_successful_run(
    runs: list[dict],
    *,
    head_sha: str,
    workflow_name: str,
) -> int:
    matches = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("head_sha") == head_sha
        and run.get("name") == workflow_name
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and type(run.get("id")) is int
        and run["id"] > 0
    ]
    if not matches:
        raise ValueError("no exact-head successful Store artifact workflow run")
    if len(matches) != 1:
        raise ValueError(
            "multiple exact-head successful Store runs; specify --run-id explicitly"
        )
    return matches[0]["id"]


def resolve_registered_head(product: dict) -> str:
    repository = product["repository_full_name"]
    source_ref = product["source_ref"]
    commit = gh_json(
        f"repos/{repository}/commits/{quote(source_ref, safe='')}"
    )
    head_sha = str(commit.get("sha") or "")
    if len(head_sha) != 40:
        raise ValueError("registered source_ref did not resolve to a commit")
    return head_sha


def require_explicit_run_matches_head(
    product: dict,
    *,
    run_id: int,
    head_sha: str,
) -> None:
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("run-id must be positive")
    run = gh_json(
        f"repos/{product['repository_full_name']}/actions/runs/{run_id}"
    )
    if run.get("head_sha") != head_sha:
        raise ValueError("explicit run-id is not for the current registered branch HEAD")
    if run.get("name") != product["workflow_name"]:
        raise ValueError("explicit run-id is not the registered Store workflow")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError("explicit run-id is not a completed SUCCESS Store workflow")


def discover_run_id(product: dict, *, head_sha: str) -> int:
    repository = product["repository_full_name"]
    source_ref = product["source_ref"]
    response = gh_json(
        f"repos/{repository}/actions/runs?branch={quote(source_ref, safe='')}&status=success&per_page=100"
    )
    runs = response.get("workflow_runs")
    if not isinstance(runs, list):
        raise ValueError("GitHub Actions run listing is invalid")
    return select_exact_successful_run(
        runs,
        head_sha=head_sha,
        workflow_name=product["workflow_name"],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-id", required=True)
    parser.add_argument(
        "--run-id",
        type=int,
        help="Exact successful Store workflow run. Omit to discover a unique exact-head SUCCESS run.",
    )
    parser.add_argument("--target-root", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()

    try:
        product = load_product(args.registry, args.product_id)
        head_sha = resolve_registered_head(product)
        if args.run_id is not None:
            require_explicit_run_matches_head(
                product,
                run_id=args.run_id,
                head_sha=head_sha,
            )
            run_id = args.run_id
        else:
            run_id = discover_run_id(product, head_sha=head_sha)
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "pull_store_product_artifact.py"),
            "--repo",
            product["repository_full_name"],
            "--run-id",
            str(run_id),
            "--artifact-name",
            product["artifact_name"],
            "--target-root",
            str(args.target_root),
            "--receipt",
            str(args.receipt),
            "--expected-store-id",
            product["store_id"],
            "--expected-identity-name",
            product["identity_name"],
            "--expected-version",
            product["version"],
            "--expected-architecture",
            product["architecture"],
            "--expected-workflow-name",
            product["workflow_name"],
        ]
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            return result.returncode
        print(
            json.dumps(
                {
                    "status": "GROUP_B_PRODUCT_ARTIFACT_STAGED",
                    "product_id": args.product_id,
                    "store_id": product["store_id"],
                    "identity_name": product["identity_name"],
                    "run_id": run_id,
                    "registered_head_sha": head_sha,
                    "run_id_source": "explicit" if args.run_id is not None else "exact_head_discovery",
                    "receipt": str(args.receipt),
                    "submitted_to_store": False,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"GROUP_B_ARTIFACT_HOLD: {str(exc)[:240]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
