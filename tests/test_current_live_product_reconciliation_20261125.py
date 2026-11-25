import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ops" / "active_e2e_handoff.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261116.json"
RECON = ROOT / "ops" / "focus_file_transport_reconciliation_20261125.json"


class CurrentLiveProductReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        cls.recon = json.loads(RECON.read_text(encoding="utf-8"))

    def test_pr165_exact_head_ci_is_not_product_e2e(self):
        self.assertEqual(self.ledger["latest_transport_reconciliation"]["central_tested_head_sha"],
                         "60ab8183a05f248972bf227d6059671f5f0532ac")
        self.assertEqual(self.ledger["latest_transport_reconciliation"]["previous_central_head_sha"],
                         "98953c5a9815a4ff30dfd82564a1672b7992a2bd")
        self.assertEqual([x["run_id"] for x in self.ledger["latest_transport_reconciliation"]["exact_head_ci"]],
                         [45504775685, 45504775807, 45504775632])
        self.assertEqual(self.ledger["latest_transport_reconciliation"]["pr165_current_head_parent_ci_status"],
                         "PASS_EXACT_HEAD_CI")
        self.assertEqual(self.ledger["e2e_status"], "HOLD")
        self.assertIs(self.ledger["e2e_pass"], False)
        self.assertIs(self.ledger["latest_transport_reconciliation"]["real_msix"], False)

    def test_focus_identity_and_request_remain_historical(self):
        focus = next(x for x in self.ledger["current_priority_products"] if x["product"] == "Focus Session Desk")
        self.assertEqual(focus["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["approved_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(focus["approved_identity_file_blob_sha"], "00c56e85ec7590783284e372ba100a3127614971")
        self.assertEqual(focus["current_source_request_status"], "NOT_OBSERVED__HISTORICAL_REQUEST_BINDS_8B00_ONLY")
        self.assertEqual(focus["current_source_identity_binding_status"], "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
        self.assertIsNone(focus["package_version"])
        self.assertIs(focus["real_msix"], False)
        self.assertEqual(focus["product_quality_assessment"]["score"]["total"], 54)
        self.assertEqual(focus["product_quality_assessment"]["decision"], "DO_NOT_SELL__BELOW_80")

    def test_file_request_is_current_source_dry_run_not_identity_or_package(self):
        file_row = next(x for x in self.ledger["current_priority_products"] if x["product"] == "File Integrity Ledger")
        request = file_row["current_source_request"]
        self.assertEqual(file_row["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(request["request_id"], "app-file-integrity-ledger-33d612be2774")
        self.assertEqual(request["source_sha"], file_row["current_source_sha"])
        self.assertEqual(request["status"], "DRY_RUN")
        self.assertEqual(request["official_identity_status"], "NOT_COLLECTED")
        self.assertIsNone(request["package_version"])
        self.assertIsNone(file_row["package_version"])
        self.assertIs(file_row["real_msix"], False)
        self.assertFalse(file_row["approved_identity_file_present_on_current_pr115_head"])
        self.assertEqual(file_row["msix_export"]["status"], "SKIPPED_NO_ARTIFACT")

    def test_prism_current_export_does_not_reuse_old_identity_or_claim_physical_qa(self):
        prism = next(x for x in self.ledger["current_priority_products"] if x["product"] == "Prism Route 3D")
        self.assertEqual(prism["current_source_sha"], "b03ce7b16c3f75c04fe20fdda224c45849eeba0d")
        self.assertEqual(prism["historical_factory_source_sha"], "4c22875c5ed79d393516c6a7a95361b9e9ed1950")
        self.assertFalse(prism["historical_identity_cas_reuse_allowed"])
        self.assertEqual(prism["export_run_id"], 43794658086)
        self.assertEqual(prism["factory_export_artifact_id"], 14797309778)
        self.assertEqual(prism["physical_qa_sessions"], "0/6")
        self.assertEqual(prism["current_source_identity_rebind"], "PENDING_CURRENT_SOURCE_APPROVAL")
        self.assertIsNone(prism["package_version"])
        self.assertIs(prism["real_msix"], False)

    def test_signal_current_tuple_is_separate_from_historical_c058(self):
        self.assertTrue(self.ledger["active_product_is_historical"])
        self.assertEqual(self.ledger["active_product"]["source_sha"], "c058cbf7fe38e02d929c67d047d717ff74bd522e")
        signal = self.ledger["current_signal_sprint_live_20261125"]
        self.assertEqual(signal["current_candidate_source_sha"], "1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertEqual(signal["current_request_id"], "game-signal-sprint-1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertTrue(signal["request_dry_run"])
        self.assertFalse(signal["request_submitted"])
        self.assertEqual(signal["cas_status"], "NOT_APPLIED")
        self.assertEqual(signal["build_artifact_id"], 14931068646)
        self.assertFalse(signal["physical_windows_uia_pass"])
        self.assertIsNone(signal["package_version"])
        self.assertIs(signal["real_msix"], False)
        self.assertFalse(signal["real_msixvc"])
        self.assertFalse(signal["required_revision_in_frozen_source"])

    def test_four_way_registration_routes_and_unresolved_products(self):
        entries = {x["product"]: x for x in self.ledger["current_live_registration_routing_20261125"]["entries"]}
        self.assertEqual(entries["Focus Session Desk"]["registration_type"], "MSIX_OR_PWA_APP")
        self.assertEqual(entries["File Integrity Ledger"]["registration_type"], "MSIX_OR_PWA_APP")
        self.assertEqual(entries["Offline Notes Canary"]["registration_type"], "MSIX_OR_PWA_APP")
        self.assertEqual(entries["Signal Sprint"]["registration_type"], "GDK_GAME")
        self.assertEqual(entries["Prism Route 3D"]["registration_type"], "MSIX_OR_PWA_GAME")
        self.assertEqual(entries["Offline Text Diff Desk"]["registration_type"], "HOLD_REGISTRATION_TYPE_UNRESOLVED")
        self.assertEqual(entries["Offline Image Inventory Desk"]["registration_type"], "HOLD_REGISTRATION_TYPE_UNRESOLVED")

    def test_pr161_pr171_and_pr174_are_not_promoted_to_e2e_or_store_pass(self):
        self.assertEqual(self.recon["pr161"]["scope"], "Offline QA only; not product E2E")
        self.assertIn("dry-run not started", self.recon["pr171"]["scope"])
        self.assertEqual(self.recon["pr174"]["compare_to_current_pr165_head"]["behind_by"], 84)
        self.assertEqual(self.recon["pr174"]["decision"], "DO_NOT_RESTACK")
        self.assertEqual(self.recon["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.recon["store_upload_test_eligibility"]["dry_run_started"])
        self.assertEqual(self.ledger["local_code_sync_receipt_status_20261125"]["status"],
                         "NOT_OBSERVED__CLOUD_PASS_ONLY")
        for key in ("store_submission_allowed", "certification_allowed", "publish_allowed",
                    "live_partner_center_write_allowed", "merge_allowed", "force_push_allowed"):
            self.assertIs(self.ledger[key], False)


if __name__ == "__main__":
    unittest.main()
