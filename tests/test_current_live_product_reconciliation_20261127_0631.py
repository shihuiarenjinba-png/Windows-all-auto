"""Current live product and PR165 reconciliation snapshot for 2026-11-27 06:31 JST."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261127_0631.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261127_0631.json"


class CurrentLiveProductReconciliation20261127Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_pr165_actual_head_ci_and_canonical_ledger_mismatch_are_explicit(self):
        o = self.overlay
        p = o["pr165"]
        self.assertEqual(p["head_sha_at_observation"], "84f9a3480e2df93f0d75bddc29fb8de47e4ec941")
        self.assertEqual(p["parent_sha"], "64a57e24a377c33904749fd6deac5d14655ea6d5")
        self.assertEqual(p["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in p["exact_head_ci"]],
                         [45833181073, 45833181013, 45833180930])
        self.assertTrue(all(x["head_sha"] == p["head_sha_at_observation"]
                            and x["conclusion"] == "success" for x in p["exact_head_ci"]))
        ledger = o["canonical_ledger_reconciliation"]
        self.assertEqual(ledger["recorded_pr165_current_branch_head_sha"],
                         "86b6aa06205010c8ad90f16a3de52dbe6dc9fe23")
        self.assertEqual(ledger["actual_pr165_head_sha"], p["head_sha_at_observation"])
        self.assertIs(ledger["mismatch"], True)
        self.assertIn("append-only overlay", ledger["resolution"])
        self.assertEqual(o["status"], "HOLD")
        self.assertIs(o["e2e_pass"], False)

    def test_pr161_pr171_and_automator_pin_are_read_only_verified(self):
        o = self.overlay
        self.assertEqual(o["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual([x["run_id"] for x in o["pr161"]["exact_head_ci"]],
                         [42712757936, 43403424936])
        self.assertTrue(all(x["conclusion"] == "success" for x in o["pr161"]["exact_head_ci"]))
        self.assertEqual(o["pr171"]["head_sha"], "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual([x["run_id"] for x in o["pr171"]["exact_head_ci"]],
                         [44437197470, 44437190317])
        self.assertTrue(all(x["conclusion"] == "success" for x in o["pr171"]["exact_head_ci"]))
        self.assertTrue(o["pr171"]["store_upload_bridge_present"])
        pin = o["pr171"]["windows_automator_pin"]
        self.assertEqual(pin["commit_sha"], "d3b8ed4ae7762a69d3fe2a90b64aa86ee938259b")
        self.assertEqual(pin["exact_commit_ci_run_id"], 44319200630)
        self.assertEqual(pin["conclusion"], "success")
        self.assertEqual(o["pr171"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(o["pr171"]["dry_run_started"])
        self.assertFalse(o["pr171"]["live_started"])

    def test_focus_current_source_does_not_reuse_historical_identity_or_request(self):
        f = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(f["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(f["identity"]["historical_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(f["identity"]["expected_head_sha"], f["identity"]["source_sha"])
        self.assertEqual(f["identity"]["package_version_gate"], "HOLD")
        self.assertFalse(f["identity"]["package_version_field_present"])
        self.assertFalse(f["identity"]["current_source_reuse_allowed"])
        request = f["current_source_request"]
        self.assertEqual(request["source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertFalse(request["source_matches_current_pr_head"])
        self.assertEqual(request["status"], "DRY_RUN")
        self.assertFalse(request["request_submitted"])
        self.assertFalse(request["partner_center_write"])
        self.assertFalse(request["identity_write"])
        self.assertFalse(request["msix_build"])
        gui = f["latest_native_windows_gui"]
        self.assertEqual(gui["head_sha"], f["current_source_sha"])
        self.assertEqual(gui["run_id"], 45895951025)
        self.assertEqual(gui["artifact_id"], 15153413358)
        self.assertEqual(gui["exe_sha256"], "d473931ecfc7e08910e5a682768f2c61360481534a9c30661e17c8856732208d")
        self.assertTrue(gui["human_visual_review_required"])
        self.assertEqual(gui["owner_visual_signoff_status"], "PENDING")
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])
        self.assertEqual(f["store_assets"]["owner"], "00")
        self.assertEqual(f["product_quality_score"], 54)

    def test_file_current_source_has_no_approved_identity_and_no_msix(self):
        f = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(f["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertFalse(f["identity"]["current_source_approved_identity_present"])
        self.assertEqual(f["identity"]["historical_identity_source_sha"],
                         "d1108d12f7d1697af30400f97c7db39cba5e6791")
        self.assertFalse(f["identity"]["current_source_reuse_allowed"])
        request = f["current_source_request"]
        self.assertEqual(request["source_sha"], f["current_source_sha"])
        self.assertEqual(request["status"], "DRY_RUN")
        self.assertEqual(request["official_identity_status"], "UNVERIFIED")
        self.assertFalse(request["request_submitted"])
        self.assertFalse(request["identity_write"])
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])
        export = f["msix_export"]
        self.assertEqual(export["status"], "SKIPPED_NO_ARTIFACT")
        self.assertEqual(export["build_and_export_steps"], "SKIPPED")
        self.assertIn("approved Identity absent", export["exact_gate_output"])
        self.assertEqual(f["latest_native_windows_gui"]["run_id"], 45422895435)
        self.assertEqual(f["latest_native_windows_gui"]["human_visual_review_status"], "PASS")

    def test_first_unconnected_interval_is_before_real_msix_and_downstream_stays_false(self):
        o = self.overlay
        self.assertEqual(o["first_unconnected_interval"]["status"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        self.assertFalse(o["transport_contract"]["real_product_msix_received"])
        self.assertEqual(o["transport_contract"]["status"], "IMPLEMENTED_FAIL_CLOSED__EXACT_HEAD_CI_PASS")
        self.assertFalse(o["products"]["focus_session_desk"]["github_backlog_receipt"])
        self.assertFalse(o["products"]["focus_session_desk"]["local_pull_receipt"])
        self.assertFalse(o["products"]["focus_session_desk"]["windows_checker_receipt"])
        self.assertFalse(o["products"]["file_integrity_ledger"]["github_backlog_receipt"])
        self.assertFalse(o["products"]["file_integrity_ledger"]["local_pull_receipt"])
        self.assertFalse(o["products"]["file_integrity_ledger"]["windows_checker_receipt"])
        self.assertEqual(o["local_code_sync_receipt_status"], "NOT_OBSERVED__CLOUD_PASS_ONLY")
        self.assertEqual(o["partner_center"]["version_inferred"], False)

    def test_new_completion_queue_preserves_existing_product_only_and_store_safety(self):
        q = self.queue
        self.assertFalse(q["new_product_generation_allowed"])
        self.assertEqual([x["product"] for x in q["priority"]],
                         ["Focus Session Desk", "File Integrity Ledger", "Prism Route 3D", "Signal Sprint"])
        self.assertEqual(q["priority"][0]["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(q["priority"][1]["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(q["status"], "HOLD")
        self.assertIs(q["e2e_pass"], False)
        self.assertEqual(q["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(q["store_upload_test_eligibility"]["dry_run_started"])
        self.assertFalse(q["store_submission_allowed"])
        self.assertFalse(q["certification_allowed"])
        self.assertFalse(q["publish_allowed"])


if __name__ == "__main__":
    unittest.main()
