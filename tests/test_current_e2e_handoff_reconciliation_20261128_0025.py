import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261128_0025.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261128_0025.json"


class CurrentE2EHandoffReconciliation20261128Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_pr165_pr161_pr171_and_pr215_heads_are_exact_and_ci_passes(self):
        o = self.overlay
        self.assertEqual(o["pr165"]["head_sha"], "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertTrue(all(x["head_sha"] == o["pr165"]["head_sha"] and x["conclusion"] == "success"
                            for x in o["pr165"]["exact_head_ci"]))
        self.assertEqual(o["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertTrue(all(x["head_sha"] == o["pr161"]["head_sha"] and x["conclusion"] == "success"
                            for x in o["pr161"]["exact_head_ci"]))
        self.assertEqual(o["pr171"]["head_sha"], "764721021f13be96364529650b44fb439770bac9")
        self.assertTrue(all(x["head_sha"] == o["pr171"]["head_sha"] and x["conclusion"] == "success"
                            for x in o["pr171"]["exact_head_ci"]))
        self.assertEqual(o["pr215"]["head_sha"], "ffcb416493fe4ec41779ae65b2274551c2a3c3eb")
        self.assertTrue(all(x["head_sha"] == o["pr215"]["head_sha"] and x["conclusion"] == "success"
                            for x in o["pr215"]["exact_head_ci"]))

    def test_pr215_fixture_exercises_transport_pull_checker_but_is_not_product_e2e(self):
        f = self.overlay["pr215"]["integration_fixture"]
        self.assertEqual(f["marker"], "QA_FIXTURE_ONLY_NOT_PRODUCT")
        self.assertTrue(f["synthetic_package"])
        self.assertTrue(f["synthetic_identity_and_version"])
        self.assertEqual(f["checker_verdict"], "NEEDS_REVIEW")
        self.assertEqual(f["result_status"], "HOLD")
        self.assertIs(f["e2e_pass"], False)
        self.assertEqual(f["local_gui_qa"], "NOT_RUN")
        self.assertEqual(f["submitted_to_store"], 0)
        self.assertIs(f["real_product_msix"], False)
        self.assertIs(f["physical_local_windows_pull"], False)
        self.assertIs(f["trusted_windows_checker"], False)
        self.assertIs(f["product_gui_install"], False)
        self.assertIs(f["product_e2e"], False)

    def test_focus_current_request_does_not_authorize_historical_identity_reuse(self):
        p = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(p["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(p["approved_identity_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertNotEqual(p["approved_identity_source_sha"], p["current_source_sha"])
        self.assertEqual(p["current_identity_binding"], "STALE_HISTORICAL_SOURCE_MISMATCH_NOT_REUSABLE")
        self.assertEqual(p["current_request"]["source_sha"], p["current_source_sha"])
        self.assertEqual(p["current_request"]["status"], "DRY_RUN")
        self.assertIs(p["current_request"]["submitted"], False)
        self.assertEqual(p["current_request"]["official_identity_status"], "UNVERIFIED")
        self.assertIsNone(p["current_request"]["package_version"])
        self.assertEqual(p["current_request"]["package_status"], "NOT_BUILT")
        self.assertEqual(p["current_request"]["github_return_status"], "NOT_APPLIED")
        self.assertEqual(p["msix_export"]["exact_reason"], "MSIX_BUILD_HOLD: Missing verified version")
        self.assertIs(p["real_msix"], False)

    def test_file_integrity_has_no_current_approved_identity_and_request_is_dry_run(self):
        p = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(p["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertIs(p["approved_identity_file_present"], False)
        self.assertEqual(p["current_identity_binding"], "NO_CURRENT_SOURCE_APPROVED_IDENTITY")
        self.assertEqual(p["current_request"]["source_sha"], p["current_source_sha"])
        self.assertEqual(p["current_request"]["status"], "DRY_RUN")
        self.assertEqual(p["current_request"]["official_identity_status"], "UNVERIFIED")
        self.assertIsNone(p["current_request"]["package_version"])
        self.assertEqual(p["current_request"]["package_status"], "NOT_BUILT")
        self.assertEqual(p["msix_export"]["selection_hold_reason"],
                         "MSIX_SELECTION_HOLD: approved Identity absent; do not invent Store IDs")
        self.assertIs(p["msix_export"]["build_steps_skipped"], True)
        self.assertIs(p["real_msix"], False)

    def test_transport_and_checker_receipts_remain_honest_holds(self):
        o = self.overlay
        for key in ("real_msix", "github_backlog_receipt", "local_pull_receipt",
                    "local_checker_receipt", "local_gui_install_receipt"):
            self.assertIs(o[key], False)
        self.assertEqual(o["e2e_status"], "HOLD")
        self.assertIs(o["e2e_pass"], False)

    def test_canonical_ledger_is_preserved_and_overlay_is_append_only(self):
        c = self.overlay["canonical_ledger_reconciliation"]
        self.assertEqual(c["path"], "ops/active_e2e_handoff.json")
        self.assertEqual(c["bytes"], 1976822)
        self.assertEqual(c["current_fetch_status"], "EMPTY_CONTENT")
        self.assertIs(c["stale"], True)
        self.assertIs(c["rewritten"], False)

    def test_local_code_sync_is_not_promoted_from_cloud_only_evidence(self):
        s = self.overlay["local_code_sync"]
        self.assertEqual(s["status"], "NOT_OBSERVED__CLOUD_PASS_ONLY")
        self.assertIs(s["durable_receipt_present"], False)
        self.assertIs(s["physical_user_windows_session_available"], False)
        self.assertIsNone(s["first_run_receipt"])
        self.assertIsNone(s["idempotent_reuse_receipt"])

    def test_store_permissions_and_queue_priorities_remain_fail_closed(self):
        o = self.overlay
        for key in ("store_submission_allowed", "certification_allowed", "publish_allowed",
                    "merge_allowed", "force_push_allowed"):
            self.assertIs(o[key], False)
        self.assertEqual(o["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertIs(o["store_upload_test_eligibility"]["dry_run_started"], False)
        self.assertIs(o["store_upload_test_eligibility"]["live_started"], False)
        self.assertEqual([x["product"] for x in self.queue["priority"][:2]],
                         ["Focus Session Desk", "File Integrity Ledger"])
        self.assertIs(self.queue["new_product_generation_allowed"], False)
        self.assertIs(self.queue["global"]["e2e_pass"], False)
        self.assertIs(self.queue["global"]["store_submission_allowed"], False)


if __name__ == "__main__":
    unittest.main()
