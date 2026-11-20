from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_local_store_upload_candidate",
    ROOT / "scripts" / "check_local_store_upload_candidate.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

FIXTURE = ROOT / "tests" / "fixtures" / "folder_engine_paid_trial_handoff_v2.json"


def load_handoff() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def bind_draft(handoff: dict) -> None:
    handoff["product"]["draft_id"] = "1152921505702999999"
    handoff["product"]["draft_url"] = (
        "https://partner.microsoft.com/en-us/dashboard/products/"
        "9P99MJX1R4V6/submissions/1152921505702999999"
    )
    handoff["approvals"]["initial_submission_start_completed"] = True


class LocalStoreUploadCandidateTests(unittest.TestCase):
    def test_missing_local_package_holds(self):
        handoff = load_handoff()
        bind_draft(handoff)
        result = MODULE.evaluate(handoff, Path("Z:/definitely-missing/package.msix"))
        self.assertEqual(result["status"], "HOLD_LOCAL_MSIX_NOT_FOUND")

    def test_sha_mismatch_holds(self):
        handoff = load_handoff()
        bind_draft(handoff)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / handoff["package"]["file_name"]
            path.write_bytes(b"wrong")
            result = MODULE.evaluate(handoff, path)
        self.assertEqual(result["status"], "HOLD_LOCAL_MSIX_SHA_MISMATCH")

    def test_missing_draft_binding_holds_after_exact_package(self):
        handoff = load_handoff()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "candidate.msix"
            path.write_bytes(b"candidate")
            handoff["package"]["file_name"] = path.name
            handoff["package"]["package_sha256"] = hashlib.sha256(b"candidate").hexdigest()
            handoff["security"]["package_sha256"] = handoff["package"]["package_sha256"]
            result = MODULE.evaluate(handoff, path)
        self.assertEqual(result["status"], "HOLD_SUBMISSION_RECONCILE_REQUIRED")

    def test_exact_local_package_and_draft_reaches_approval_gate(self):
        handoff = load_handoff()
        bind_draft(handoff)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "candidate.msix"
            path.write_bytes(b"candidate")
            handoff["package"]["file_name"] = path.name
            handoff["package"]["package_sha256"] = hashlib.sha256(b"candidate").hexdigest()
            handoff["security"]["package_sha256"] = handoff["package"]["package_sha256"]
            result = MODULE.evaluate(handoff, path)
        self.assertEqual(result["status"], "READY_FOR_MSIX_UPLOAD_APPROVAL")
        self.assertTrue(result["exact_package_match"])
        self.assertFalse(result["package_upload_executed"])
        self.assertFalse(result["certification_executed"])
        self.assertFalse(result["published"])

    def test_empty_assets_directory_holds_when_explicitly_checked(self):
        handoff = load_handoff()
        bind_draft(handoff)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "candidate.msix"
            path.write_bytes(b"candidate")
            handoff["package"]["file_name"] = path.name
            handoff["package"]["package_sha256"] = hashlib.sha256(b"candidate").hexdigest()
            handoff["security"]["package_sha256"] = handoff["package"]["package_sha256"]
            assets = root / "assets"
            assets.mkdir()
            result = MODULE.evaluate(handoff, path, assets)
        self.assertEqual(result["status"], "HOLD_STORE_ASSETS")


if __name__ == "__main__":
    unittest.main()
