from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "pull_group_b_store_product",
    ROOT / "scripts" / "pull_group_b_store_product.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class GroupBStoreRegistryTests(unittest.TestCase):
    def test_registry_has_unique_store_identity_and_only_three_direct_pull_products(self):
        path = ROOT / "ops" / "group_b_standard_store_products.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            data["schema_version"], "group-b-standard-store-products/1"
        )
        products = data["products"]
        self.assertEqual(
            set(products),
            {
                "folder-engine",
                "scheduled-api-runner",
                "workflow-automation-hub",
                "browser-automation-runner",
            },
        )
        direct = [
            product_id
            for product_id, product in products.items()
            if product.get("direct_product_artifact_pull_supported") is True
        ]
        self.assertEqual(
            set(direct),
            {
                "scheduled-api-runner",
                "workflow-automation-hub",
                "browser-automation-runner",
            },
        )
        store_ids = [p["store_id"] for p in products.values()]
        identities = [p["identity_name"] for p in products.values()]
        repos = [p["repository_full_name"] for p in products.values()]
        self.assertEqual(len(store_ids), len(set(store_ids)))
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(len(repos), len(set(repos)))

    def test_folder_direct_pull_is_rejected_to_preserve_frozen_pilot(self):
        with self.assertRaisesRegex(ValueError, "frozen"):
            MODULE.load_product(
                ROOT / "ops" / "group_b_standard_store_products.json",
                "folder-engine",
            )

    def test_direct_products_have_artifact_and_local_only_checks(self):
        registry = ROOT / "ops" / "group_b_standard_store_products.json"
        for product_id in (
            "scheduled-api-runner",
            "workflow-automation-hub",
            "browser-automation-runner",
        ):
            with self.subTest(product_id=product_id):
                product = MODULE.load_product(registry, product_id)
                self.assertTrue(product["artifact_name"].endswith("UNSIGNED-DRAFT"))
                self.assertEqual(product["architecture"], "x64")
                self.assertEqual(product["version"], "1.0.0.0")
                self.assertGreaterEqual(len(product["local_only_checks"]), 3)
                self.assertTrue(product["workflow_name"].strip())
                self.assertTrue(product["source_ref"].strip())

    def test_exact_head_run_selection_accepts_only_one_store_workflow_success(self):
        runs = [
            {
                "id": 10,
                "head_sha": "a" * 40,
                "name": "Windows build",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 11,
                "head_sha": "a" * 40,
                "name": "Reliability",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 12,
                "head_sha": "b" * 40,
                "name": "Windows build",
                "status": "completed",
                "conclusion": "success",
            },
        ]
        self.assertEqual(
            MODULE.select_exact_successful_run(
                runs,
                head_sha="a" * 40,
                workflow_name="Windows build",
            ),
            10,
        )

    def test_exact_head_run_selection_holds_when_missing_or_ambiguous(self):
        with self.assertRaisesRegex(ValueError, "no exact-head"):
            MODULE.select_exact_successful_run(
                [],
                head_sha="a" * 40,
                workflow_name="Windows build",
            )
        runs = [
            {
                "id": 10,
                "head_sha": "a" * 40,
                "name": "Windows build",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 11,
                "head_sha": "a" * 40,
                "name": "Windows build",
                "status": "completed",
                "conclusion": "success",
            },
        ]
        with self.assertRaisesRegex(ValueError, "multiple exact-head"):
            MODULE.select_exact_successful_run(
                runs,
                head_sha="a" * 40,
                workflow_name="Windows build",
            )

    def test_unknown_product_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown Group B product_id"):
            MODULE.load_product(
                ROOT / "ops" / "group_b_standard_store_products.json",
                "not-a-product",
            )

    def test_registry_schema_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "registry.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "wrong",
                        "products": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unsupported"):
                MODULE.load_product(path, "anything")


if __name__ == "__main__":
    unittest.main()
