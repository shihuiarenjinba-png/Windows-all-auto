import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261127_1334.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261127_1334.json"


class CurrentLiveProductReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_pr165_exact_head_and_parent_are_pinned(self):
        pr = self.overlay["pr165"]
        self.assertEqual(pr["head_sha"], "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertEqual(pr["parent_sha"], "6afe5ec89a440880066bee43a61f596a5939761d")
        self.assertEqual(pr["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual({r["run_id"] for r in pr["exact_head_ci"]},
                         {45899687437, 45899687528, 45899687545})
        self.assertTrue(all(r["head_sha"] == pr["head_sha"] and r["conclusion"] == "success"
                            for r in pr["exact_head_ci"]))

    def test_pr197_is_exactly_stacked_on_current_pr165_and_all_runs_pass(self):
        pr = self.overlay["pr197"]
        self.assertEqual(pr["base_pr165_head_sha"], self.overlay["pr165"]["head_sha"])
        self.assertEqual(pr["head_sha"], "84943837bd731025c59ec230853269f9910ff5e0")
        self.assertEqual(pr["parent_sha"], "7d79d2e2f2a5bcca31f5c95dfbb82047b53eefd1")
        self.assertEqual(pr["compare_to_pr165"], {
            "status": "ahead", "ahead_by": 17, "behind_by": 0, "total_commits": 17,
            "base_sha": "07cb543816c7432edcf45465ae0763e16917aecc"
        })
        self.assertEqual(pr["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual({r["run_id"] for r in pr["exact_head_ci"]},
                         {45930764607, 45930765188, 45930764640})
        self.assertTrue(all(r["head_sha"] == pr["head_sha"] and r["conclusion"] == "success"
                            for r in pr["exact_head_ci"]))
        self.assertFalse(pr["product_code_changed"])

    def test_pr161_and_pr171_live_heads_remain_pinned(self):
        self.assertEqual(self.overlay["pr161"]["head_sha"],
                         "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(self.overlay["pr171"]["head_sha"],
                         "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(self.overlay["pr161"]["exact_head_ci"][0]["run_id"], 42712757936)
        self.assertEqual(self.overlay["pr171"]["exact_head_ci"][0]["run_id"], 44437197470)
        self.assertEqual(self.overlay["pr171"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.overlay["pr171"]["dry_run_started"])
        self.assertFalse(self.overlay["pr171"]["live_started"])

    def test_focus_current_request_is_exact_source_dry_run_not_identity_return(self):
        focus = self.overlay["products"]["focus_session_desk"]
        request = focus["current_source_request"]
        self.assertEqual(focus["current_source_sha"],
                         "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(request["source_sha"], focus["current_source_sha"])
        self.assertEqual(request["request_id"], "app-focus-session-desk-b6b69464a9c7")
        self.assertEqual(request["workflow_run_id"], 45925933012)
        self.assertEqual(request["artifact_id"], 15166202971)
        self.assertEqual(request["artifact_sha256"],
                         "8f1862039297711a68bc33e8e25bea8cfc85f9926b269f0b2136bfa9986b503a")
        self.assertEqual(request["request_status"], "DRY_RUN")
        self.assertFalse(request["request_submitted"])
        self.assertFalse(request["partner_center_write"])
        self.assertFalse(request["identity_write"])
        self.assertFalse(request["msix_build"])
        self.assertEqual(focus["identity"]["historical_source_sha"],
                         "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertFalse(focus["identity"]["current_source_reuse_allowed"])
        self.assertIsNone(focus["package_version"])
        self.assertEqual(focus["state"], "WAITING_USER_IDENTITY")

    def test_file_integrity_current_identity_is_absent_and_request_is_source_bound(self):
        file = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(file["current_source_sha"],
                         "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertFalse(file["identity"]["current_source_approved_identity_present"])
        self.assertEqual(file["identity"]["historical_identity_source_sha"],
                         "d1108d12f7d1697af30400f97c7db39cba5e6791")
        self.assertFalse(file["identity"]["current_source_reuse_allowed"])
        self.assertEqual(file["current_source_request"]["source_sha"], file["current_source_sha"])
        self.assertEqual(file["current_source_request"]["request_id"],
                         "app-file-integrity-ledger-33d612be2774")
        self.assertIsNone(file["package_version"])
        self.assertEqual(file["state"], "WAITING_USER_IDENTITY")

    def test_partner_center_context_unavailable_does_not_infer_sign_in_state(self):
        readback = self.overlay["partner_center_readback"]
        self.assertEqual(readback["status"],
                         "NOT_OBSERVED__ORIGINATING_BROWSER_CONTEXT_UNAVAILABLE")
        self.assertEqual(readback["sign_in_state"], "NOT_DETERMINED")
        self.assertEqual(readback["identity_acquisition_owner"], "USER")
        self.assertFalse(readback["request_submitted"])
        self.assertFalse(readback["partner_center_write"])
        self.assertFalse(readback["identity_write"])

    def test_canonical_ledger_is_read_but_not_rewritten_and_stale_pointer_is_disclosed(self):
        ledger = self.overlay["canonical_ledger_reconciliation"]
        self.assertEqual(ledger["full_content_read_status"], "READABLE_VIA_GIT_BLOB")
        self.assertEqual(ledger["blob_sha"], "5e764d88bcc7d5f101557dfb547cfab48d7d5145")
        self.assertTrue(ledger["mismatch"])
        self.assertTrue(ledger["active_product_is_historical"])
        self.assertEqual(ledger["historical_active_product"]["source_sha"],
                         "c058cbf7fe38e02d929c67d047d717ff74bd522e")
        self.assertFalse(ledger["rewritten"])

    def test_transport_code_is_ready_but_no_real_product_has_entered_it(self):
        readiness = self.overlay["transport_readiness"]
        self.assertEqual(readiness["github_artifact_custody"], "IMPLEMENTED_AND_EXACT_HEAD_CI_PASS")
        self.assertEqual(readiness["local_pull"], "IMPLEMENTED_NOT_EXECUTED_WITH_REAL_PRODUCT_MSIX")
        self.assertEqual(readiness["local_checker"],
                         "FAIL_CLOSED_LOCAL_CUSTODY_RECEIPT_GATE_IMPLEMENTED_AND_EXACT_HEAD_CI_PASS")
        self.assertEqual(readiness["product_e2e"], "HOLD")
        self.assertFalse(self.overlay["products"]["focus_session_desk"]["real_msix"])
        self.assertFalse(self.overlay["products"]["file_integrity_ledger"]["real_msix"])
        self.assertFalse(self.overlay["products"]["focus_session_desk"]["github_backlog_receipt"])
        self.assertFalse(self.overlay["products"]["file_integrity_ledger"]["local_pull_receipt"])

    def test_local_code_sync_is_not_promoted_from_cloud_only_evidence(self):
        sync = self.overlay["local_code_sync"]
        self.assertEqual(sync["status"], "NOT_OBSERVED__CLOUD_PASS_ONLY")
        self.assertFalse(sync["local_code_sync_pass"])
        self.assertTrue(sync["cloud_results_must_not_be_promoted_to_local_pass"])
        self.assertEqual(sync["first_run_receipt"], "NOT_OBSERVED")
        self.assertEqual(sync["idempotent_replay_receipt"], "NOT_OBSERVED")
        self.assertEqual(sync["scheduled_task_receipt"], "NOT_OBSERVED")

    def test_queue_preserves_existing_product_priority_and_all_store_gates_closed(self):
        self.assertEqual([item["product"] for item in self.queue["priority"]],
                         ["Focus Session Desk", "File Integrity Ledger", "Prism Route 3D", "Signal Sprint"])
        self.assertFalse(self.queue["new_product_generation_allowed"])
        self.assertEqual(self.queue["priority"][0]["state"], "WAITING_USER_IDENTITY")
        self.assertEqual(self.queue["priority"][1]["state"], "WAITING_USER_IDENTITY")
        self.assertEqual(self.queue["first_unconnected_interval"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        self.assertFalse(self.queue["e2e_pass"])
        self.assertFalse(self.queue["real_msix"])
        self.assertFalse(self.queue["github_backlog_receipt"])
        self.assertFalse(self.queue["local_pull_receipt"])
        self.assertFalse(self.queue["local_checker_receipt"])
        self.assertFalse(self.queue["local_gui_install_receipt"])
        self.assertFalse(self.queue["store_submission_allowed"])
        self.assertFalse(self.queue["certification_allowed"])
        self.assertFalse(self.queue["publish_allowed"])
        self.assertEqual(self.queue["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.queue["store_upload_test_eligibility"]["dry_run_started"])
        self.assertFalse(self.queue["store_upload_test_eligibility"]["live_started"])


if __name__ == "__main__":
    unittest.main()
