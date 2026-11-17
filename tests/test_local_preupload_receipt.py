from __future__ import annotations

from hashlib import sha256
import copy
import json
from pathlib import Path
import unittest

from all_auto.local_preupload_receipt import (
    LocalPreuploadReceiptError,
    finalize_local_preupload_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "folder_engine_paid_trial_handoff_v2.json"


class LocalPreuploadReceiptTests(unittest.TestCase):
    def setUp(self):
        self.handoff = json.loads(FIXTURE.read_text(encoding="utf-8"))
        package = self.handoff["package"]
        identity = self.handoff["identity"]
        product = self.handoff["product"]
        self.candidate = {
            "schema_version": "store-preupload-readiness/1",
            "status": "READY_FOR_MSIX_UPLOAD_APPROVAL",
            "store_id": identity["store_id"],
            "source_sha": product["source_sha"],
            "expected_package_sha256": package["package_sha256"],
            "actual_package_sha256": package["package_sha256"],
            "expected_package_filename": package["file_name"],
            "package_filename": package["file_name"],
            "exact_package_match": True,
            "package_upload_executed": False,
            "certification_executed": False,
            "published": False,
        }
        self.preflight = {
            "schema_version": "local-static-package-preflight/1",
            "status": "PASS",
            "store_id": identity["store_id"],
            "source_sha": product["source_sha"],
            "local_repo_head": "9" * 40,
            "source_checkout_mode": "ContainedCommit",
            "package_sha256": package["package_sha256"],
            "unpacked_exe_sha256": package["exe_sha256"],
            "manifest_identity_verified": True,
            "package_rebuilt": False,
            "security_bypass_used": False,
            "self_test_pass": None,
        }

    def finalize(self, candidate=None, preflight=None):
        return finalize_local_preupload_receipt(
            candidate or self.candidate,
            preflight or self.preflight,
            self.handoff,
        )

    def test_ready_receipt_binds_static_evidence_without_store_write(self):
        result = self.finalize()
        self.assertEqual(result["status"], "READY_FOR_MSIX_UPLOAD_APPROVAL")
        self.assertEqual(result["receipt_kind"], "READ_ONLY_LOCAL_PREUPLOAD_HANDOFF")
        self.assertTrue(result["ready_for_upload_approval"])
        self.assertFalse(result["partner_center_write_performed"])
        self.assertEqual(result["static_preflight"]["status"], "PASS")
        self.assertIsNone(result["static_preflight"]["self_test_pass"])
        self.assertEqual(result["store_actions"]["package_upload"], "NOT_EXECUTED")
        self.assertEqual(
            result["immutable_binding"]["exe_sha256"],
            self.handoff["package"]["exe_sha256"],
        )

    def test_changed_exe_sha_is_rejected(self):
        changed = copy.deepcopy(self.preflight)
        changed["unpacked_exe_sha256"] = sha256(b"other exe").hexdigest()
        with self.assertRaisesRegex(LocalPreuploadReceiptError, "preflight EXE SHA"):
            self.finalize(preflight=changed)

    def test_store_write_claim_is_rejected(self):
        changed = copy.deepcopy(self.candidate)
        changed["package_upload_executed"] = True
        with self.assertRaisesRegex(LocalPreuploadReceiptError, "must be false"):
            self.finalize(candidate=changed)

    def test_rebuild_or_security_bypass_is_rejected(self):
        for field in ("package_rebuilt", "security_bypass_used"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.preflight)
                changed[field] = True
                with self.assertRaisesRegex(LocalPreuploadReceiptError, field):
                    self.finalize(preflight=changed)


if __name__ == "__main__":
    unittest.main()
