from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import copy
import tempfile
import unittest

from all_auto.store_preupload_gate import evaluate_store_preupload_gate


STORE_ID = "9P99MJX1R4V6"


def draft_receipt():
    draft_id = "1152921505702999999"
    return {
        "schema_version": "existing-store-initial-submission-reconcile-receipt/1",
        "status": "INITIAL_SUBMISSION_DRAFT_PRESENT_RECOVERED",
        "submission_state": "EXISTING_PRODUCT_DRAFT_PRESENT",
        "store_id": STORE_ID,
        "draft_id": draft_id,
        "draft_url": (
            "https://partner.microsoft.com/en-us/dashboard/products/"
            f"{STORE_ID}/submissions/{draft_id}"
        ),
        "write_performed": False,
        "retry_authorized": False,
        "start_submission_clicked": False,
        "package_uploaded": False,
        "pricing_changed": False,
        "submitted": False,
        "published": False,
    }


class StorePreuploadGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name) / "FolderAutomationEngine_1.0.0.0_x64_StoreDraft_UNSIGNED.msix"
        self.package.write_bytes(b"frozen-msix-test-bytes")
        digest = sha256(self.package.read_bytes()).hexdigest().upper()
        expected = {
            "store_id": STORE_ID,
            "identity_name": "OkinawaDesktopTools.FolderAutomationEngine",
            "publisher": "CN=46263F21-A700-41DB-8C9B-114C22FB82FC",
            "version": "1.0.0.0",
            "architecture": "x64",
            "source_sha": "51597b389384be6cf2b3d85c09ee66099b80807e",
            "package_sha256": digest,
            "package_file_name": self.package.name,
        }
        self.payload = {
            "schema_version": "store-preupload-gate-input/1",
            "package_path": str(self.package),
            "expected": expected,
            "observed": copy.deepcopy(expected),
            "draft_reconciliation": draft_receipt(),
            "store_fields": {
                "packages": True,
                "pricing": True,
                "trial": True,
                "markets": True,
                "audience": True,
                "properties": True,
                "store_listings": True,
                "submission_options": True,
                "unknown_partner_center_state": False,
            },
            "assets": {"ready": True},
        }

    def status(self, payload=None):
        return evaluate_store_preupload_gate(payload or self.payload)["status"]

    def test_ready_rehashes_exact_local_package_and_performs_no_store_write(self):
        receipt = evaluate_store_preupload_gate(self.payload)
        self.assertEqual(receipt["status"], "READY_FOR_MSIX_UPLOAD_APPROVAL")
        self.assertTrue(receipt["local_package"]["rehash_performed"])
        self.assertFalse(receipt["write_performed"])
        self.assertEqual(receipt["start_submission"], "NOT_REPEATED")
        self.assertEqual(receipt["package_upload"], "NOT_EXECUTED")
        self.assertEqual(receipt["certification"], "NOT_EXECUTED")
        self.assertEqual(receipt["publish"], "NOT_EXECUTED")

    def test_missing_local_package(self):
        self.package.unlink()
        self.assertEqual(self.status(), "HOLD_LOCAL_MSIX_NOT_FOUND")

    def test_local_sha_mismatch(self):
        self.package.write_bytes(b"changed")
        self.assertEqual(self.status(), "HOLD_LOCAL_MSIX_SHA_MISMATCH")

    def test_no_draft_after_manual_start_claim(self):
        broken = copy.deepcopy(self.payload)
        broken["draft_reconciliation"]["status"] = "HOLD_SUBMISSION_RECONCILE_REQUIRED"
        self.assertEqual(self.status(broken), "HOLD_SUBMISSION_RECONCILE_REQUIRED")

    def test_ambiguous_or_mismatched_draft_url(self):
        broken = copy.deepcopy(self.payload)
        broken["draft_reconciliation"]["draft_url"] += "/another"
        self.assertEqual(self.status(broken), "HOLD_SUBMISSION_RECONCILE_REQUIRED")

    def test_draft_store_id_mismatch(self):
        broken = copy.deepcopy(self.payload)
        broken["draft_reconciliation"]["store_id"] = "WRONG"
        self.assertEqual(self.status(broken), "HOLD_SUBMISSION_RECONCILE_REQUIRED")

    def test_reconciliation_write_is_rejected(self):
        broken = copy.deepcopy(self.payload)
        broken["draft_reconciliation"]["write_performed"] = True
        self.assertEqual(self.status(broken), "HOLD_SUBMISSION_RECONCILE_REQUIRED")

    def test_exact_identity_mismatch(self):
        broken = copy.deepcopy(self.payload)
        broken["observed"]["publisher"] = "CN=WRONG"
        receipt = evaluate_store_preupload_gate(broken)
        self.assertEqual(receipt["status"], "HOLD_EXACT_PACKAGE_MISMATCH")
        self.assertEqual(receipt["mismatches"], ["publisher"])

    def test_assets_hold_precedes_store_field_unknown(self):
        broken = copy.deepcopy(self.payload)
        broken["assets"]["ready"] = False
        broken["store_fields"]["pricing"] = False
        self.assertEqual(self.status(broken), "HOLD_STORE_ASSETS")

    def test_unknown_partner_center_state(self):
        broken = copy.deepcopy(self.payload)
        broken["store_fields"]["pricing"] = False
        receipt = evaluate_store_preupload_gate(broken)
        self.assertEqual(receipt["status"], "HOLD_UNKNOWN_PARTNER_CENTER_STATE")
        self.assertEqual(receipt["unread_sections"], ["pricing"])


if __name__ == "__main__":
    unittest.main()

