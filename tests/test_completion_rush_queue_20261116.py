import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "ops/completion_rush_queue_20261127_0731.json"


class CompletionRushQueueCurrentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))
        cls.products = {item["product"]: item for item in cls.queue["priority"]}

    def test_focus_is_delivery_hold_with_stale_source_bound_request(self):
        focus = self.products["Focus Session Desk"]
        self.assertEqual(focus["state"], "POST_IDENTITY_UPGRADE")
        self.assertEqual(focus["hold_class"], "DELIVERY_HOLD")
        self.assertFalse(focus["functional_hold"])
        self.assertTrue(focus["product_frozen_for_package"])
        self.assertEqual(focus["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(focus["source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertEqual(focus["identity_return_scope"], "HISTORICAL_SOURCE_ONLY")
        self.assertEqual(focus["current_source_identity_binding_status"], "STALE_HISTORICAL_SOURCE_MISMATCH")
        self.assertIsNone(focus["current_source_request_id"])
        self.assertEqual(focus["stale_source_request_id"], "app-focus-session-desk-fb6293839bc7")
        self.assertEqual(focus["current_source_request_status"], "STALE_SOURCE_MISMATCH__REGENERATION_REQUIRED")
        self.assertIsNone(focus["package_version"])
        self.assertEqual(focus["package_version_status"], "AUTHORITATIVE_VALUE_REQUIRED")
        self.assertFalse(focus["real_msix"])
        self.assertFalse(focus["product_e2e_pass"])
        self.assertEqual(focus["current_source_gui_run_id"], 45895951025)
        self.assertTrue(focus["current_source_gui_cold_restart_persistence_verified"])
        self.assertEqual(focus["owner_visual_signoff_status"], "PENDING")
        self.assertEqual(focus["product_quality_assessment"]["score"]["total"], 54)
        self.assertEqual(focus["sale_decision"], "DO_NOT_SELL_BELOW_80")

    def test_file_is_waiting_for_current_source_identity_and_version(self):
        file_item = self.products["File Integrity Ledger"]
        self.assertEqual(file_item["state"], "WAITING_USER_IDENTITY")
        self.assertEqual(file_item["hold_class"], "DELIVERY_HOLD")
        self.assertFalse(file_item["functional_hold"])
        self.assertTrue(file_item["product_frozen_for_package"])
        self.assertEqual(file_item["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(file_item["source_sha"], "d1108d12f7d1697af30400f97c7db39cba5e6791")
        self.assertEqual(file_item["identity_return_scope"], "HISTORICAL_SOURCE_ONLY")
        self.assertEqual(file_item["current_source_identity_binding_status"], "NO_CURRENT_SOURCE_APPROVED_IDENTITY")
        self.assertFalse(file_item["approved_identity_file_present_on_current_pr115_head"])
        self.assertEqual(file_item["current_source_request_id"], "app-file-integrity-ledger-33d612be2774")
        self.assertEqual(file_item["current_source_request"]["source_sha"], file_item["current_source_sha"])
        self.assertEqual(file_item["current_source_request"]["status"], "DRY_RUN")
        self.assertEqual(file_item["current_source_request"]["official_identity_status"], "UNVERIFIED")
        self.assertEqual(file_item["human_visual_review_status"], "PASS")
        self.assertEqual(file_item["asset_mapping_qa_run_id"], 45747686529)
        self.assertIsNone(file_item["package_version"])
        self.assertFalse(file_item["real_msix"])
        self.assertFalse(file_item["product_e2e_pass"])

    def test_prism_source_conflict_and_signal_artifacts_are_not_promoted(self):
        prism = self.products["Prism Route 3D"]
        self.assertEqual(prism["user_declared_current_source_sha_prefix"], "4c22875c")
        self.assertEqual(prism["last_repository_observed_source_sha"], "b03ce7b16c3f75c04fe20fdda224c45849eeba0d")
        self.assertEqual(prism["source_reconciliation_status"], "CONFLICT__EXACT_CURRENT_HEAD_NOT_REVALIDATED")
        self.assertFalse(prism["old_identity_reuse_allowed"])
        self.assertIsNone(prism["package_version"])
        self.assertFalse(prism["real_msix"])

        signal = self.products["Signal Sprint"]
        self.assertEqual(signal["current_build_artifact_id"], 14946655071)
        self.assertEqual(signal["current_gdk_readiness_artifact_id"], 14946675208)
        self.assertEqual(signal["build_artifact_status"], "ARTIFACTS_PRESENT__EXE_AND_GDK_READINESS__MSIXVC_NOT_BUILT")
        self.assertEqual(signal["gdk_sdk_status"], "HOLD_GDK_SDK_ROOT_NOT_FOUND")
        self.assertFalse(signal["physical_windows_uia_pass"])
        self.assertFalse(signal["real_msixvc"])

    def test_pr165_and_sequential_pr192_to_pr196_restacks_have_exact_head_ci(self):
        latest = self.queue["latest_transport_reconciliation"]
        self.assertEqual(latest["central_head"], "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertEqual(latest["previous_central_head_sha"], "6afe5ec89a440880066bee43a61f596a5939761d")
        self.assertEqual(latest["ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in latest["exact_head_ci"]], [45899687528,45899687437,45899687545])
        self.assertEqual(latest["status"], "HOLD")
        self.assertFalse(latest["e2e_pass"])
        chain = self.queue["restack_chain_current_20261127_0731"]
        self.assertEqual([x["pr"] for x in chain], [197,198,202,203,204])
        self.assertTrue(all(x["ci_status"] == "PASS_EXACT_HEAD_CI" for x in chain))
        self.assertTrue(all(x["product_e2e_pass"] is False for x in chain if "product_e2e_pass" in x))
        self.assertFalse(self.queue["current_transport_reconciliation_20261127_0731"]["pr165"]["real_msix"])

    def test_no_real_package_or_store_authority_is_claimed(self):
        self.assertEqual(self.queue["status"], "HOLD")
        self.assertFalse(self.queue["e2e_pass"])
        self.assertFalse(self.queue["new_product_generation_allowed"])
        self.assertEqual(self.queue["first_unconnected_interval_current_20261127_0731"]["status"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        self.assertFalse(self.queue["store_upload_test_eligibility_current_20261127_0731"]["eligible_fresh_unsold_products"])
        self.assertFalse(self.queue["store_upload_test_eligibility_current_20261127_0731"]["dry_run_started"])
        self.assertFalse(self.queue["store_upload_test_eligibility_current_20261127_0731"]["live_started"])
        self.assertEqual(self.queue["local_code_sync_receipt_status_current_20261127_0731"], "NOT_OBSERVED__CLOUD_PASS_ONLY")
        self.assertFalse(self.queue["store_submission_allowed"])
        self.assertFalse(self.queue["certification_allowed"])
        self.assertFalse(self.queue["publish_allowed"])
        self.assertFalse(self.queue["safety_current_20261127_0731"]["live_partner_center_write_allowed"])


if __name__ == "__main__":
    unittest.main()
