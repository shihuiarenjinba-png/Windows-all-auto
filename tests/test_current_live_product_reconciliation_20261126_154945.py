import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
STAMP = "20261126_154945"
HEAD165 = "84f9a3480e2df93f0d75bddc29fb8de47e4ec941"
HEAD190 = "a7e2abae75a65828721ea35005df12a245335f2a"
PR165_RUNS = [45833181013, 45833181073, 45833180930]
PR190_RUNS = [45851167368, 45851167382, 45851167381]


class CurrentLiveProductReconciliation20261126_154945Tests(unittest.TestCase):
    def test_pr165_and_pr190_exact_heads_are_recorded_without_product_e2e_promotion(self):
        ledger = json.loads((ROOT / "ops/active_e2e_handoff.json").read_text(encoding="utf-8"))
        queue = json.loads((ROOT / "ops/completion_rush_queue_20261116.json").read_text(encoding="utf-8"))
        overlay = json.loads((ROOT / "ops" / f"active_e2e_handoff_overlay_{STAMP}.json").read_text(encoding="utf-8"))

        key = f"pr165_live_head_observation_{STAMP}"
        self.assertEqual(ledger["pr165_latest_live_observation_key"], key)
        self.assertEqual(ledger["pr165_latest_live_head_sha"], HEAD165)
        observation = ledger[key]
        self.assertEqual(observation["head_sha"], HEAD165)
        self.assertEqual([x["run_id"] for x in observation["exact_head_ci"]], PR165_RUNS)
        self.assertTrue(all(x["head_sha"] == HEAD165 and x["conclusion"] == "success" for x in observation["exact_head_ci"]))
        self.assertFalse(observation["product_code_changed"])
        self.assertEqual(observation["product_e2e_status"], "HOLD")
        self.assertFalse(observation["e2e_pass"])
        self.assertIsNone(observation["parent_sha"])
        self.assertEqual(observation["parent_sha_status"], "NOT_RETURNED_BY_COMMIT_METADATA_READ")

        transport = ledger["pr190_local_pull_transport_20261127"]
        self.assertEqual(transport["head_sha"], HEAD190)
        self.assertEqual(transport["base_sha"], HEAD165)
        self.assertEqual(transport["comparison_to_pr165"]["ahead_by"], 6)
        self.assertEqual(transport["comparison_to_pr165"]["behind_by"], 0)
        self.assertEqual([x["run_id"] for x in transport["exact_head_ci"]], PR190_RUNS)
        self.assertTrue(all(x["head_sha"] == HEAD190 and x["conclusion"] == "success" for x in transport["exact_head_ci"]))
        self.assertEqual(transport["status"], "IMPLEMENTED_CI_PASS_NOT_EXECUTED")
        self.assertFalse(transport["physical_user_pc_execution_status"] == "PASS")
        self.assertFalse(transport["local_pull_receipt"])
        self.assertFalse(transport["windows_checker_receipt"])
        self.assertFalse(transport["local_gui_install_receipt"])
        self.assertFalse(transport["product_e2e_pass"])

        self.assertTrue(ledger["active_product_is_historical"])
        self.assertEqual(ledger["active_product"]["request_id"], "game-signal-sprint-c058cbf7fe38e02d929c67d047d717ff74bd522e")
        self.assertEqual(ledger["current_active_product"]["request_id"], "game-signal-sprint-1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertTrue(ledger["current_request_pointer"])
        self.assertEqual(ledger["current_active_product"]["source_sha"], "1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertEqual(ledger["current_active_product"]["current_identity_preview_status"], "GDK_IDENTITY_PREVIEW_PRESENT__DRY_RUN_ONLY__CAS_NOT_APPLIED")
        self.assertFalse(ledger["current_active_product"]["cas_applied"])

        products = {x["product"]: x for x in ledger[f"current_priority_products_live_20261127_{STAMP[-6:]}"]} if f"current_priority_products_live_20261127_{STAMP[-6:]}" in ledger else {x["product"]: x for x in ledger["current_priority_products_live_20261127_154945"]}
        focus = products["Focus Session Desk"]
        self.assertEqual(focus["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["identity_acquisition_owner"], "USER")
        self.assertIsNone(focus["package_version"])
        self.assertFalse(focus["real_msix"])
        file_product = products["File Integrity Ledger"]
        self.assertEqual(file_product["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertFalse(file_product["approved_identity_file_present_on_current_source"])
        self.assertIsNone(file_product["package_version"])
        prism = products["Prism Route 3D"]
        self.assertEqual(prism["current_source_sha"], "b03ce7b16c3f75c04fe20fdda224c45849eeba0d")
        self.assertEqual(prism["historical_approved_identity_source_sha_prefix"], "15fdcb52")
        self.assertEqual(prism["physical_windows_sessions_passed"], 0)
        self.assertIsNone(prism["package_version"])
        signal = products["Signal Sprint"]
        self.assertEqual(signal["current_source_sha"], "1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertEqual(signal["current_identity_preview_status"], "GDK_IDENTITY_PREVIEW_PRESENT__DRY_RUN_ONLY__CAS_NOT_APPLIED")
        self.assertEqual(signal["current_build_artifact_id"], 14946655071)
        self.assertEqual(signal["current_gdk_readiness_artifact_id"], 14946675208)
        self.assertIsNone(signal["package_version"])
        self.assertFalse(signal["real_msixvc"])

        self.assertEqual(queue["latest_observation_key"], key)
        self.assertEqual(queue["latest_transport_reconciliation"]["central_head"], HEAD165)
        self.assertEqual([x["run_id"] for x in queue["latest_transport_reconciliation"]["exact_head_ci"]], PR165_RUNS)
        self.assertEqual(queue["latest_transport_reconciliation"]["pr190_local_pull_transport"]["head_sha"], HEAD190)
        signal_queue = next(x for x in queue["priority"] if x["product"] == "Signal Sprint")
        self.assertIn("ARTIFACTS_PRESENT", signal_queue["build_artifact_status"])
        self.assertEqual(signal_queue["current_identity_preview_status"], "GDK_IDENTITY_PREVIEW_PRESENT__DRY_RUN_ONLY__CAS_NOT_APPLIED")
        self.assertFalse(signal_queue["real_msixvc"])
        self.assertFalse(queue["e2e_pass"])
        self.assertEqual(queue["status"], "HOLD")

        self.assertEqual(overlay["pr165"]["head_sha"], HEAD165)
        self.assertEqual(overlay["pr190"]["head_sha"], HEAD190)
        self.assertEqual(overlay["status"], "HOLD")
        self.assertFalse(overlay["e2e_pass"])
        self.assertEqual(overlay["downstream_receipts"]["real_msix"], False)
        self.assertEqual(overlay["downstream_receipts"]["local_pull_receipt"], False)
        self.assertEqual(overlay["local_code_sync"]["status"], "NOT_OBSERVED__CLOUD_PASS_ONLY")
        self.assertEqual(overlay["store_upload_test"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(overlay["store_upload_test"]["dry_run_started"])
        self.assertFalse(overlay["safety"]["store_submission_allowed"])
        self.assertFalse(overlay["safety"]["certification_allowed"])
        self.assertFalse(overlay["safety"]["publish_allowed"])
        self.assertFalse(overlay["safety"]["merge_allowed"])
        self.assertFalse(overlay["safety"]["force_push_allowed"])


if __name__ == "__main__":
    unittest.main()
