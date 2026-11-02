"""Positive/negative read-only archive and mixed POST/PRE resume regression."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.batch4_archive_resume_guard import (
    ContractHold, _strict_json, build_plan,
)

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"


class Batch4ArchiveResumeGuardTests(unittest.TestCase):
    def setUp(self):
        self.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_current_projection_is_no_work_no_unverified_local_success(self):
        plan = build_plan(self.ledger)
        self.assertEqual((plan["app_post_identity"], plan["all_lane_post_identity"]),
                         (2, 3))  # Prism is a separate 3D post-Identity lane
        self.assertEqual(plan["cloud_discovered"], 4)
        self.assertEqual(plan["physical_local_discovered"], 0)
        self.assertEqual(plan["physical_local_processed"], 0)
        self.assertFalse(plan["scheduled_trigger_proven"])
        self.assertFalse(plan["physical_windows_pass"])
        self.assertFalse(plan["real_msix_pass"])
        self.assertEqual([x["action"] for x in plan["results"]], [
            "NO_WORK_POST_IDENTITY__NO_PRODUCT_CREATE_NO_CAS",
            "NO_WORK_POST_IDENTITY__NO_PRODUCT_CREATE_NO_CAS",
            "HOLD_LOCAL_ARCHIVE_BYTES_NOT_MOUNTED",
            "HOLD_ARCHIVE_NOT_PRESERVED__NO_AUTO_DOWNLOAD",
        ])

    def _synthetic_text_archive(self, root, *, bad_request=False):
        job = self.ledger["rotation_cohorts"]["app_jobs"][2]
        batch = self.ledger["multi_product_partner_center_batch_4"]["products"][2]
        record = next(r for r in self.ledger["revision_review_reconciliation"][
            "artifact_byte_preservation_20261102"]["records"]
            if r["artifact_id"] == batch["artifact_id"])
        exe = b"synthetic-test-executable-not-real-binary"
        exe_sha = hashlib.sha256(exe).hexdigest()
        job["expected_exe_sha256"] = exe_sha
        job["expected_exe_bytes"] = len(exe)
        batch["exe_sha256"] = exe_sha
        record["exe_sha256"] = exe_sha
        handoff = {"slug": job["slug"], "repo": job["source_repository"],
                   "source_branch": job["source_branch"], "source_sha": job["source_sha"],
                   "request_id": "wrong-other-product" if bad_request else job["request_id"],
                   "partner_center_registration_type": job["registration_type"],
                   "partner_center_selection": job["partner_center_selection"],
                   "product_type": "APP"}
        receipt = {"slug": job["slug"], "source_sha": job["source_sha"],
                   "source_branch": job["source_branch"], "request_id": job["request_id"],
                   "source_repository": job["source_repository"],
                   "executable_sha256": exe_sha, "executable_bytes": len(exe)}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("registration-handoff.json", json.dumps(handoff))
            z.writestr("exe-receipt.json", json.dumps(receipt))
            z.writestr(job["slug"] + ".exe", exe)
        data = buf.getvalue()
        zip_sha = hashlib.sha256(data).hexdigest()
        record["archive_sha256"] = zip_sha
        record["archive_bytes"] = len(data)
        batch["artifact_zip_sha256"] = zip_sha
        job["factory_artifact_zip_sha256"] = zip_sha
        path = root / ("artifact-" + str(batch["artifact_id"]) + ".zip")
        path.write_bytes(data)
        return path

    def test_verified_preserved_text_archive_reuse_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._synthetic_text_archive(root)
            result = build_plan(self.ledger, root)
            self.assertEqual(result["results"][2]["action"],
                             "READ_ONLY_ARCHIVE_REUSE_VERIFIED__IDENTITY_RETURN_PENDING")
            self.assertIn("HOLD_ARCHIVE_NOT_PRESERVED", result["results"][3]["action"])
            self.assertEqual(result["physical_local_processed"], 0)

    def test_cross_product_request_in_archive_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._synthetic_text_archive(root, bad_request=True)
            result = build_plan(self.ledger, root)
            self.assertEqual(result["results"][2]["action"],
                             "HOLD_ARCHIVE_EMBEDDED_BINDING_MISMATCH")

    def test_corrupt_archive_bytes_never_fall_back_to_github(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._synthetic_text_archive(root)
            path.write_bytes(path.read_bytes() + b"tamper")
            result = build_plan(self.ledger, root)
            self.assertEqual(result["results"][2]["action"], "HOLD_ARCHIVE_BYTE_SIZE_MISMATCH")

    def test_expired_github_ttl_does_not_invalidate_verified_preserved_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._synthetic_text_archive(root)
            # Historical expiry is a binding, not permission to re-download.
            self.assertLess(self.ledger["multi_product_partner_center_batch_4"]
                            ["products"][2]["artifact_expiry_utc"], "2026-11-03")
            self.assertIn("READ_ONLY_ARCHIVE_REUSE_VERIFIED",
                          build_plan(self.ledger, root)["results"][2]["action"])

    def test_post_identity_cas_commit_conflict_is_not_no_work(self):
        self.ledger["multi_product_partner_center_batch_4"]["products"][0][
            "identity_return_commit_sha"] = "f" * 40
        with self.assertRaisesRegex(ContractHold, "POST_IDENTITY_RETURN_CONFLICT"):
            build_plan(self.ledger)

    def test_duplicate_return_target_is_rejected(self):
        jobs = self.ledger["rotation_cohorts"]["app_jobs"]
        jobs[3]["identity_return_target"] = jobs[2]["identity_return_target"]
        with self.assertRaisesRegex(ContractHold, "CROSS_PRODUCT_COLLISION"):
            build_plan(self.ledger)

    def test_false_local_or_scheduler_pass_is_rejected(self):
        batch = self.ledger["multi_product_partner_center_batch_4"]
        batch["processed_count"] = 4
        with self.assertRaisesRegex(ContractHold, "PHYSICAL_PROOF_CONFLICT"):
            build_plan(self.ledger)

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(ContractHold, "DUPLICATE_JSON_KEY"):
            _strict_json(b'{"request_id":"a","request_id":"b"}')


if __name__ == "__main__":
    unittest.main()
