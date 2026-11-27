import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261128_0132.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261128_0132.json"


class CurrentE2EHandoffStateCorrection20261128Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_pr165_live_branch_head_and_exact_head_ci_are_current(self):
        p = self.overlay["pr165"]
        self.assertEqual(p["head_sha"], "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertTrue(all(x["head_sha"] == p["head_sha"] and x["conclusion"] == "success"
                            for x in p["exact_head_ci"]))
        self.assertEqual([x["run_id"] for x in p["exact_head_ci"]],
                         [45899687437, 45899687528, 45899687545])
        self.assertFalse(p["real_msix"])
        self.assertFalse(p["local_checker_receipt"])

    def test_pr161_and_pr171_are_offline_qa_only_and_green(self):
        for key, sha in (
            ("pr161", "71d9c2125b6aed44a86ca1872d48ad19963f3e63"),
            ("pr171", "764721021f13be96364529650b44fb439770bac9"),
        ):
            p = self.overlay[key]
            self.assertEqual(p["head_sha"], sha)
            self.assertTrue(all(x["conclusion"] == "success" for x in p["exact_head_ci"]))
            self.assertIn("Offline QA only", p["scope"])
        self.assertEqual(self.overlay["pr171"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.overlay["pr171"]["dry_run_started"])
        self.assertFalse(self.overlay["pr171"]["live_started"])

    def test_pr215_fixture_is_synthetic_and_cannot_promote_product_e2e(self):
        f = self.overlay["pr215"]["integration_fixture"]
        self.assertEqual(f["marker"], "QA_FIXTURE_ONLY_NOT_PRODUCT")
        self.assertTrue(f["synthetic_package"])
        self.assertTrue(f["synthetic_identity_and_version"])
        self.assertEqual(f["checker_verdict"], "NEEDS_REVIEW")
        self.assertEqual(f["result_status"], "HOLD")
        self.assertIs(f["e2e_pass"], False)
        self.assertIs(f["product_e2e"], False)

    def test_focus_request_artifact_is_exact_source_bound_dry_run(self):
        p = self.overlay["products"]["focus_session_desk"]
        r = p["current_request"]
        self.assertEqual(p["current_source"]["sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(r["request_id"], "app-focus-session-desk-b6b69464a9c7")
        self.assertEqual(r["artifact_id"], 15166202971)
        self.assertEqual(r["artifact_sha256"], "8f1862039297711a68bc33e8e25bea8cfc85f9926b269f0b2136bfa9986b503a")
        self.assertTrue(r["dry_run"])
        self.assertIs(r["request_submitted"], False)
        self.assertEqual(r["source_head_verification"], "VERIFIED")
        self.assertEqual(r["status"], "DRY_RUN")

    def test_focus_historical_identity_is_not_current_source_approval(self):
        p = self.overlay["products"]["focus_session_desk"]
        identity = p["current_source_identity_file"]
        self.assertTrue(identity["tracked_file_present"])
        self.assertEqual(identity["bound_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertNotEqual(identity["bound_source_sha"], p["current_source"]["sha"])
        self.assertEqual(identity["binding"], "STALE_HISTORICAL_SOURCE_MISMATCH_NOT_REUSABLE")
        self.assertFalse(identity["package_version_field_present"])
        self.assertIsNone(p["authoritative_package_version"])
        self.assertEqual(p["msix_export"]["exact_reason"], "MSIX_BUILD_HOLD: Missing verified version")
        self.assertFalse(p["real_msix"])

    def test_file_integrity_request_is_exact_source_bound_but_not_identity_approved(self):
        p = self.overlay["products"]["file_integrity_ledger"]
        r = p["current_request"]
        self.assertEqual(p["current_source"]["sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(r["request_id"], "app-file-integrity-ledger-33d612be2774")
        self.assertEqual(r["artifact_id"], 14934034365)
        self.assertEqual(r["artifact_sha256"], "697528b3b0769e3962eebfa0efcdcb026618cd378d97fc60c4f234017882527e")
        self.assertTrue(r["dry_run"])
        self.assertEqual(r["status"], "DRY_RUN")
        self.assertIs(r["request_submitted"], False)
        self.assertFalse(p["current_source_approved_identity_file_present"])
        self.assertEqual(p["historical_identity_reference"]["source_sha"],
                         "d1108d12f7d1697af30400f97c7db39cba5e6791")
        self.assertIsNone(p["authoritative_package_version"])
        self.assertTrue(p["msix_export"]["build_steps_skipped"])
        self.assertFalse(p["real_msix"])

    def test_asset_ownership_and_package_freeze_are_preserved(self):
        for key in ("focus_session_desk", "file_integrity_ledger"):
            p = self.overlay["products"][key]
            self.assertTrue(p["assets"]["required_pngs_present"])
            self.assertEqual(p["assets"]["owner"], "00")
            self.assertFalse(p["assets"]["regeneration_by_36"])
        self.assertTrue(self.queue["rules"]["no_identity_rerequest"])
        self.assertTrue(self.queue["rules"]["no_historical_identity_reuse"])

    def test_all_lane_state_classifications_match_supervisor_policy(self):
        p = self.overlay["products"]
        self.assertEqual(p["focus_session_desk"]["state"], "POST_IDENTITY_UPGRADE")
        self.assertEqual(p["file_integrity_ledger"]["state"], "POST_IDENTITY_UPGRADE")
        self.assertEqual(p["prism_route_3d"]["state"], "POST_IDENTITY_UPGRADE")
        self.assertEqual(p["signal_sprint"]["state"], "POST_IDENTITY_UPGRADE")
        self.assertEqual(p["offline_notes_canary"]["state"], "PRE_IDENTITY_FIX_REQUIRED")
        self.assertEqual(self.queue["waiting_user_identity_products"], [])

    def test_partner_center_and_local_sync_are_not_claimed(self):
        pc = self.overlay["partner_center_readback"]
        self.assertFalse(pc["writes_attempted"])
        self.assertEqual(pc["status"], "NOT_PERFORMED_AUTHENTICATED_BROWSER_CONTEXT_UNAVAILABLE")
        self.assertEqual(pc["focus_current_source_identity"], "UNVERIFIED")
        self.assertEqual(pc["file_current_source_identity"], "UNVERIFIED")
        local = self.overlay["local_code_sync"]
        self.assertEqual(local["status"], "NOT_OBSERVED__CLOUD_PASS_ONLY")
        self.assertFalse(local["durable_receipt_present"])
        self.assertFalse(local["physical_user_windows_session_available"])

    def test_canonical_ledger_is_preserved_and_global_gates_stay_false(self):
        c = self.overlay["canonical_ledger_reconciliation"]
        self.assertEqual(c["path"], "ops/active_e2e_handoff.json")
        self.assertEqual(c["bytes"], 1976822)
        self.assertEqual(c["current_fetch_status"], "EMPTY_CONTENT")
        self.assertTrue(c["stale"])
        self.assertFalse(c["rewritten"])
        for key in ("real_msix", "github_backlog_receipt", "local_pull_receipt",
                    "local_checker_receipt", "local_gui_install_receipt",
                    "store_submission_allowed", "certification_allowed",
                    "publish_allowed", "merge_allowed", "force_push_allowed"):
            self.assertIs(self.overlay[key], False)
        self.assertFalse(self.overlay["e2e_pass"])


if __name__ == "__main__":
    unittest.main()
