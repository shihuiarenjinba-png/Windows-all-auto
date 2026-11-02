"""Fail-closed review-head, artifact TTL and physical-local boundaries.

This test reads only the checked-in central ledger. It does not download expired
GitHub artifacts, invoke Partner Center, execute CAS, or assert physical QA.
"""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
APP_REVIEW = "766480975ecbe5826bfb2c73060a662d30c708b1"
GAME_UI_REVIEW = "8927cd072d18c95a0940b4e0d7bca26359de20e9"
GAME_SOURCE = "c058cbf7fe38e02d929c67d047d717ff74bd522e"
GAME_RUN_HEAD = "a1af3448cd2edeae5bd54cbaca486a53fd991944"
PRISM_REVIEW = "3c5a1e6837118a73609a0b9c9b7b54dfa4c14f0d"
PRISM_QA = "87e174d59e99b1f3a6172e324ef35053a5ea6607"
PRISM_OLD_GATE1 = "11417b75636ee18816028ffd5221884c4c9a9836"
FOCUS_ZIP = "06189361745a9cc175f1fe5bde27d758b71518ac1d2e955436939e3e7ed2a04d"


def errors(data):
    """Validate current evidence without promoting any gate from cloud metadata."""
    problems = []
    r = data["revision_review_reconciliation"]
    current = r["current_four_lane_observation"]
    obs = r["observations"]
    game = current["game"]
    prism = current["three_d"]
    app = current["app"]
    win = current["windows_e2e"]
    focus = r["focus_artifact_expiry_current"]
    archive = r["batch4_artifact_archive_resume_contract"]
    gates = data["quality_gates"]
    cohort = data["rotation_cohorts"]["app_jobs"]

    def require(condition, name):
        if not condition:
            problems.append(name)

    require(app["head"] == APP_REVIEW and obs["offline-image-inventory-desk"]["current_review_head_sha"] == "b375fd9ed39ce5ceef635d9df169d7e23f2e2eac" and obs["offline-image-inventory-desk"]["observation_snapshot_scope"].startswith("HISTORICAL_"), "APP_CURRENT_REVIEW_DRIFT")
    require(app["ci"] == [41435219141, 41435219193], "APP_CI_MISMATCH")
    require(app["score"] == 64 and app["real_buyers"] == 0 and not app["promoted"], "APP_MARKET_UNAUTHORIZED_PROMOTION")
    require(game["factory_review_pr"] == 16 and game["factory_review_head"] == GAME_UI_REVIEW, "GAME_PR16_NOT_CURRENT")
    require(game["factory_review_ci"] == [41435749204, 41435749281], "GAME_PR16_CI_MISMATCH")
    require(game["original_source_sha"] == GAME_SOURCE and data["active_product"]["source_sha"] == GAME_SOURCE, "GAME_IMMUTABLE_SOURCE_CHANGED")
    require(game["factory_artifact_run_head"] == GAME_RUN_HEAD and GAME_UI_REVIEW != GAME_RUN_HEAD, "GAME_REVIEW_SUBSTITUTED_FOR_ARTIFACT")
    require(obs["signal-sprint-ui-revision"]["current_review_head_sha"] == GAME_UI_REVIEW, "GAME_UI_OBSERVATION_STALE")
    require(obs["signal-sprint-ui-revision"]["old_artifact_sha_conflict"] == "HOLD_UNRESOLVED", "GAME_OLD_ARTIFACT_CONFLICT_LOST")
    require(not game["cas"] and not game["msixvc"] and not game["local_pass"], "GAME_UNVERIFIED_GATE_PROMOTED")
    require(prism["factory_pr"] == 18 and prism["head"] == PRISM_REVIEW and prism["qa_pr"] == 9 and prism["qa_head"] == PRISM_QA, "PRISM_CURRENT_PR18_QA9_MISMATCH")
    require(prism["artifact_id"] == 13130487252 and prism["artifact_run_id"] == 41422372852, "PRISM_ARTIFACT_PROVENANCE_CHANGED")
    require(prism["artifact_metadata_digest"] == "sha256:970288793436900405f9986f2da4c403345792fb7563398dfb21e9abaeaf3836", "PRISM_METADATA_DIGEST_CHANGED")
    require(obs["prism-route-3d-consumer-revision"]["historical_gate1_identity_return_commit"] == PRISM_OLD_GATE1, "PRISM_GATE1_HISTORY_CHANGED")
    require(obs["prism-route-3d-consumer-qa-pr9"]["current_review_head_sha"] == PRISM_QA and not obs["prism-route-3d-consumer-qa-pr9"]["prior_qa_pr6_is_current"], "OLD_PRISM_QA_MISLABELED_CURRENT")
    require(not prism["legacy_identity_cas_is_new_revision"] and not prism["new_cas"] and not prism["signed_msix"] and not prism["physical_gui"], "PRISM_OLD_IDENTITY_REUSED_OR_GATE_PROMOTED")
    require(not obs["prism-route-3d-consumer-revision"]["artifact_byte_sha256_rehashed_by_36"], "PRISM_METADATA_MISREPRESENTED_AS_BYTE_REHASH")
    require(focus["artifact_id"] == 12807496604 and focus["github_current_artifacts_count"] == 0, "FOCUS_EXPIRED_ARTIFACT_INVENTORY_CHANGED")
    require(not focus["github_current_artifact_available"] and not focus["github_download_allowed"] and focus["github_status"].startswith("EXPIRED"), "EXPIRED_ACTIONS_ARTIFACT_MISLABELED_DOWNLOADABLE")
    require(focus["library_archive_preserved"] and focus["library_archive_sha256"] == FOCUS_ZIP, "FOCUS_LIBRARY_ARCHIVE_LOST")
    require(not focus["user_pc_archive_rehash_verified"], "FOCUS_CLOUD_ARCHIVE_MISLABELED_PHYSICAL")
    require(archive["archived_zip_ids"] == [12807496604, 12815845218, 12826068537, 12817339804], "APP_ARCHIVE_4_NOT_DISTINCT")
    require(len(archive["products"]) == 4 and archive["app_post_identity_count"] == 2 and archive["all_lane_post_identity_count"] == 3, "APP_VS_ALL_LANE_POST_SCOPE_MIXED")
    require([x["identity_state"] for x in archive["products"]] == ["POST_IDENTITY_READY", "POST_IDENTITY_READY", "PRE_IDENTITY_READY", "PRE_IDENTITY_READY"], "APP_IDENTITY_STATES_REGRESSED")
    require([x["status"] for x in cohort] == ["POST_IDENTITY_READY", "POST_IDENTITY_READY", "PRE_IDENTITY_READY", "PRE_IDENTITY_READY"], "APP_QUEUE_STATE_REGRESSED")
    require(not archive["products"][0]["github_artifact_download_allowed"], "FOCUS_EXPIRED_DOWNLOAD_IN_RESUME")
    require(win["batch_cloud_discovered"] == 4 and win["batch_github_identity_returned"] == 2 and win["batch_local_processed"] == 0 and win["batch_local_discovered"] == 0, "CLOUD_BATCH_AS_LOCAL_SUCCESS")
    require(win["next_index_is_cloud_logical"] and not win["task_scheduler_proof"] and not win["physical_local_sync"], "LOGICAL_CURSOR_OR_SCHEDULER_MISREPRESENTED")
    require(win["archive_cloud_verified"] == 4 and not win["focus_user_pc_archive_rehash"], "ARCHIVE_SCOPE_MIXED")
    require(not gates["local_source_code_sync_physical_pass"] and not gates["local_source_code_sync_scheduler_pass"], "LOCAL_SYNC_FALSE_PASS")
    require(not gates["real_msix_pass"] and not gates["real_gdk_msixvc_pass"] and not gates["github_backlog_real_product_pass"], "REAL_PACKAGE_FALSE_PASS")
    require(not gates["local_pull_pass"] and not gates["checker_pass"] and not gates["gui_qa_pass"] and not data["e2e_pass"], "PHYSICAL_E2E_FALSE_PASS")
    return problems


class CurrentFourLaneAndExpiredArtifactRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_checked_in_ledger_is_fail_closed(self):
        self.assertEqual(errors(self.ledger), [])

    def test_expired_actions_artifact_cannot_be_marked_downloadable(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["focus_artifact_expiry_current"]["github_download_allowed"] = True
        self.assertIn("EXPIRED_ACTIONS_ARTIFACT_MISLABELED_DOWNLOADABLE", errors(broken))

    def test_preserved_library_zip_cannot_be_claimed_as_user_pc_receipt(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["focus_artifact_expiry_current"]["user_pc_archive_rehash_verified"] = True
        self.assertIn("FOCUS_CLOUD_ARCHIVE_MISLABELED_PHYSICAL", errors(broken))

    def test_old_3d_qa_head_cannot_replace_pr9(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"]["qa_head"] = "8aa8c20e1db0f2c30b91dd4e27cc141b1448d7d7"
        self.assertIn("PRISM_CURRENT_PR18_QA9_MISMATCH", errors(broken))

    def test_game_review_cannot_replace_immutable_source(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["current_four_lane_observation"]["game"]["original_source_sha"] = GAME_UI_REVIEW
        self.assertIn("GAME_IMMUTABLE_SOURCE_CHANGED", errors(broken))

    def test_cloud_batch_cannot_be_promoted_to_physical(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["current_four_lane_observation"]["windows_e2e"]["batch_local_processed"] = 4
        self.assertIn("CLOUD_BATCH_AS_LOCAL_SUCCESS", errors(broken))

    def test_old_prism_identity_cannot_be_new_cas(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"]["new_cas"] = True
        self.assertIn("PRISM_OLD_IDENTITY_REUSED_OR_GATE_PROMOTED", errors(broken))


if __name__ == "__main__":
    unittest.main()
