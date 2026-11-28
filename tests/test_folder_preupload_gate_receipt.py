from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FolderPreuploadGateReceiptTests(unittest.TestCase):
    def test_exact_live_receipt_records_ready_rehash(self):
        payload = json.loads(
            (
                ROOT
                / "ops"
                / "folder_engine_preupload_gate_input_20261119.json"
            ).read_text(encoding="utf-8")
        )
        receipt = json.loads(
            (
                ROOT
                / "ops"
                / "folder_engine_preupload_gate_receipt_20261119.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["status"], "READY_FOR_MSIX_UPLOAD_APPROVAL")
        self.assertTrue(receipt["local_package"]["rehash_performed"])
        self.assertEqual(
            receipt["local_package"]["sha256"],
            "3C6BC8C1291450905AE71834F2704A59325D1AAA1C9DE3F064BCB8C7EBCA9FB9",
        )
        self.assertEqual(
            payload["expected"]["package_sha256"],
            receipt["local_package"]["sha256"],
        )
        self.assertEqual(receipt["draft"]["store_id"], "9P99MJX1R4V6")
        self.assertEqual(
            receipt["draft"]["draft_id"], "1152921505702423660"
        )
        self.assertEqual(receipt["package_upload"], "NOT_EXECUTED")
        self.assertEqual(receipt["certification"], "NOT_EXECUTED")
        self.assertEqual(receipt["publish"], "NOT_EXECUTED")


if __name__ == "__main__":
    unittest.main()
