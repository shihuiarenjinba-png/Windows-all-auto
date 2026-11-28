import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261127_1148.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261127_1148.json"


class CurrentLiveProductReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_pr165_head_parent_and_all_exact_head_runs_are_pinned(self):
        pr = self.overlay["pr165"]
        self.assertEqual(pr["head_sha"], "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertEqual(pr["parent_sha"], "6afe5ec89a440880066bee43a61f596a5939761d")
        self.assertEqual(pr["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual({r["run_id"] for r in pr["exact_head_ci"]},
                         {45899687437, 45899687528, 45899687545})
        self.assertTrue(all(r["head_sha"] == pr["head_sha"] and r["conclusion"] == "success"
                            for r in pr["exact_head_ci"]))

    def test_pr161_and_pr171_live_heads_remain_directly_pinned(self):
        self.assertEqual(self.overlay["pr161"]["head_sha"],
                         "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(self.overlay["pr171"]["head_sha"],
                         "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(self.overlay["pr161"]["exact_head_ci"][0]["conclusion"], "success")
        self.assertEqual(self.overlay["pr171"]["exact_head_ci"][0]["conclusion"], "success")
        self.assertEqual(self.overlay["pr171"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.overlay["pr171"]["dry_run_started"])
        self.assertFalse(self.overlay["pr171"]["live_started"])

    def test_pr197_is_selectively_restacked_and_current_branch_head_ci_passed(self):
        pr = self.overlay["pr197"]
        self.assertEqual(pr["base_pr165_head_sha"], self.overlay["pr165"]["head_sha"])
        self.assertEqual(pr["transport_checker_code_head_sha"],
                         "296ed87ba03c99ad3caed9cbdb1e7d1cea922769")
        self.assertEqual(pr["compare_to_pr165"], {"status": "ahead", "ahead_by": 11, "behind_by": 0})
        self.assertEqual(pr["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual({r["run_id"] for r in pr["exact_head_ci"]},
                         {45930103512, 45930103618, 45930103574})
        self.assertTrue(all(r["head_sha"] == pr["transport_checker_code_head_sha"]
                            and r["conclusion"] == "success" for r in pr["exact_head_ci"]))
        latest = pr["latest_verified_branch_head_before_this_append"]
        self.assertEqual(latest["head_sha"], "6869711aa67ff8947eb56dd701cc77677b52ebc7")
        self.assertEqual({r["run_id"] for r in latest["exact_head_ci"]},
                         {45930409211, 45930409203, 45930409223})
        self.assertTrue(all(r["head_sha"] == latest["head_sha"] and r["conclusion"] == "success"
                            for r in latest["exact_head_ci"]))
        self.assertFalse(pr["product_code_changed"])
        self.assertEqual(pr["checker_handoff"],
                         "LOCAL_CUSTODY_RECEIPT_REQUIRED_BEFORE_CHECKER_SUBPROCESS")

    def test_focus_current_source_request_is_now_bound_to_exact_pr94_head(self):
        focus = self.overlay["products"]["focus_session_desk"]
        request = focus["current_source_request"]
        self.assertEqual(focus["current_source_sha"],
                         "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(request["source_sha"], focus["current_source_sha"])
        self.assertEqual(request["request_id"], "app-focus-session-desk-b6b69464a9c7")
        self.assertEqual(request["source_head_verification"], "VERIFIED")
        self.assertEqual(request["request_status"], "DRY_RUN")
        self.assertEqual(request["workflow_run_id"], 45925933012)
        self.assertEqual(request["artifact_id"], 15166202971)
        self.assertEqual(request["artifact_sha256"],
                         "8f1862039297711a68bc33e8e25bea8cfc85f9926b269f0b2136bfa9986b503a")
        self.assertFalse(request["request_submitted"])
        self.assertFalse(request["partner_center_write"])
        self.assertFalse(request["identity_write"])
        self.assertFalse(request["msix_build"])
        self.assertFalse(focus["identity"]["current_source_reuse_allowed"])
        self.assertIsNone(focus["package_version"])
        self.assertEqual(focus["package_version_status"], "AUTHORITATIVE_VALUE_REQUIRED")

    def test_pr134_request_artifact_is_dry_run_not_identity_or_package_approval(self):
        pr = self.overlay["pr134"]
        self.assertEqual(pr["base_product_source_sha"],
                         "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(pr["tooling_head_sha"], "26cf8aa81e1c4ed0775eaae087d7911832b5c90f")
        self.assertEqual(pr["exact_head_workflow_run"]["conclusion"], "success")
        self.assertFalse(pr["request_submitted"])
        self.assertFalse(pr["partner_center_write"])
        self.assertFalse(pr["identity_write"])
        self.assertFalse(pr["msix_build"])
        self.assertEqual(pr["official_identity_status"], "UNVERIFIED")
        self.assertEqual(pr["package_status"], "NOT_BUILT")

    def test_file_integrity_current_source_identity_and_version_remain_held(self):
        file = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(file["current_source_sha"],
                         "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertFalse(file["identity"]["current_source_approved_identity_present"])
        self.assertFalse(file["identity"]["current_source_reuse_allowed"])
        self.assertIsNone(file["package_version"])
        self.assertEqual(file["package_version_status"], "AUTHORITATIVE_VALUE_REQUIRED")

    def test_png_ownership_and_existing_evidence_are_not_overwritten(self):
        focus = self.overlay["products"]["focus_session_desk"]
        file = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(focus["store_assets"]["owner"], "00")
        self.assertEqual(file["store_assets"]["owner"], "00")
        self.assertFalse(focus["store_assets"]["regeneration_or_modification_by_36"])
        self.assertFalse(file["store_assets"]["regeneration_or_modification_by_36"])
        self.assertEqual(focus["store_assets"]["msix_embedding"], "NOT_VERIFIED")
        self.assertEqual(file["store_assets"]["msix_embedding"], "NOT_VERIFIED")

    def test_transport_and_checker_code_do_not_promote_product_e2e(self):
        transport = self.overlay["transport_readiness"]
        self.assertEqual(transport["github_artifact_custody"], "IMPLEMENTED_AND_EXACT_HEAD_CI_PASS")
        self.assertEqual(transport["local_pull"], "IMPLEMENTED_NOT_EXECUTED_WITH_REAL_PRODUCT_MSIX")
        self.assertEqual(transport["local_checker"],
                         "FAIL_CLOSED_LOCAL_CUSTODY_RECEIPT_GATE_IMPLEMENTED_AND_EXACT_HEAD_CI_PASS")
        self.assertFalse(self.overlay["e2e_pass"])
        self.assertFalse(self.overlay["products"]["focus_session_desk"]["real_msix"])
        self.assertFalse(self.overlay["products"]["file_integrity_ledger"]["real_msix"])
        self.assertFalse(self.overlay["products"]["focus_session_desk"]["windows_checker_receipt"])
        self.assertFalse(self.overlay["products"]["file_integrity_ledger"]["windows_checker_receipt"])
        self.assertFalse(self.overlay["products"]["focus_session_desk"]["local_gui_install_receipt"])
        self.assertFalse(self.overlay["products"]["file_integrity_ledger"]["local_gui_install_receipt"])

    def test_canonical_ledger_is_disclosed_as_stale_and_unchanged(self):
        ledger = self.overlay["canonical_ledger_reconciliation"]
        self.assertEqual(ledger["full_content_read_status"], "NOT_READABLE_BY_CURRENT_FETCH")
        self.assertEqual(ledger["current_actual_pr165_head_sha"], self.overlay["pr165"]["head_sha"])
        self.assertTrue(ledger["mismatch"])
        self.assertIn("was not edited", ledger["resolution"])

    def test_queue_keeps_existing_product_order_and_all_store_writes_disabled(self):
        self.assertEqual([x["product"] for x in self.queue["priority"]],
                         ["Focus Session Desk", "File Integrity Ledger", "Prism Route 3D", "Signal Sprint"])
        self.assertFalse(self.queue["new_product_generation_allowed"])
        self.assertEqual(self.queue["priority"][0]["current_request_source_sha"],
                         self.queue["priority"][0]["current_source_sha"])
        self.assertEqual(self.queue["priority"][0]["current_request_status"],
                         "DRY_RUN__SOURCE_BOUND_TO_CURRENT_HEAD")
        self.assertEqual(self.queue["first_unconnected_interval"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        self.assertFalse(self.queue["e2e_pass"])
        self.assertFalse(self.queue["store_submission_allowed"])
        self.assertFalse(self.queue["certification_allowed"])
        self.assertFalse(self.queue["publish_allowed"])
        self.assertEqual(self.queue["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.queue["store_upload_test_eligibility"]["dry_run_started"])
        self.assertFalse(self.queue["store_upload_test_eligibility"]["live_started"])


if __name__ == "__main__":
    unittest.main()
