"""Regression for the 2026-11-27 09:34 JST append-only E2E ledger refresh."""
import json
import unittest
from pathlib import Path


class ActiveE2ELedgerRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.data = json.loads(
            (root / "ops" / "active_e2e_handoff_overlay_20261127_0934.json")
            .read_text(encoding="utf-8")
        )

    def test_canonical_ledger_is_read_by_blob_and_stale_heads_are_explicit(self):
        ledger = self.data["canonical_ledger"]
        self.assertEqual(ledger["blob_sha"],
                         "5e764d88bcc7d5f101557dfb547cfab48d7d5145")
        self.assertEqual(ledger["full_content_read_status"],
                         "READABLE_VIA_GITHUB_FETCH_BLOB")
        self.assertEqual(ledger["e2e_status"], "HOLD")
        self.assertIs(ledger["e2e_pass"], False)
        self.assertEqual(ledger["pr165_actual_head_sha"],
                         "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertIs(ledger["pr165_pointer_mismatch"], True)

    def test_pr205_and_pr165_exact_head_ci_are_repository_only(self):
        observed = self.data["observation_basis"]
        self.assertEqual(observed["pr205_head_before_this_append"],
                         "bc3bb641dbf67e9ed5db0788d01e50f1e376fb07")
        self.assertTrue(all(
            run["conclusion"] == "success"
            and run["head_sha"] == observed["pr205_head_before_this_append"]
            for run in observed["exact_head_ci"]
        ))
        pr165 = self.data["verified_current_heads"]["pr165"]
        self.assertEqual(pr165["head_sha"],
                         "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertTrue(all(run["conclusion"] == "success"
                            for run in pr165["exact_head_ci"]))
        self.assertEqual(pr165["product_e2e_status"], "HOLD")

    def test_focus_historical_identity_and_request_cannot_be_reused(self):
        focus = self.data["products"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"],
                         "b6b69464a9c7450489338bc7542fd22cf190ed42")
        identity = focus["identity"]
        self.assertEqual(identity["source_sha"],
                         "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(identity["binding_status"], "STALE_TRACKED")
        self.assertFalse(identity["current_source_reuse_allowed"])
        request = focus["current_source_request"]
        self.assertFalse(request["observed"])
        self.assertFalse(request["prior_request_is_current"])
        self.assertIsNone(focus["package_version"])
        self.assertIs(focus["real_msix"], False)

    def test_file_identity_and_version_are_not_substituted_by_dry_run(self):
        product = self.data["products"]["file_integrity_ledger"]
        self.assertFalse(product["identity"]["present_on_current_source"])
        self.assertFalse(product["identity"]["current_source_reuse_allowed"])
        request = product["current_source_request"]
        self.assertEqual(request["status"], "DRY_RUN")
        self.assertEqual(request["official_identity_status"], "UNVERIFIED")
        self.assertIsNone(request["package_version"])
        self.assertIsNone(product["package_version"])
        self.assertIs(product["real_msix"], False)
        self.assertEqual(product["latest_native_windows_gui"]["owner_visual_signoff"],
                         "PASS")

    def test_prism_current_source_is_distinct_from_qa_tool_and_old_identity(self):
        prism = self.data["products"]["prism_route_3d"]
        self.assertEqual(prism["current_source_sha"],
                         "b03ce7b16c3f75c04fe20fdda224c45849eeba0d")
        self.assertEqual(prism["tooling_commit_4c22875c"]["changed_files"],
                         ["tools/prism_revision_package_binding.py"])
        self.assertFalse(prism["tooling_commit_4c22875c"]["product_source"])
        self.assertEqual(prism["historical_identity"]["source_sha"],
                         "15fdcb52e46e35e6de8e87c55af99719c21e09b9")
        self.assertFalse(prism["historical_identity"]["old_identity_reuse_allowed"])
        self.assertIsNone(prism["package_version"])
        self.assertEqual(prism["physical_windows_qa"]["sessions_completed"], 0)

    def test_no_version_inference_or_store_write_is_allowed(self):
        authority = self.data["version_authority"]
        self.assertEqual(authority["version_source"],
                         "products/<slug>/store/approved-identity.json::version")
        self.assertFalse(authority["authoritative_version_found"])
        self.assertFalse(authority["version_inferred"])
        safety = self.data["safety"]
        self.assertFalse(safety["live_partner_center_write_allowed"])
        self.assertFalse(safety["store_submission_allowed"])
        self.assertFalse(safety["certification_allowed"])
        self.assertFalse(safety["publish_allowed"])
        self.assertFalse(safety["merge_allowed"])
        self.assertFalse(safety["force_push_allowed"])

    def test_no_product_e2e_or_local_receipt_is_claimed(self):
        transport = self.data["transport"]
        self.assertTrue(transport["pr165_exact_head_ci_pass"])
        self.assertFalse(transport["real_product_msix_received"])
        self.assertFalse(transport["github_backlog_receipt"])
        self.assertFalse(transport["local_pull_receipt"])
        self.assertFalse(transport["windows_checker_receipt"])
        self.assertFalse(transport["local_gui_install_receipt"])
        self.assertFalse(transport["product_e2e_pass"])
        self.assertEqual(transport["local_code_sync_receipt"],
                         "NOT_OBSERVED__CLOUD_PASS_ONLY")
        self.assertEqual(self.data["store_upload_test"]["eligible_fresh_unsold_products"], 0)


if __name__ == "__main__":
    unittest.main()
