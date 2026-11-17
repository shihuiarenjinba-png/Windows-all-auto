from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


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

    def test_explicit_run_must_match_current_registered_head(self):
        product = MODULE.load_product(
            ROOT / "ops" / "group_b_standard_store_products.json",
            "scheduled-api-runner",
        )
        good_run = {
            "head_sha": "a" * 40,
            "name": product["workflow_name"],
            "status": "completed",
            "conclusion": "success",
        }
        with patch.object(MODULE, "gh_json", return_value=good_run):
            MODULE.require_explicit_run_matches_head(
                product,
                run_id=123,
                head_sha="a" * 40,
            )

        stale_run = dict(good_run)
        stale_run["head_sha"] = "b" * 40
        with patch.object(MODULE, "gh_json", return_value=stale_run):
            with self.assertRaisesRegex(ValueError, "current registered branch HEAD"):
                MODULE.require_explicit_run_matches_head(
                    product,
                    run_id=123,
                    head_sha="a" * 40,
                )

    def test_explicit_run_must_match_registered_store_workflow(self):
        product = MODULE.load_product(
            ROOT / "ops" / "group_b_standard_store_products.json",
            "scheduled-api-runner",
        )
        wrong_workflow = {
            "head_sha": "a" * 40,
            "name": "Reliability tests / 信頼性テスト",
            "status": "completed",
            "conclusion": "success",
        }
        with patch.object(MODULE, "gh_json", return_value=wrong_workflow):
            with self.assertRaisesRegex(ValueError, "registered Store workflow"):
                MODULE.require_explicit_run_matches_head(
                    product,
                    run_id=123,
                    head_sha="a" * 40,
                )

    def test_scheduled_locally_verified_candidate_is_frozen(self):
        product = MODULE.load_product(
            ROOT / "ops" / "group_b_standard_store_products.json",
            "scheduled-api-runner",
        )
        frozen = MODULE.get_frozen_candidate(product)
        self.assertIsNotNone(frozen)
        self.assertEqual(
            frozen["source_sha"],
            "28ef873ab2ff325b8f26c61a9ba48701280e8290",
        )
        self.assertEqual(frozen["store_run_id"], 44093493317)
        self.assertEqual(frozen["artifact_id"], 14333575447)
        self.assertTrue(frozen["local_static_verified"])
        self.assertTrue(frozen["promotion_requires_new_local_static_verification"])

    def test_invalid_frozen_candidate_fails_closed(self):
        product = MODULE.load_product(
            ROOT / "ops" / "group_b_standard_store_products.json",
            "scheduled-api-runner",
        )
        product = dict(product)
        product["frozen_candidate"] = {"local_static_verified": False}
        with self.assertRaisesRegex(ValueError, "not locally static-verified"):
            MODULE.get_frozen_candidate(product)

    def test_frozen_candidate_run_must_match_frozen_source(self):
        product = MODULE.load_product(
            ROOT / "ops" / "group_b_standard_store_products.json",
            "scheduled-api-runner",
        )
        frozen = MODULE.get_frozen_candidate(product)
        run = {
            "head_sha": frozen["source_sha"],
            "name": product["workflow_name"],
            "status": "completed",
            "conclusion": "success",
        }
        with patch.object(MODULE, "gh_json", return_value=run):
            MODULE.require_run_matches_source(
                product,
                run_id=frozen["store_run_id"],
                source_sha=frozen["source_sha"],
            )

        stale = dict(run)
        stale["head_sha"] = "0" * 40
        with patch.object(MODULE, "gh_json", return_value=stale):
            with self.assertRaisesRegex(ValueError, "required candidate source SHA"):
                MODULE.require_run_matches_source(
                    product,
                    run_id=frozen["store_run_id"],
                    source_sha=frozen["source_sha"],
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
