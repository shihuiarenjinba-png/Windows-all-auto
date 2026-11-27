import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops/active_e2e_handoff_overlay_20261127_1432.json"
QUEUE = ROOT / "ops/completion_rush_queue_20261116.json"

PR165_HEAD = "07cb543816c7432edcf45465ae0763e16917aecc"
PR165_PARENT = "6afe5ec89a440880066bee43a61f596a5939761d"


class CurrentLiveReconciliation20261127_1432Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_pr165_head_and_three_exact_head_runs_are_current(self):
        o = self.overlay
        p = o["pr165"]
        self.assertEqual(p["head_sha_at_observation"], PR165_HEAD)
        self.assertEqual(p["parent_sha"], PR165_PARENT)
        self.assertEqual(p["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in p["exact_head_ci"]],
                         [45899687437, 45899687528, 45899687545])
        self.assertTrue(all(x["head_sha"] == PR165_HEAD and x["conclusion"] == "success"
                            for x in p["exact_head_ci"]))
        self.assertEqual(o["post_observation_verification"]["latest_pr165_head_sha"], PR165_HEAD)
        self.assertFalse(o["post_observation_verification"]["product_code_changed_since_84f9"])
        self.assertEqual(o["status"], "HOLD")
        self.assertIs(o["e2e_pass"], False)

    def test_restaked_pr192_to_pr196_chain_is_sequential_and_exact_head_green(self):
        chain = self.overlay["transport_contract"]["restack_chain_20261127"]
        expected = {
            "pr207": ("07cb543816c7432edcf45465ae0763e16917aecc",
                      "e175ce531da038e7521bf768879fa514c3f70f64", [45946800586, 45946800590, 45946800577]),
            "pr208": ("e175ce531da038e7521bf768879fa514c3f70f64",
                      "a5e9872e5303d070180c93a9df0724946fb62cba", [45947331667]),
            "pr209": ("a5e9872e5303d070180c93a9df0724946fb62cba",
                      "0a5ddd2755dbfee981c1eae671b6fa7655351465", [45947456459]),
            "pr210": ("0a5ddd2755dbfee981c1eae671b6fa7655351465",
                      "655dbb4f1865069a5ff7dd5b116426702e42cfbb", [45947551430]),
        }
        for key, (parent, head, run_ids) in expected.items():
            row = chain[key]
            self.assertEqual(row["parent_sha"], parent)
            self.assertEqual(row["head_sha"], head)
            self.assertTrue(row["exact_head_ci_status"].startswith("PASS"))
            self.assertEqual([x["run_id"] for x in row["exact_head_ci"]], run_ids)
            self.assertTrue(all(x["head_sha"] == head and x["conclusion"] == "success"
                                for x in row["exact_head_ci"]))
        self.assertEqual(self.overlay["transport_contract"]["status"],
                         "IMPLEMENTED_FAIL_CLOSED__EXACT_HEAD_CI_PASS")
        self.assertFalse(self.overlay["transport_contract"]["real_product_msix_received"])

    def test_focus_source_request_drift_is_explicit_and_identity_is_historical_only(self):
        f = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(f["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(f["current_source_compare"]["ahead_by"], 4)
        self.assertEqual(f["current_source_compare"]["changed_files"],
                         ["products/focus-session-desk/tests/windows_exe_gui_smoke.py"])
        self.assertFalse(f["current_source_compare"]["product_code_changed"])
        self.assertEqual(f["current_source_request"]["source_sha"],
                         "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertFalse(f["current_source_request"]["source_matches_current_pr_head"])
        self.assertFalse(f["current_source_request"]["request_submitted"])
        self.assertEqual(f["identity"]["historical_source_sha"],
                         "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertFalse(f["identity"]["current_source_reuse_allowed"])
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])
        gui = f["latest_native_windows_gui"]
        self.assertEqual(gui["head_sha"], f["current_source_sha"])
        self.assertEqual(gui["run_id"], 45895951025)
        self.assertEqual(gui["artifact_id"], 15153413358)
        self.assertTrue(gui["human_visual_review_required"])
        self.assertEqual(gui["owner_visual_signoff_status"], "PENDING")

    def test_file_integrity_request_matches_source_but_identity_and_version_are_missing(self):
        f = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(f["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(f["current_source_request"]["source_sha"], f["current_source_sha"])
        self.assertTrue(f["current_source_request"]["source_matches_current_pr_head"])
        self.assertFalse(f["identity"]["current_source_approved_identity_present"])
        self.assertFalse(f["identity"]["current_source_reuse_allowed"])
        self.assertEqual(f["identity"]["historical_identity_source_sha"],
                         "d1108d12f7d1697af30400f97c7db39cba5e6791")
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])
        self.assertEqual(f["latest_native_windows_gui"]["run_id"], 45422895435)
        self.assertEqual(f["latest_native_windows_gui"]["human_visual_review_status"], "PASS")

    def test_local_code_sync_is_not_claimed_from_cloud_only_evidence(self):
        sync = self.overlay["local_code_sync"]
        self.assertEqual(sync["status"], "NOT_OBSERVED__CLOUD_PASS_ONLY")
        self.assertEqual(sync["exact_three_sha_tuple"], {
            "local_sync_tooling_commit": "b962910095adcdbcee7fb0c1ef12e4fb3575c9e8",
            "signal_sprint_source_sha": "1a349faa41663c417c40710140a4d50c79b62b78",
            "prism_route_3d_source_sha": "b03ce7b16c3f75c04fe20fdda224c45849eeba0d",
        })
        self.assertTrue(sync["source_ref_readbacks"]["signal_sprint"]["matches"])
        self.assertTrue(sync["source_ref_readbacks"]["prism_route_3d"]["matches"])
        self.assertFalse(sync["physical_user_windows_session_available"])
        self.assertFalse(sync["powershell_available"])
        self.assertFalse(sync["windows_task_scheduler_available"])
        self.assertFalse(sync["local_code_sync_pass"])
        self.assertIsNone(sync["exact_three_sha_receipt"])
        self.assertIsNone(sync["idempotent_reuse_receipt"])
        self.assertIsNone(sync["task_scheduler_receipt"])

    def test_queue_points_to_new_overlay_and_store_safety_remains_false(self):
        q = self.queue
        self.assertEqual(q["current_status_reconciliation_file"],
                         "ops/active_e2e_handoff_overlay_20261127_1432.json")
        self.assertEqual(q["previous_current_status_reconciliation_file"],
                         "ops/active_e2e_handoff_overlay_20261126_203204.json")
        self.assertEqual(q["latest_pr165_head_after_reconciliation"], PR165_HEAD)
        self.assertEqual(q["latest_pr165_exact_head_ci_run_ids"],
                         [45899687437, 45899687528, 45899687545])
        self.assertEqual(q["current_status_reconciliation_20261127_1432"]["focus_source_sha"],
                         "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertFalse(q["current_status_reconciliation_20261127_1432"]["focus_request_matches_current_source"])
        self.assertEqual(q["priority"][0]["current_source_sha"],
                         "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(q["priority"][0]["current_source_request"]["source_sha"],
                         "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(q["store_upload_test_eligibility_current_20261127_1432"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(q["store_upload_test_eligibility_current_20261127_1432"]["dry_run_started"])
        self.assertFalse(q["store_submission_allowed"])
        self.assertFalse(q["certification_allowed"])
        self.assertFalse(q["publish_allowed"])
        self.assertFalse(q["e2e_pass"])


if __name__ == "__main__":
    unittest.main()
