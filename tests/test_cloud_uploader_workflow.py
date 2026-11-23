from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "store-cloud-uploader.yml"


class CloudUploaderWorkflowTests(unittest.TestCase):
    def test_same_product_is_serialized_for_manual_and_repository_dispatch(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        product_key = "inputs.product || github.event.client_payload.product"
        self.assertIn(f"group: store-upload-${{{{ {product_key} }}}}", workflow)
        self.assertIn(f"PRODUCT_KEY: ${{{{ {product_key} }}}}", workflow)


if __name__ == "__main__":
    unittest.main()
