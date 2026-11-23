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

    def test_data_contract_auditor_live_upload_remains_unapproved(self):
        config = ROOT / "uploader" / "config" / "data-contract-auditor.job.json"
        values = json.loads(config.read_text(encoding="utf-8"))
        self.assertIs(values["upload_approved"], False)
        self.assertIn("REPLACE_", values["expected_sha256"])


if __name__ == "__main__":
    unittest.main()
