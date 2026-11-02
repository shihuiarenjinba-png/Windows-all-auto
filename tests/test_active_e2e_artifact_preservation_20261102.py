"""Read-only central-ledger regression: byte custody is not Store/E2E approval.

The actual ZIP bytes were independently downloaded, SHA256 verified and
read back from persistent Library by the 36 lane. This fixture checks that
the non-secret ledger receipt remains pinned and never promotes downstream
gates. CI does not have the Library binaries and does not rehash them.
"""
import json
from pathlib import Path
import unittest

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
ARCHIVES = {
    12807496604: ("focus-session-desk",
                  "06189361745a9cc175f1fe5bde27d758b71518ac1d2e955436939e3e7ed2a04d",
                  "04b2d7e4eae215855217285f07f8835ffe3cf60dc5aab24ede141d28f563416d"),
    12815845218: ("offline-text-diff-desk",
                  "cfbbb12690915b2ac0d8be0bfa690ea347e6912f7737bf64473140f125ed937b",
                  "1a0e4f61dfab52e2cac7317bc28bb4ff34b6aa477974e0430ff360d7e2b4381e"),
    12826068537: ("file-integrity-ledger",
                  "c4c1f299318cf182d3d04773284990e55e270c25de28f4b8eb3baf7895548b88",
                  "9100bbcfba20ed2768e5d2dffcb39c987466377d26a34af1e03cc166071e02ca"),
}


class ArtifactPreservationLedgerRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.revision = cls.data["revision_review_reconciliation"]

    def test_three_real_preidentity_zip_archives_preserved_but_not_msix(self):
        evidence = self.revision["artifact_byte_preservation_20261102"]
        self.assertEqual(evidence["zip_archives_preserved"], 3)
        self.assertEqual(evidence["zip_archives_sha256_readback_verified"], 3)
        self.assertEqual(evidence["zip_crc_pass"], 3)
        self.assertEqual(evidence["embedded_exe_receipt_sha256_pass"], 3)
        self.assertEqual(evidence["storage"], "PERSISTENT_CHATGPT_LIBRARY_NOT_GITHUB_QA_BACKLOG")
        self.assertTrue(evidence["receipt_library_path"].endswith(".json"))
        actual = {item["artifact_id"]: item for item in evidence["records"]}
        self.assertEqual(set(actual), set(ARCHIVES))
        for aid, (slug, zip_sha, exe_sha) in ARCHIVES.items():
            item = actual[aid]
            self.assertEqual((item["slug"], item["archive_sha256"], item["exe_sha256"]),
                             (slug, zip_sha, exe_sha))
            self.assertTrue(item["archive_download_verified"])
            self.assertTrue(item["library_upload_succeeded"])
            self.assertTrue(item["library_readback_sha256_verified"])
            self.assertEqual(item["package_kind"], "PRE_IDENTITY_UNSIGNED_EXE_NOT_MSIX")
            self.assertIn(str(aid), item["library_path"])
        for key in ("real_msix_pass", "github_qa_backlog_pass", "local_pull_pass",
                    "checker_pass", "gui_qa_pass"):
            self.assertFalse(evidence[key])
        self.assertEqual(evidence["store_submission"], "NOT_PERFORMED")
        self.assertTrue(self.revision["cross_lane_gates"]["pre_identity_archive_library_preservation_pass"])

    def test_game_independent_bytes_and_live_check_only_do_not_release_cas(self):
        game = self.revision["observations"]["signal-sprint-new-lineage"]
        self.assertEqual(game["new_artifact_id"], 13105352227)
        self.assertEqual(game["new_artifact_wrapper_sha256"],
                         "843496682662e871fc6e1b5df83ace2c6b01ef314cfc466b5072290890b70a8f")
        self.assertEqual(game["inner_new_lineage_zip_sha256"],
                         "46aff1ee7570459235c9e7ca7fb1faf6f494dc8100e62b6e132c6d07a6291b71")
        self.assertEqual(game["contained_exe_sha256"],
                         "beb683b61b4fa4b2ec90fe1d413363c8a535bd4cb72b41b54b03a9685f516ee0")
        self.assertTrue(game["exact_new_artifact_bytes_rehashed_by_36"])
        self.assertEqual(game["provisioner_validator_ci_run_id"], 41371345733)
        self.assertEqual(game["provisioner_live_check_only_run_id"], 41371299063)
        self.assertIn("LIVE_CHECK_ONLY_PASS", game["provisioner_validator_compatibility"])
        self.assertIn("CAS_HOLD", game["provisioner_validator_compatibility"])
        self.assertIn("EXPIRED_404", game["old_artifact_status"])
        self.assertFalse(game["new_lineage_cas_applied"])
        self.assertFalse(game["gdk_msixvc_built"])
        self.assertFalse(game["approved_package_version"])

    def test_three_d_qa_new_head_and_batch_cursor_remain_separate(self):
        three_d = self.revision["observations"]["prism-route-3d-sentinel"]
        qa = three_d["independent_3d_qa_pr6"]
        self.assertEqual(qa["review_head_sha"], "4b58f9d3c2ff75be9627f3e8a4dd20194460111d")
        self.assertEqual(qa["ci_run_id"], 41377481988)
        self.assertFalse(qa["new_sentinel_cas_applied"])
        self.assertEqual(qa["real_signed_msix"], "NOT_BUILT")
        batch = self.data["multi_product_partner_center_batch_4"]
        self.assertEqual(batch["cloud_verified_return_count"], 2)
        self.assertEqual(batch["remaining_pre_identity_count"], 2)
        self.assertEqual(batch["local_batch_discovered_count"], 0)
        self.assertEqual(batch["processed_count"], 0)
        self.assertEqual(batch["next_resume_index"], 3)
        self.assertIn("NOT_LOCAL_PROCESSED_COUNT", batch["next_resume_index_semantics"])
        self.assertEqual(batch["trigger_proof"], "BATCH_SCHEDULE_TRIGGER_NOT_PROVEN")
        self.assertFalse(self.data["e2e_pass"])


if __name__ == "__main__":
    unittest.main()
