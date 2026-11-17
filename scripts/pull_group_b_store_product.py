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
    ):
        if not isinstance(product.get(key), str) or not product[key].strip():
            raise ValueError(f"Group B product entry missing {key}")
    return product


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--target-root", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()

    try:
        product = load_product(args.registry, args.product_id)
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "pull_store_product_artifact.py"),
            "--repo",
            product["repository_full_name"],
            "--run-id",
            str(args.run_id),
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
                    "run_id": args.run_id,
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
