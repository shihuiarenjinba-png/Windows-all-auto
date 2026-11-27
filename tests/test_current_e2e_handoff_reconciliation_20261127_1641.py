import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261127_1641.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261127_1641.json"


class CurrentE2EReconciliation1641Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_pr165_live_head_and_exact_head_ci_are_pinned(self):
        pr = self.overlay["pr165"]
        self.assertEqual(pr["head_sha"], "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertEqual(pr["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual({item["run_id"] for item in pr["exact_head_ci"]},
                         {45899687437, 45899687528, 45899687545})
        self.assertTrue(all(item["head_sha"] == pr["head_sha"] and item["conclusion"] == "success"
                            for item in pr["exact_head_ci"]))

    def test_pr161_and_pr171_current_heads_remain_exact(self):
        self.assertEqual(self.overlay["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(self.overlay["pr171"]["head_sha"], "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(self.overlay["pr161"]["exact_head_ci"][0]["run_id"], 42712757936)
        self.assertEqual(self.overlay["pr171"]["exact_head_ci"][0]["run_id"], 44437197470)
        self.assertEqual(self.overlay["pr171"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.overlay["pr171"]["dry_run_started"])
        self.assertFalse(self.overlay["pr171"]["live_started"])

    def test_pr197_is_current_exact_stack_and_all_three_ci_runs_pass(self):
        pr = self.overlay["pr197"]
        self.assertEqual(pr["head_sha"], "1f106f0fffe871bf82a2ae3ceeb04eaa8ab75988")
        self.assertEqual(pr["compare_to_pr165"], {
            "status": "ahead", "ahead_by": 18, "behind_by": 0, "total_commits": 18,
            "base_sha": "07cb543816c7432edcf45465ae0763e16917aecc"
        })
        self.assertEqual({item["run_id"] for item in pr["exact_head_ci"]},
                         {45941584802, 45941584857, 45941584807})
        self.assertTrue(all(item["head_sha"] == pr["head_sha"] and item["conclusion"] == "success"
                            for item in pr["exact_head_ci"]))
        self.assertFalse(pr["product_code_changed"])

    def test_pr213_correction_is_verified_and_selectively_integrated(self):
        pr = self.overlay["pr213"]
        self.assertEqual(pr["head_sha"], "3e1b2b70c73f47bb293e6b003eec5803c249d5d5")
        self.assertEqual(pr["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual({item["run_id"] for item in pr["exact_head_ci"]},
                         {45954196967, 45954196984, 45954196987})
        self.assertTrue(all(item["head_sha"] == pr["head_sha"] and item["conclusion"] == "success"
                            for item in pr["exact_head_ci"]))
        integration = self.overlay["integration_candidate"]
        self.assertEqual(integration["base_pr197_head_sha"], "1f106f0fffe871bf82a2ae3ceeb04eaa8ab75988")
        self.assertEqual(integration["source_pr213_head_sha"], "3e1b2b70c73f47bb293e6b003eec5803c249d5d5")
        self.assertEqual(integration["code_fix_commit_sha"], "28248e289d6eee14a5b2067d54f83d9a49fd1d04")
        self.assertEqual(integration["regression_test_commit_sha"], "c6d149fc29563b268e9ca7b1a15efa529e0e5591")
        self.assertTrue(integration["preserves_pr197_checker_queue_and_local_pull_changes"])

    def test_pr212_remains_sibling_and_its_stale_focus_snapshot_is_superseded(self):
        pr = self.overlay["pr212"]
        self.assertEqual(pr["head_sha"], "78ab0e8717881bdb0a450ba9f6a7804ca280f661")
        self.assertEqual(pr["compare_to_pr197"], {
            "status": "diverged", "ahead_by": 5, "behind_by": 18, "merge_base": "07cb543816c7432edcf45465ae0763e16917aecc"
        })
        self.assertEqual(pr["current_overlay_focus_request"], "STALE_OLD_FB629_REQUEST")
        self.assertFalse(pr["merged"])

    def test_focus_request_is_current_source_dry_run_but_identity_is_historical(self):
        focus = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        request = focus["current_source_request"]
        self.assertEqual(request["request_id"], "app-focus-session-desk-b6b69464a9c7")
        self.assertEqual(request["source_sha"], focus["current_source_sha"])
        self.assertEqual(request["workflow_run_id"], 45925933012)
        self.assertEqual(request["artifact_id"], 15166202971)
        self.assertEqual(request["artifact_sha256"], "8f1862039297711a68bc33e8e25bea8cfc85f9926b269f0b2136bfa9986b503a")
        self.assertEqual(request["request_status"], "DRY_RUN")
        self.assertFalse(request["request_submitted"])
        identity = focus["identity"]["direct_current_source_file_readback"]
        self.assertEqual(identity["identity_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(identity["current_source_sha"], focus["current_source_sha"])
        self.assertFalse(identity["reusable_for_current_source"])
        self.assertIsNone(focus["package_version"])
        self.assertFalse(focus["real_msix"])

    def test_file_integrity_request_matches_source_but_current_identity_is_absent(self):
        product = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(product["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(product["current_source_request"]["source_sha"], product["current_source_sha"])
        self.assertEqual(product["current_source_request"]["request_id"], "app-file-integrity-ledger-33d612be2774")
        self.assertFalse(product["identity"]["current_source_approved_identity_present"])
        self.assertEqual(product["identity"]["direct_current_source_file_readback"]["status"],
                         "NOT_FOUND_404_ON_EXACT_PR115_HEAD")
        self.assertIsNone(product["package_version"])
        self.assertFalse(product["real_msix"])

    def test_canonical_ledger_is_not_claimed_read_or_rewritten_from_empty_fetch(self):
        ledger = self.overlay["canonical_ledger_reconciliation"]
        self.assertEqual(ledger["current_direct_fetch"]["returned_content_chars"], 0)
        self.assertEqual(ledger["full_content_read_status"], "NOT_VERIFIABLE_IN_THIS_RUN")
        self.assertTrue(ledger["stale"])
        self.assertFalse(ledger["rewritten"])

    def test_transport_and_product_e2e_remain_distinct(self):
        self.assertEqual(self.overlay["transport_readiness"]["approved_identity_receipt_trio"],
                         "PATCHED_ON_STACKED_CANDIDATE__EXACT_HEAD_CI_PENDING")
        for key in ("focus_session_desk", "file_integrity_ledger"):
            product = self.overlay["products"][key]
            self.assertFalse(product["real_msix"])
            self.assertFalse(product["github_backlog_receipt"])
            self.assertFalse(product["local_pull_receipt"])
            self.assertFalse(product["windows_checker_receipt"])
            self.assertFalse(product["local_gui_install_receipt"])
            self.assertFalse(product["product_e2e_pass"])
        self.assertFalse(self.overlay["e2e_pass"])

    def test_partner_center_and_local_windows_context_are_not_inferred(self):
        pc = self.overlay["partner_center_readback"]
        self.assertEqual(pc["status"], "NOT_OBSERVED__ORIGINATING_BROWSER_CONTEXT_UNAVAILABLE")
        self.assertEqual(pc["sign_in_state"], "NOT_DETERMINED")
        self.assertFalse(pc["request_submitted"])
        self.assertFalse(pc["partner_center_write"])
        self.assertFalse(pc["identity_write"])
        self.assertEqual(self.overlay["local_code_sync"]["status"], "NOT_OBSERVED__CLOUD_PASS_ONLY")

    def test_queue_order_and_all_live_store_gates_stay_closed(self):
        self.assertEqual([item["product"] for item in self.queue["priority"]],
                         ["Focus Session Desk", "File Integrity Ledger", "Prism Route 3D", "Signal Sprint"])
        self.assertFalse(self.queue["new_product_generation_allowed"])
        self.assertEqual(self.queue["first_unconnected_interval"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        self.assertEqual(self.queue["integration_candidate"]["branch"], "codex/36-pr213-pr197-reconcile-20261127-1641")
        self.assertEqual(self.queue["integration_candidate"]["code_fix_commit_sha"], "28248e289d6eee14a5b2067d54f83d9a49fd1d04")
        self.assertFalse(self.queue["e2e_pass"])
        self.assertFalse(self.queue["real_msix"])
        self.assertFalse(self.queue["github_backlog_receipt"])
        self.assertFalse(self.queue["local_pull_receipt"])
        self.assertFalse(self.queue["local_checker_receipt"])
        self.assertFalse(self.queue["local_gui_install_receipt"])
        self.assertFalse(self.queue["store_submission_allowed"])
        self.assertFalse(self.queue["certification_allowed"])
        self.assertFalse(self.queue["publish_allowed"])
        self.assertFalse(self.queue["merge_allowed"])
        self.assertFalse(self.queue["force_push_allowed"])
        self.assertEqual(self.queue["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.queue["store_upload_test_eligibility"]["dry_run_started"])
        self.assertFalse(self.queue["store_upload_test_eligibility"]["live_started"])


if __name__ == "__main__":
    unittest.main()
