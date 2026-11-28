import json
import shutil
import tempfile
import unittest
from pathlib import Path

from all_auto.active_handoff_pointer import (
    ActiveHandoffPointerError,
    git_blob_sha1,
    load_active_handoff_pointer,
)

ROOT = Path(__file__).resolve().parents[1]
POINTER_PATH = "ops/active_e2e_handoff_pointer_v1.json"


class ActiveHandoffPointerV1Tests(unittest.TestCase):
    def test_git_blob_sha_is_stable_across_windows_crlf_checkout(self):
        self.assertEqual(git_blob_sha1(b"one\ntwo\n"), git_blob_sha1(b"one\r\ntwo\r\n"))

    def _copy_pointer_snapshot(self, destination: Path) -> None:
        pointer = json.loads((ROOT / POINTER_PATH).read_text(encoding="utf-8"))
        overlay_path = pointer["active_snapshot"]["overlay"]["path"]
        queue_path = pointer["active_snapshot"]["queue"]["path"]
        for relative in (POINTER_PATH, overlay_path, queue_path):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)

    def test_verified_overlay_wins_over_stale_canonical_embedded_pointer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_pointer_snapshot(root)

            # The canonical ledger is deliberately absent from this consumer fixture.
            self.assertFalse((root / "ops" / "active_e2e_handoff.json").exists())
            snapshot = load_active_handoff_pointer(root)

            self.assertEqual(
                snapshot["overlay_path"],
                "ops/active_e2e_handoff_overlay_20261128_1440.json",
            )
            self.assertEqual(
                snapshot["overlay"]["pr165"]["head_sha"],
                "07cb543816c7432edcf45465ae0763e16917aecc",
            )
            self.assertEqual(
                snapshot["pointer"]["legacy_embedded_pointer"]["recorded_pr165_head_sha"],
                "380d4818330688f47d3558217ed556868cf0b744",
            )
            self.assertEqual(
                snapshot["pointer"]["selection_policy"],
                "VERIFIED_POINTER_REFERENCED_OVERLAY_ONLY",
            )
            self.assertEqual(
                snapshot["overlay"]["canonical_ledger_reconciliation"]["full_content_read_status"],
                "READABLE_BY_FETCH_BLOB",
            )
            self.assertEqual(
                snapshot["pointer"]["canonical_ledger"]["fetch_blob_status"],
                "READABLE",
            )
            self.assertEqual(
                snapshot["overlay"]["request_artifact_local_rehash"]["focus_session_desk"]["local_sha256"],
                "8f1862039297711a68bc33e8e25bea8cfc85f9926b269f0b2136bfa9986b503a",
            )
            self.assertTrue(
                snapshot["overlay"]["request_artifact_local_rehash"]["focus_session_desk"]["digest_match"]
            )
            self.assertFalse(
                snapshot["overlay"]["request_artifact_local_rehash"]["focus_session_desk"]["package_msix_present"]
            )

    def test_latest_overlay_records_current_app_lane_reconciliation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_pointer_snapshot(root)
            snapshot = load_active_handoff_pointer(root)

            self.assertEqual(
                snapshot["overlay"]["pr126_source_pin"]["status"],
                "STALE_SOURCE_PIN",
            )
            self.assertEqual(
                snapshot["overlay"]["products"]["focus_session_desk"]["current_request"]["request_id"],
                "app-focus-session-desk-b6b69464a9c7",
            )
            self.assertTrue(
                snapshot["overlay"]["products"]["file_integrity_ledger"]["functional_hold"]
            )
            self.assertEqual(
                snapshot["overlay"]["products"]["us_freelance_ledger"]["current_source"]["pr"],
                140,
            )
            self.assertEqual(
                snapshot["queue"]["priority"][0]["product"],
                "Focus Session Desk",
            )
            self.assertEqual(
                snapshot["queue"]["priority"][1]["product"],
                "File Integrity Ledger",
            )
            self.assertEqual(
                snapshot["overlay"]["request_artifact_local_rehash"]["file_integrity_ledger"]["local_sha256"],
                "697528b3b0769e3962eebfa0efcdcb026618cd378d97fc60c4f234017882527e",
            )
            self.assertTrue(
                snapshot["overlay"]["request_artifact_local_rehash"]["file_integrity_ledger"]["digest_match"]
            )
            self.assertFalse(
                snapshot["overlay"]["request_artifact_local_rehash"]["file_integrity_ledger"]["package_msix_present"]
            )
            self.assertEqual(
                snapshot["overlay"]["local_code_sync"]["status"],
                "NOT_OBSERVED__CLOUD_PASS_ONLY",
            )

    def test_tampered_overlay_fails_closed_without_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_pointer_snapshot(root)
            pointer = json.loads((root / POINTER_PATH).read_text(encoding="utf-8"))
            overlay_path = root / pointer["active_snapshot"]["overlay"]["path"]
            overlay_path.write_text('{"tampered":true}', encoding="utf-8")

            with self.assertRaises(ActiveHandoffPointerError):
                load_active_handoff_pointer(root)

    def test_tampered_queue_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_pointer_snapshot(root)
            pointer = json.loads((root / POINTER_PATH).read_text(encoding="utf-8"))
            queue_path = root / pointer["active_snapshot"]["queue"]["path"]
            queue_path.write_text('{"tampered":true}', encoding="utf-8")

            with self.assertRaises(ActiveHandoffPointerError):
                load_active_handoff_pointer(root)

    def test_missing_overlay_does_not_fall_back_to_canonical_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_pointer_snapshot(root)
            pointer = json.loads((root / POINTER_PATH).read_text(encoding="utf-8"))
            (root / pointer["active_snapshot"]["overlay"]["path"]).unlink()

            with self.assertRaises(ActiveHandoffPointerError):
                load_active_handoff_pointer(root)

    def test_pointer_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._copy_pointer_snapshot(root)
            pointer = json.loads((root / POINTER_PATH).read_text(encoding="utf-8"))
            pointer["active_snapshot"]["overlay"]["path"] = "../active_e2e_handoff.json"
            (root / POINTER_PATH).write_text(json.dumps(pointer), encoding="utf-8")

            with self.assertRaises(ActiveHandoffPointerError):
                load_active_handoff_pointer(root)


if __name__ == "__main__":
    unittest.main()
