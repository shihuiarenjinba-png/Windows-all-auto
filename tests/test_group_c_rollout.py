from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from all_auto.group_c_rollout import (
    GroupCRolloutError,
    load_registry,
    next_product,
    rollout_status,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "ops" / "group_c_store_products.json"


class GroupCRolloutTests(unittest.TestCase):
    def test_registry_fixes_six_product_order(self):
        registry = load_registry(REGISTRY_PATH)
        self.assertEqual(
            registry["execution_order"],
            [
                "data-contract-auditor",
                "web-evidence-archiver",
                "excel-csv-privacy-cleaner",
                "image-privacy-cleaner",
                "ai-upload-guard",
                "pdf-privacy",
            ],
        )

    def test_current_block_stops_every_later_product(self):
        registry = load_registry(REGISTRY_PATH)
        rows = rollout_status(ROOT, registry)
        self.assertEqual(
            rows[0]["effective_state"], "HOLD_FORMAL_VERSION_ASSETS_UI_QA"
        )
        self.assertTrue(
            all(
                row["effective_state"] == "WAITING_FOR_PREVIOUS_PRODUCT"
                for row in rows[1:]
            )
        )
        self.assertEqual(next_product(ROOT, registry)["product_id"], "data-contract-auditor")

    def test_completed_teacher_one_unlocks_only_teacher_two(self):
        registry = load_registry(REGISTRY_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            receipt_path = temp_root / registry["products"]["data-contract-auditor"]["receipt"]
            receipt_path.parent.mkdir(parents=True)
            receipt = json.loads(
                (ROOT / registry["products"]["data-contract-auditor"]["receipt"]).read_text(
                    encoding="utf-8"
                )
            )
            receipt["current_state"] = "READY_FOR_CERTIFICATION_REVIEW"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            rows = rollout_status(temp_root, registry)
            self.assertEqual(rows[0]["effective_state"], "READY_FOR_CERTIFICATION_REVIEW")
            self.assertEqual(
                rows[1]["effective_state"], "READY_FOR_WINDOWS_REAL_DEVICE_QA"
            )
            self.assertTrue(
                all(
                    row["effective_state"] == "WAITING_FOR_PREVIOUS_PRODUCT"
                    for row in rows[2:]
                )
            )

    def test_route_or_order_mutation_fails_closed(self):
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            wrong_order = copy.deepcopy(registry)
            wrong_order["execution_order"].reverse()
            path.write_text(json.dumps(wrong_order), encoding="utf-8")
            with self.assertRaisesRegex(GroupCRolloutError, "EXECUTION_ORDER"):
                load_registry(path)
            wrong_route = copy.deepcopy(registry)
            wrong_route["products"]["pdf-privacy"]["submission_route"] = "msix_pwa_game"
            path.write_text(json.dumps(wrong_route), encoding="utf-8")
            with self.assertRaisesRegex(GroupCRolloutError, "SUBMISSION_ROUTE"):
                load_registry(path)


if __name__ == "__main__":
    unittest.main()
