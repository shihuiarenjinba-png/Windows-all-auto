"""Fail-closed Prism post-Identity package/backlog contract regression tests.

This is a software-only contract fixture, NOT an MSIX, CAS or physical E2E receipt.
No operator-approved Package Version is supplied or inferred here.
"""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
CURRENT = "4c22875c5ed79d393516c6a7a95361b9e9ed1950"
REQUEST = "3d-prism-route-3d-4c22875c5ed7"
OLD = "e8c77192a06527b005168359433f2868ff86708e"


def validate_prism_package_gate(record, approved_version=None, package_receipt=None):
    """Reject package promotion until exact current evidence and approved Version exist."""
    receipt = record["current_36_receipt_verification"]
    identity = record["official_identity_readonly_preflight_20261109"]
    if receipt["source_sha"] != CURRENT or receipt["request_id"] != REQUEST:
        return "HOLD_SOURCE_REQUEST_DRIFT"
    if not record["current_36_receipt_independently_rehashed"]:
        return "HOLD_INDEPENDENT_QA"
    if receipt["software_runtime_qa"] != "PASS":
        return "HOLD_SOFTWARE_QA"
    if identity["identity_source_sha"] == CURRENT or identity["identity_request_id"] == REQUEST:
        return "HOLD_IDENTITY_PROVENANCE_OVERWRITE"
    if not identity["reviewed"] or identity["source"] != "partner_center":
        return "HOLD_OFFICIAL_IDENTITY"
    if approved_version is None:
        return "HOLD_VERSION_NOT_APPROVED"
    if not isinstance(approved_version, str) or len(approved_version.split(".")) != 4 or any(
        not part.isdecimal() or int(part) > 65535 for part in approved_version.split(".")
    ):
        return "HOLD_INVALID_VERSION"
    if package_receipt is None:
        return "HOLD_REAL_MSIX_NOT_VERIFIED"
    required = ("source_sha", "request_id", "version", "identity_store_id", "package_sha256")
    if any(not package_receipt.get(k) for k in required):
        return "HOLD_INCOMPLETE_PACKAGE_RECEIPT"
    if (package_receipt["source_sha"] != CURRENT
            or package_receipt["request_id"] != REQUEST
            or package_receipt["version"] != approved_version
            or package_receipt["identity_store_id"] != identity["identity_store_id"]):
        return "HOLD_PACKAGE_PROVENANCE_MISMATCH"
    return "PACKAGE_RECEIPT_CONTRACT_VALIDATED_NOT_LOCAL_E2E"


def validate_backlog_handoff(package_receipt, backlog_receipt, local_receipt=None):
    """Software-only handoff contract; never infer physical installation or E2E."""
    if not package_receipt or not package_receipt.get("package_sha256"):
        return "HOLD_REAL_PACKAGE_RECEIPT"
    if not backlog_receipt:
        return "HOLD_BACKLOG_RECEIPT"
    fields = ("source_sha", "request_id", "version", "identity_store_id", "package_sha256")
    if any(not backlog_receipt.get(k) or backlog_receipt[k] != package_receipt.get(k) for k in fields):
        return "HOLD_BACKLOG_PACKAGE_MISMATCH"
    if not local_receipt:
        return "HOLD_LOCAL_PULL_RECEIPT"
    if any(local_receipt.get(k) != backlog_receipt[k] for k in fields):
        return "HOLD_LOCAL_PACKAGE_MISMATCH"
    return "HANDOFF_CONTRACT_VALIDATED_NOT_INSTALL_OR_GUI_E2E"


class PrismPackageGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.record = cls.ledger["prism_pr25_4c22875c_independent_qa_gate_reconciliation_20261109"]

    def test_current_software_qa_and_historical_source_separate(self):
        self.assertEqual(self.record["current_factory_head"], CURRENT)
        self.assertEqual(self.record["current_36_receipt_verification"]["source_sha"], CURRENT)
        self.assertEqual(self.record["qa_pin_mismatch"]["qa_pinned_factory_source"], OLD)
        self.assertEqual(self.record["identity_state"], "POST_IDENTITY_UPGRADE")
        self.assertFalse(self.record["physical_windows_e2e_pass"])

    def test_no_approved_version_fail_closed(self):
        self.assertIsNone(self.record["official_identity_readonly_preflight_20261109"]["approved_version"])
        self.assertEqual(validate_prism_package_gate(self.record), "HOLD_VERSION_NOT_APPROVED")

    def test_source_request_drift_rejected(self):
        changed = copy.deepcopy(self.record)
        changed["current_36_receipt_verification"]["request_id"] = "another-lane"
        self.assertEqual(validate_prism_package_gate(changed), "HOLD_SOURCE_REQUEST_DRIFT")

    def test_qa_not_rehashed_rejected(self):
        changed = copy.deepcopy(self.record)
        changed["current_36_receipt_independently_rehashed"] = False
        self.assertEqual(validate_prism_package_gate(changed), "HOLD_INDEPENDENT_QA")

    def test_version_does_not_imply_msix_or_e2e(self):
        self.assertEqual(validate_prism_package_gate(self.record, "1.0.0.0"), "HOLD_REAL_MSIX_NOT_VERIFIED")
        self.assertFalse(self.record["real_msix_verified"])
        self.assertIsNone(self.record["backlog_receipt"])
        self.assertIsNone(self.record["local_qa_receipt"])

    def test_cross_lane_and_version_mismatch_rejected(self):
        receipt = {"source_sha": CURRENT, "request_id": REQUEST, "version": "1.0.0.0",
                   "identity_store_id": "WRONG", "package_sha256": "a" * 64}
        self.assertEqual(validate_prism_package_gate(self.record, "1.0.0.0", receipt),
                         "HOLD_PACKAGE_PROVENANCE_MISMATCH")
        self.assertEqual(validate_prism_package_gate(self.record, "1.0", receipt),
                         "HOLD_INVALID_VERSION")

    def test_backlog_and_local_receipts_fail_closed(self):
        package = {"source_sha": CURRENT, "request_id": REQUEST, "version": "1.0.0.0",
                   "identity_store_id": "TEST_ONLY", "package_sha256": "a" * 64}
        self.assertEqual(validate_backlog_handoff(None, None), "HOLD_REAL_PACKAGE_RECEIPT")
        self.assertEqual(validate_backlog_handoff(package, None), "HOLD_BACKLOG_RECEIPT")
        mismatch = dict(package, package_sha256="b" * 64)
        self.assertEqual(validate_backlog_handoff(package, mismatch), "HOLD_BACKLOG_PACKAGE_MISMATCH")
        self.assertEqual(validate_backlog_handoff(package, package), "HOLD_LOCAL_PULL_RECEIPT")
        self.assertEqual(validate_backlog_handoff(package, package, mismatch), "HOLD_LOCAL_PACKAGE_MISMATCH")
        self.assertEqual(validate_backlog_handoff(package, package, package),
                         "HANDOFF_CONTRACT_VALIDATED_NOT_INSTALL_OR_GUI_E2E")
        self.assertFalse(self.record["physical_windows_e2e_pass"])


if __name__ == "__main__":
    unittest.main()
