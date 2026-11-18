from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from all_auto.product_qa_plan import load_bound_plan
from scripts.run_received_product_qa_bundle import (
    ReceivedProductBundleHold, _cross_check, _load_bundle, main,
)


class ReceivedProductQABundleTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.bundle_path = (
            self.root / "ops" / "received-product-qa" /
            "folio-ai-readonly-cbb9de.json"
        )

    def test_folio_bundle_cross_checks_and_plan_revalidates(self):
        bundle = _load_bundle(self.bundle_path)
        _cross_check(bundle)
        self.assertEqual(
            bundle["artifact_source"]["source_sha"],
            "cbb9de223c0eac79563651ba2d0ae22e43653d68",
        )
        self.assertEqual(
            bundle["bound_plan"]["template_sha256"],
            "f9277953933528dd8c21c1d4f7b1e2df56cabda3cc0d3541cd9a614a7fdba42e",
        )
        optional = [
            step for step in bundle["bound_plan"]["steps"]
            if step["required"] is False
        ]
        self.assertTrue(optional)
        self.assertTrue(all(
            step["action"] in {
                "PROCESS_STATUS", "UIA_FIND_WINDOW",
                "UIA_FIND_CONTROL", "UIA_READ_TEXT",
            }
            for step in optional
        ))
        with tempfile.TemporaryDirectory() as temporary:
            plan_path = Path(temporary) / "plan.json"
            plan_path.write_text(
                json.dumps(
                    bundle["bound_plan"], ensure_ascii=False,
                    sort_keys=True, separators=(",", ":"),
                ) + "\n",
                encoding="utf-8",
            )
            validated = load_bound_plan(plan_path)
        self.assertEqual(validated["product_slug"], "folio-ai")

    def test_cross_check_rejects_artifact_or_job_drift(self):
        bundle = json.loads(self.bundle_path.read_text(encoding="utf-8"))
        bundle["job"]["artifact_sha256"] = "0" * 64
        with self.assertRaisesRegex(
                ReceivedProductBundleHold, "job executable SHA"):
            _cross_check(bundle)

    def test_execution_requires_explicit_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(SystemExit) as caught:
                main([
                    "--bundle", str(self.bundle_path),
                    "--workspace", str(Path(temporary) / "run"),
                ])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
