"""Keep Prism's current Factory source distinct from QA tooling and historical Identity."""
import json
import unittest
from pathlib import Path


class PrismCurrentSourceReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.data = json.loads(
            (root / "ops" / "prism_current_source_reconciliation_20261127.json")
            .read_text(encoding="utf-8")
        )

    def test_4c_commit_is_qa_tooling_not_product_source(self):
        tooling = self.data["correction"]["tooling_commit"]
        self.assertEqual(tooling["sha"],
                         "4c22875c5ed79d393516c6a7a95361b9e9ed1950")
        self.assertEqual(tooling["changed_files"],
                         ["tools/prism_revision_package_binding.py"])
        self.assertIs(tooling["product_source"], False)
        self.assertEqual(
            self.data["current_product_source"]["head_sha"],
            "b03ce7b16c3f75c04fe20fdda224c45849eeba0d",
        )

    def test_current_factory_tuple_and_old_identity_are_separate(self):
        product = self.data["current_product_source"]
        self.assertEqual(product["pr"], 25)
        self.assertEqual(product["request_id"],
                         "3d-prism-route-3d-b03ce7b16c3f")
        identity = product["approved_identity_file"]
        self.assertEqual(identity["source_sha"],
                         "15fdcb52e46e35e6de8e87c55af99719c21e09b9")
        self.assertEqual(identity["request_id"],
                         "3d-prism-route-3d-15fdcb52e46e")
        self.assertFalse(identity["old_identity_reuse_allowed"])
        self.assertEqual(identity["current_source_binding_status"],
                         "HISTORICAL_SOURCE_MISMATCH")
        self.assertIsNone(product["package_version"])
        self.assertIs(product["real_msix"], False)

    def test_independent_qa_head_is_current_and_cloud_only(self):
        qa = self.data["independent_qa"]
        self.assertEqual(qa["pr"], 19)
        self.assertEqual(qa["current_head_sha"],
                         "9b90bfc9dfa6ded9699c3f22df45390be909dae8")
        self.assertEqual(qa["exact_head_ci_status"], "PASS_8_OF_8")
        self.assertEqual(len(qa["exact_head_ci"]), 8)
        self.assertTrue(all(run["conclusion"] == "success"
                            for run in qa["exact_head_ci"]))
        self.assertTrue(qa["cloud_ci_is_not_physical_qa"])

    def test_physical_qa_and_store_gates_remain_held(self):
        qa = self.data["independent_qa"]
        self.assertEqual(qa["physical_windows_sessions_completed"], 0)
        self.assertEqual(qa["physical_windows_sessions_required"], 6)
        self.assertEqual(qa["physical_screenshots_completed"], 0)
        self.assertEqual(qa["physical_screenshots_required"], 36)
        gates = self.data["product_gate"]
        self.assertEqual(gates["physical_windows_qa"],
                         "0_OF_6_SESSIONS__0_OF_36_SCREENSHOTS")
        self.assertIs(gates["store_submission_allowed"], False)
        self.assertIs(gates["certification_allowed"], False)
        self.assertIs(gates["publish_allowed"], False)
        self.assertIs(gates["sale_ready"], False)


if __name__ == "__main__":
    unittest.main()
