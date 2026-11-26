"""Current PR165 live-head reconciliation; repository CI is not product E2E."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ops" / "active_e2e_handoff.json"
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261126_143124.json"


class LivePR165Reconciliation20261126Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))

    def test_live_pr165_head_and_exact_ci_are_current_without_e2e_promotion(self):
        ledger = self.ledger
        key = "pr165_live_head_observation_20261126_143124"
        self.assertEqual(ledger["latest_live_head_observation_key"], key)
        observation = ledger[key]
        self.assertEqual(observation["head_sha"], "84f9a3480e2df93f0d75bddc29fb8de47e4ec941")
        self.assertEqual(observation["previous_observed_head_sha"], "776431b039bd67ffdbc6a215aa1fc672ad1d1549")
        self.assertEqual(observation["comparison_to_previous_observed_head"]["ahead_by"], 2)
        self.assertEqual(observation["comparison_to_last_verified_code_head"]["ahead_by"], 39)
        self.assertEqual(observation["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in observation["exact_head_ci"]],
                         [45833181013, 45833181073, 45833180930])
        self.assertTrue(all(x["head_sha"] == observation["head_sha"] and x["conclusion"] == "success"
                            for x in observation["exact_head_ci"]))
        self.assertEqual(observation["offline_qa"]["windows"]["tests_run"], 578)
        self.assertEqual(observation["offline_qa"]["windows"]["skipped"], 2)
        self.assertEqual(observation["offline_qa"]["ubuntu"]["tests_run"], 578)
        self.assertEqual(observation["offline_qa"]["ubuntu"]["skipped"], 0)
        self.assertEqual(ledger["latest_live_execution_reconciliation_key"],
                         "latest_live_execution_reconciliation_20261126_143124")
        recon = ledger["latest_live_execution_reconciliation_20261126_143124"]
        self.assertEqual(recon["status"], "HOLD")
        self.assertIs(recon["e2e_pass"], False)
        self.assertIs(ledger["latest_live_e2e_pass"], False)
        self.assertTrue(observation["repository_ci_is_not_product_e2e"])

    def test_focus_and_file_current_source_identity_version_gates_remain_held(self):
        recon = self.ledger["latest_live_execution_reconciliation_20261126_143124"]
        focus = recon["focus_session_desk"]
        self.assertEqual(focus["source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["request"]["request_id"], "app-focus-session-desk-fb6293839bc7")
        self.assertEqual(focus["request"]["status"], "DRY_RUN")
        self.assertEqual(focus["identity"]["current_source_identity_status"], "NOT_COLLECTED")
        self.assertEqual(focus["identity"]["historical_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertIs(focus["identity"]["current_source_reuse_allowed"], False)
        self.assertIsNone(focus["package_version"])
        self.assertIs(focus["real_msix"], False)

        file_product = recon["file_integrity_ledger"]
        self.assertEqual(file_product["source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(file_product["request"]["request_id"], "app-file-integrity-ledger-33d612be2774")
        self.assertEqual(file_product["request"]["status"], "DRY_RUN")
        self.assertIs(file_product["identity"]["current_source_approved_identity_present"], False)
        self.assertEqual(file_product["identity"]["official_identity_status"], "UNVERIFIED")
        self.assertIsNone(file_product["package_version"])
        self.assertIs(file_product["real_msix"], False)
        self.assertEqual(file_product["visual_review"]["status"], "HUMAN_OWNER_VISUAL_REVIEW_PASS")
        self.assertIs(file_product["visual_review"]["immutable_receipt_flag_remains_true"], True)

        self.assertEqual(recon["first_unconnected_interval"]["status"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        self.assertIsNone(recon["partner_center"]["authoritative_package_version"])
        self.assertIs(recon["partner_center"]["version_inferred"], False)
        self.assertIs(recon["partner_center"]["partner_center_write_performed"], False)

    def test_local_pull_port_keeps_identity_receipts_paired_and_never_claims_e2e(self):
        port = self.ledger["latest_live_execution_reconciliation_20261126_143124"]["local_pull_contract"]
        self.assertEqual(port["status"], "PORTED_TO_CURRENT_PR165_STACK__EXACT_HEAD_CI_PENDING")
        self.assertEqual(port["receipt_status"], "CUSTODY_VERIFIED_ONLY")
        self.assertIn("approved-identity.json included in custody bundle allowlist", port["checks"])
        self.assertIn("transport_receipt.json + github-custody.json + approved-identity.json required all-or-none",
                      port["checks"])
        self.assertIs(port["e2e_pass"], False)
        self.assertIs(port["local_pull_receipt"], False)
        self.assertIs(port["local_checker_receipt"], False)
        self.assertIs(port["local_gui_install_receipt"], False)

        overlay_port = self.overlay["local_pull_contract"]
        self.assertEqual(overlay_port["branch"], "codex/36-e2e-local-pull-ledger-20261126-1431")
        self.assertEqual(overlay_port["base_pr165_head"], "84f9a3480e2df93f0d75bddc29fb8de47e4ec941")
        self.assertEqual(overlay_port["identity_receipt_pairing"], "ALL_THREE_REQUIRED_OR_HOLD")
        self.assertIs(overlay_port["e2e_pass"], False)

    def test_pr161_pr187_pr171_and_store_safety_are_not_misrepresented(self):
        recon = self.ledger["latest_live_execution_reconciliation_20261126_143124"]
        self.assertEqual(recon["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(recon["pr161"]["exact_head_run_id"], 42712757936)
        self.assertEqual(recon["pr161"]["exact_head_conclusion"], "success")
        self.assertEqual(recon["pr161"]["scope"], "Offline QA only; not product E2E")
        self.assertEqual(recon["pr187"]["head_sha"], "5ad7b5b9522ef4640481b5c71af301405b1f255b")
        self.assertEqual(recon["pr187"]["decision"], "DO_NOT_MERGE_OR_REBASE_BLINDLY__SELECTIVE_PORT_TO_CURRENT_HEAD")
        self.assertEqual(recon["pr171"]["eligible_fresh_unsold_products"], 0)
        self.assertIs(recon["pr171"]["dry_run_started"], False)
        self.assertIs(recon["store_upload_test"]["dry_run_started"], False)
        for key in ("store_submission_allowed", "certification_allowed", "publish_allowed"):
            self.assertIs(recon["store_upload_test"][key], False)
        safety = self.overlay["safety"]
        for key in ("live_partner_center_write_allowed", "store_submission_allowed",
                    "certification_allowed", "publish_allowed", "merge_allowed",
                    "force_push_allowed", "identity_write_allowed", "version_inference_allowed",
                    "prism_legacy_identity_cas_allowed", "twelve_repo_touched",
                    "twentyfour_repo_touched", "png_generation_or_modification",
                    "product_code_changed"):
            self.assertIs(safety[key], False)


if __name__ == "__main__":
    unittest.main()
