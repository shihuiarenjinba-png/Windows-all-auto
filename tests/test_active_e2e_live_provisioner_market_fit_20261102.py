"""Current-only GAME head and market-fit threshold regression, no local/Store side effects."""
import copy
import json
from pathlib import Path
import unittest

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
LIVE_HEAD = "b53f89fc0b59871ba8f5cc7c62703bfdcc20d53a"
PRIOR_HEAD = "d77cf88977db943d83cf898aae5bbf027e5aed90"
INTERMEDIATE_HEAD = "b550faba73b16d64d85f7ef56f0080429068f00a"
SOURCE = "c058cbf7fe38e02d929c67d047d717ff74bd522e"
ORIGINAL_REQUEST = "game-signal-sprint-" + SOURCE
NEW_REQUEST = ORIGINAL_REQUEST + "-reissue-sprint-41361263698-41361263698"
CI_RUN = 41412494345


def classify_market(score, *, physical_windows=False, human_qa=False):
    """Classification only: never grants Store publication or package authorization."""
    if not isinstance(score, int) or isinstance(score, bool) or score < 0 or score > 100:
        raise ValueError("invalid market-fit score")
    if score < 80:
        return "MARKET_FIT_HOLD"
    if score < 90:
        return "PACKAGE_CANDIDATE_ONLY"
    return ("SALE_READY_CANDIDATE_ONLY" if physical_windows and human_qa
            else "HOLD_PHYSICAL_WINDOWS_OR_HUMAN_QA")


def assert_current_game_contract(data):
    active = data["active_product"]
    head_paths = [
        active["provisioner_head_observed"],
        active["provisioner_package_safety"]["head_sha"],
        active["provisioner_identity_resume"]["head_sha"],
        active["provisioner_game_gdk_pr"]["head_sha"],
        active["provisioner_game_gdk_pr"]["new_lineage_contract"]["current_head"],
        active["local_identity_return_worker"]["required_provisioner_sha"],
        data["latest_provisioner_heads_observed"]["game"]["sha"],
        data["multi_product_identity_scheduler"]["pre_identity_queue"]["provisioner_head_observed"],
        data["last_36_execution"]["game_provisioner_pr10_current"]["head_sha"],
        data["revision_review_reconciliation"]["observations"]["signal-sprint"]["current_review_head_sha"],
    ]
    if any(h != LIVE_HEAD for h in head_paths):
        raise AssertionError("current GAME PR10 HEAD inconsistent")
    if active["source_sha"] != SOURCE or active["request_id"] != ORIGINAL_REQUEST:
        raise AssertionError("immutable original source/request changed")
    new = active["provisioner_game_gdk_pr"]["new_lineage_contract"]
    if new["new_request_id"] != NEW_REQUEST or new["new_request_id"] == active["request_id"]:
        raise AssertionError("new lineage request collision")
    if new["new_build_artifact_id"] != 13105352227:
        raise AssertionError("new lineage artifact mismatched")
    if new["cas_applied"] or new["gdk_msixvc_built"] or new["ready_for_sdk"]:
        raise AssertionError("CHECK-ONLY must never promote CAS/SDK/package")
    if data["e2e_pass"] or active["cas_returned"]:
        raise AssertionError("unproven E2E/CAS promoted")
    if data["latest_provisioner_heads_observed"]["game"]["ci_run_id"] != CI_RUN:
        raise AssertionError("CI does not correspond to current HEAD")


class CurrentLiveProvisionerAndMarketPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_live_head_and_distinct_lineages(self):
        data = self.data
        assert_current_game_contract(data)
        active = data["active_product"]
        self.assertEqual(active["provisioner_head_observation"]["previous_observed_head"], PRIOR_HEAD)
        self.assertEqual(active["provisioner_game_gdk_pr"]["new_lineage_contract"]["intermediate_head_sha"], INTERMEDIATE_HEAD)
        self.assertEqual(active["provisioner_game_gdk_pr"]["new_lineage_contract"]["latest_compare"], "AHEAD_4_BEHIND_0_FROM_D77CF889")
        self.assertEqual(active["provisioner_game_gdk_pr"]["new_lineage_contract"]["compare_to_prior_head"], "AHEAD_4_BEHIND_0_FROM_D77CF889")
        self.assertEqual(active["provisioner_game_gdk_pr"]["new_lineage_contract"]["assembly_plan_result"], "CHECK_ONLY_EXIT_2__NOT_READY_FOR_SDK__CAS_NOT_APPLIED__NO_MSIXVC")
        self.assertEqual(active["provisioner_game_gdk_pr"]["ci_run_id"], CI_RUN)
        self.assertEqual(active["original_exe_artifact_audit"]["original_artifact_availability"], "EXPIRED_404__ORIGINAL_ZIP_NOT_PRESERVED")
        self.assertFalse(active["original_exe_artifact_audit"]["authority_reconciled"])
        self.assertIn("e9ae4669f6739d34cad63764767328a3c796a5f9", "\n".join(active["historical_local_commands_20261027"]))
        self.assertNotIn(PRIOR_HEAD, "\n".join(active["local_commands"]))

    def test_cross_lineage_tampering_is_rejected(self):
        for mutation in ("head", "source", "request", "cas", "sdk", "ci"):
            bad = copy.deepcopy(self.data)
            active = bad["active_product"]
            if mutation == "head":
                bad["latest_provisioner_heads_observed"]["game"]["sha"] = PRIOR_HEAD
            elif mutation == "source":
                active["source_sha"] = LIVE_HEAD
            elif mutation == "request":
                active["provisioner_game_gdk_pr"]["new_lineage_contract"]["new_request_id"] = ORIGINAL_REQUEST
            elif mutation == "cas":
                active["provisioner_game_gdk_pr"]["new_lineage_contract"]["cas_applied"] = True
            elif mutation == "sdk":
                active["provisioner_game_gdk_pr"]["new_lineage_contract"]["ready_for_sdk"] = True
            else:
                bad["latest_provisioner_heads_observed"]["game"]["ci_run_id"] = 41371345733
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                assert_current_game_contract(bad)

    def test_market_fit_threshold_and_historical_scope(self):
        market = self.data["post_identity_pipeline"]
        policy = market["market_fit_policy_current"]
        self.assertEqual(policy["formal_package_min_score"], 80)
        self.assertIn("SCORE_GE_80", market["market_fit_rule"])
        self.assertNotIn("SCORE_GE_70", market["market_fit_rule"])
        self.assertIn("SCORE_GE_70", self.data["last_36_execution"]["market_fit_gate"]["scope"])
        for score, expected in ((0, "MARKET_FIT_HOLD"), (64, "MARKET_FIT_HOLD"),
                                (70, "MARKET_FIT_HOLD"), (79, "MARKET_FIT_HOLD"),
                                (80, "PACKAGE_CANDIDATE_ONLY"), (89, "PACKAGE_CANDIDATE_ONLY"),
                                (90, "HOLD_PHYSICAL_WINDOWS_OR_HUMAN_QA"),
                                (100, "HOLD_PHYSICAL_WINDOWS_OR_HUMAN_QA")):
            with self.subTest(score=score):
                self.assertEqual(classify_market(score), expected)
        self.assertEqual(classify_market(90, physical_windows=True, human_qa=True),
                         "SALE_READY_CANDIDATE_ONLY")
        self.assertEqual(classify_market(90, physical_windows=True),
                         "HOLD_PHYSICAL_WINDOWS_OR_HUMAN_QA")
        self.assertEqual(classify_market(90, human_qa=True),
                         "HOLD_PHYSICAL_WINDOWS_OR_HUMAN_QA")
        for bad_score in (-1, 101, 80.5, True):
            with self.subTest(bad_score=bad_score), self.assertRaises(ValueError):
                classify_market(bad_score)

    def test_image_and_local_gate_remain_hold(self):
        data = self.data
        image = data["revision_review_reconciliation"]["observations"]["offline-image-inventory-desk"]
        self.assertEqual(image["score"], 64)
        self.assertEqual(image["independent_buyers_completed"], 0)
        self.assertFalse(image["current_review_revision_promoted"])
        self.assertIsNone(image["new_revision_request_id"])
        batch = data["multi_product_partner_center_batch_4"]
        self.assertEqual(batch["cloud_preflight_discovered_count"], 4)
        self.assertEqual(batch["processed_count"], 0)
        self.assertNotEqual(batch["trigger_proof"], "SCHEDULED_TRIGGER_PROVEN")
        local = data["local_source_code_sync"]["physical_evidence_handoff"]
        self.assertEqual(local["status"], "NOT_LOCAL_PASS")
        self.assertFalse(local["physical_windows_verified"])
        self.assertFalse(local["task_scheduler_verified"])
        self.assertEqual(len(local["target_shas"]), 3)
        self.assertFalse(data["quality_gates"]["local_source_code_sync_physical_pass"])
        self.assertFalse(data["quality_gates"]["local_source_code_sync_scheduler_pass"])
        self.assertFalse(data["sale_ready_windows_ux_gate"]["sale_ready"])
        self.assertEqual(data["sale_ready_windows_ux_gate"]["verdict"], "NO")


if __name__ == "__main__":
    unittest.main()
