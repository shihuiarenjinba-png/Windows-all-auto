import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261127_1500.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261127_1500.json"


class CurrentE2EHandoffReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue = json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_pr165_live_head_and_exact_head_ci_are_directly_pinned(self):
        p = self.overlay["pr165"]
        self.assertEqual(p["head_sha"], "07cb543816c7432edcf45465ae0763e16917aecc")
        self.assertEqual(p["parent_sha"], "6afe5ec89a440880066bee43a61f596a5939761d")
        self.assertEqual([x["run_id"] for x in p["exact_head_ci"]],
                         [45899687437, 45899687528, 45899687545])
        self.assertTrue(all(x["head_sha"] == p["head_sha"] and x["conclusion"] == "success"
                            for x in p["exact_head_ci"]))
        self.assertFalse(p["latest_commit_changed_product_code"])

    def test_pr207_is_stacked_on_exact_pr165_head_and_ci_passed(self):
        p = self.overlay["pr207"]
        self.assertEqual(p["base_sha"], self.overlay["pr165"]["head_sha"])
        self.assertEqual(p["head_sha"], "e175ce531da038e7521bf768879fa514c3f70f64")
        self.assertEqual(p["compare"], {"status": "ahead", "ahead_by": 1, "behind_by": 0, "total_commits": 1})
        self.assertEqual([x["run_id"] for x in p["exact_head_ci"]],
                         [45946800586, 45946800590, 45946800577])
        self.assertTrue(all(x["head_sha"] == p["head_sha"] and x["conclusion"] == "success"
                            for x in p["exact_head_ci"]))
        self.assertFalse(p["real_product_msix_received"])
        self.assertFalse(p["physical_local_pull_receipt"])
        self.assertFalse(p["local_checker_receipt"])
        self.assertFalse(p["local_gui_install_receipt"])
        self.assertFalse(p["product_e2e_pass"])

    def test_pr161_and_pr171_remain_ci_only_and_store_gates_hold(self):
        self.assertEqual(self.overlay["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertTrue(all(x["conclusion"] == "success" for x in self.overlay["pr161"]["exact_head_ci"]))
        self.assertEqual(self.overlay["pr171"]["head_sha"], "764721021f13be96364529650b44fb439770bac9")
        self.assertTrue(self.overlay["pr171"]["store_upload_bridge_present"])
        self.assertEqual(self.overlay["pr171"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(self.overlay["pr171"]["dry_run_started"])
        self.assertFalse(self.overlay["pr171"]["live_started"])
        self.assertEqual(self.overlay["windows_automator_pin"]["commit_sha"],
                         "d3b8ed4ae7762a69d3fe2a90b64aa86ee938259b")
        self.assertEqual(self.overlay["windows_automator_pin"]["conclusion"], "success")

    def test_focus_historical_identity_and_request_cannot_be_reused(self):
        f = self.overlay["products"]["focus_session_desk"]
        self.assertEqual(f["current_source_sha"], "b6b69464a9c7450489338bc7542fd22cf190ed42")
        self.assertEqual(f["identity"]["historical_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertNotEqual(f["identity"]["historical_source_sha"], f["current_source_sha"])
        self.assertFalse(f["identity"]["current_source_reuse_allowed"])
        self.assertEqual(f["current_source_request"]["source_sha"],
                         "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertFalse(f["current_source_request"]["source_matches_current_pr_head"])
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])
        self.assertEqual(f["store_assets"]["owner"], "00")
        self.assertFalse(f["store_assets"]["regeneration_or_modification_by_36"])
        self.assertEqual(f["store_assets"]["Square44"]["sha256"],
                         "3fbdcd610f6781b72308755c6f92b1fdaef0592bab51c612556e5b8b95c1ee46")

    def test_file_current_source_has_no_approved_identity_or_version(self):
        f = self.overlay["products"]["file_integrity_ledger"]
        self.assertEqual(f["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertFalse(f["identity"]["current_source_approved_identity_present"])
        self.assertTrue(f["identity"]["current_source_store_directory_contains_only_assets"])
        self.assertFalse(f["identity"]["current_source_reuse_allowed"])
        self.assertEqual(f["current_source_request"]["status"], "DRY_RUN")
        self.assertEqual(f["current_source_request"]["source_sha"], f["current_source_sha"])
        self.assertIsNone(f["package_version"])
        self.assertFalse(f["real_msix"])
        self.assertEqual(f["msix_export"]["status"], "SKIPPED_NO_ARTIFACT")
        self.assertEqual(f["store_assets"]["owner"], "00")
        self.assertFalse(f["store_assets"]["regeneration_or_modification_by_36"])

    def test_every_downstream_product_gate_remains_false(self):
        for name in ("focus_session_desk", "file_integrity_ledger"):
            p = self.overlay["products"][name]
            self.assertFalse(p["real_msix"])
            self.assertFalse(p["github_backlog_receipt"])
            self.assertFalse(p["local_pull_receipt"])
            self.assertFalse(p["windows_checker_receipt"])
            self.assertFalse(p["local_gui_install_receipt"])
            self.assertFalse(p["product_e2e_pass"])
        self.assertEqual(self.overlay["first_unconnected_interval"]["status"],
                         "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        self.assertFalse(self.overlay["transport_contract"]["real_product_msix_received"])
        self.assertFalse(self.overlay["partner_center"]["version_inferred"])
        self.assertFalse(self.overlay["partner_center"]["partner_center_write_performed"])
        self.assertFalse(self.overlay["safety"]["store_submission_allowed"])
        self.assertFalse(self.overlay["safety"]["certification_allowed"])
        self.assertFalse(self.overlay["safety"]["publish_allowed"])
        self.assertFalse(self.overlay["safety"]["merge_allowed"])
        self.assertFalse(self.overlay["safety"]["force_push_allowed"])

    def test_new_queue_supersedes_stale_queue_and_tracks_current_heads(self):
        q = self.queue
        self.assertEqual(q["source_observation"], self.overlay["path"])
        self.assertEqual(q["supersedes_current_snapshot"],
                         "ops/completion_rush_queue_20261127_0631.json")
        self.assertEqual(q["pr165"]["head_sha"], self.overlay["pr165"]["head_sha"])
        self.assertEqual(q["pr207"]["base_sha"], self.overlay["pr165"]["head_sha"])
        self.assertEqual(q["pr207"]["head_sha"], self.overlay["pr207"]["head_sha"])
        self.assertEqual(q["priority"][0]["current_source_sha"],
                         self.overlay["products"]["focus_session_desk"]["current_source_sha"])
        self.assertEqual(q["priority"][1]["current_source_sha"],
                         self.overlay["products"]["file_integrity_ledger"]["current_source_sha"])
        self.assertFalse(q["new_product_generation_allowed"])
        self.assertFalse(q["e2e_pass"])
        self.assertFalse(q["store_submission_allowed"])
        self.assertFalse(q["certification_allowed"])
        self.assertFalse(q["publish_allowed"])


if __name__ == "__main__":
    unittest.main()
