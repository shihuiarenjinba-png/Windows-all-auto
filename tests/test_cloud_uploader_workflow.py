from pathlib import Path
import unittest
import json


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "store-cloud-uploader.yml"


class CloudUploaderWorkflowTests(unittest.TestCase):
    def test_same_product_is_serialized_for_manual_and_repository_dispatch(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        product_key = "inputs.product || github.event.client_payload.product"
        self.assertIn(f"group: store-upload-${{{{ {product_key} }}}}", workflow)
        self.assertIn(f"PRODUCT_KEY: ${{{{ {product_key} }}}}", workflow)

    def test_sqlite_and_artifact_are_not_the_durable_receipt_ledger(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("group: store-uploader-durable-receipt-ledger-${{ inputs.product || github.event.client_payload.product }}", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("python -m uploader.github_receipt_ledger --receipt .uploader-run/receipt.json", workflow)
        self.assertIn("retention-days: 30", workflow)

    def test_data_contract_auditor_has_one_exact_existing_draft_package_upload_approval(self):
        config = ROOT / "uploader" / "config" / "data-contract-auditor.job.json"
        values = json.loads(config.read_text(encoding="utf-8"))
        self.assertIs(values["upload_approved"], True)
        self.assertEqual(values["upload_scope"], "ONE_EXACT_MSIX_TO_EXISTING_DRAFT_PACKAGES_ONLY")
        self.assertEqual(values["approval_ref"], "USER_CHAT_AUTHORIZATION_2026-11-25_PROCEED_TO_SUBMISSION")
        self.assertEqual(values["expected_sha256"], "e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05")
        self.assertEqual(values["ref"], "722ec7a077d2c6109e657c4ee661c9f3d06a4506")
        self.assertIs(values["certification_submission_authorized"], False)
        self.assertIs(values["publish_authorized"], False)


if __name__ == "__main__":
    unittest.main()
