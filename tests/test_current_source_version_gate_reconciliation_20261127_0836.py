"""Regression for the 2026-11-27 source-bound Identity/Version HOLD overlay."""
import json
import unittest
from pathlib import Path


class CurrentSourceVersionGateReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.overlay = json.loads(
            (root / "ops" / "active_e2e_handoff_overlay_20261127_0836.json")
            .read_text(encoding="utf-8")
        )

    def test_focus_historical_identity_is_tracked_stale_and_versionless(self):
        focus = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"],
                         "b6b69464a9c7450489338bc7542fd22cf190ed42")
        identity = focus["identity"]
        self.assertTrue(identity["file_present_on_current_source"])
        self.assertTrue(identity["file_tracked_in_source"])
        self.assertEqual(identity["source_sha"],
                         "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(identity["identity_binding_status"], "STALE_TRACKED")
        self.assertEqual(identity["version_status"], "MISSING")
        self.assertFalse(identity["current_source_reuse_allowed"])
        request = focus["current_source_request"]
        self.assertFalse(request["source_matches_current_pr_head"])
        self.assertFalse(request["current_head_request_observed"])
        self.assertEqual(request["current_head_request_expected_id"],
                         "app-focus-session-desk-b6b69464a9c7")
        self.assertIsNone(focus["package_version"])
        self.assertIs(focus["real_msix"], False)

    def test_file_current_source_request_does_not_substitute_for_identity(self):
        file_product = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(file_product["current_source_sha"],
                         "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertFalse(file_product["identity"]["file_present_on_current_source"])
        self.assertEqual(file_product["identity"]["identity_binding_status"], "MISSING")
        self.assertEqual(file_product["identity"]["version_status"], "UNAVAILABLE")
        request = file_product["current_source_request"]
        self.assertEqual(request["source_sha"], file_product["current_source_sha"])
        self.assertEqual(request["status"], "DRY_RUN")
        self.assertEqual(request["official_identity_status"], "UNVERIFIED")
        self.assertIsNone(request["package_version"])
        self.assertIsNone(file_product["package_version"])
        self.assertIs(file_product["real_msix"], False)

    def test_preflight_evidence_is_scoped_to_the_exact_sources_tested(self):
        preflight = self.overlay["package_source_preflight_evidence"]
        self.assertEqual(preflight["workflow_run_id"], 45828057878)
        self.assertEqual(preflight["artifact_id"], 15120688601)
        self.assertEqual(preflight["focus_source_sha_tested"],
                         "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertFalse(preflight["focus_source_matches_current_pr94_head"])
        self.assertEqual(preflight["file_source_sha_tested"],
                         "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertTrue(preflight["file_source_matches_current_pr115_head"])
        self.assertFalse(preflight["product_makeappx_invoked"])
        self.assertEqual(preflight["fixture_only"]["scope"],
                         "QA_FIXTURE_ONLY_NOT_PRODUCT")

    def test_authoritative_version_contract_is_not_an_inferred_build_setting(self):
        authority = self.overlay["package_version_authority"]
        self.assertEqual(authority["version_source"],
                         "products/<slug>/store/approved-identity.json::version")
        self.assertEqual(authority["required_source_binding_fields"],
                         ["source_sha", "verified_source_sha", "expected_head_sha"])
        self.assertTrue(authority["operator_identity_return_must_be_untracked"])
        self.assertFalse(authority["version_inferred"])
        self.assertEqual(authority["conclusion"],
                         "NO_AUTHORITATIVE_PACKAGE_VERSION_FOUND__KEEP_VERSION_HOLD")

    def test_transport_ci_does_not_promote_product_e2e_or_store_authority(self):
        transport = self.overlay["transport_contract"]
        self.assertTrue(transport["pr165_exact_head_ci_pass"])
        self.assertFalse(transport["real_product_msix_received"])
        self.assertFalse(transport["github_backlog_receipt"])
        self.assertFalse(transport["local_pull_receipt"])
        self.assertFalse(transport["local_checker_receipt"])
        self.assertFalse(transport["local_gui_install_receipt"])
        self.assertFalse(transport["product_e2e_pass"])
        self.assertFalse(self.overlay["safety"]["store_submission_allowed"])
        self.assertFalse(self.overlay["safety"]["certification_allowed"])
        self.assertFalse(self.overlay["safety"]["publish_allowed"])
        self.assertFalse(self.overlay["safety"]["merge_allowed"])


if __name__ == "__main__":
    unittest.main()
