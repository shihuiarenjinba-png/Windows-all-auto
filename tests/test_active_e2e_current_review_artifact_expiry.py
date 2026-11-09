"""Fail-closed review-head, artifact TTL and physical-local boundaries.

This test reads only the checked-in central ledger. It does not download expired
GitHub artifacts, invoke Partner Center, execute CAS, or assert physical QA.
"""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
APP_REVIEW = "886b9214b9cc79b35403ca168ca09df7a2e12404"
GAME_UI_REVIEW = "7f43da2b57b7e3ac3bf9ab22dbf43984c5ba6620"
GAME_SOURCE = "c058cbf7fe38e02d929c67d047d717ff74bd522e"
GAME_RUN_HEAD = "a1af3448cd2edeae5bd54cbaca486a53fd991944"
PRISM_REVIEW = "0878f48c79073596e30fed37a5703e0826389862"
PRISM_PR18_BUILD = "3c5a1e6837118a73609a0b9c9b7b54dfa4c14f0d"
PRISM_QA = "1a16b2a69083ca5698f29388c0eb59875a612450"
PRISM_OLD_GATE1 = "11417b75636ee18816028ffd5221884c4c9a9836"
FOCUS_ZIP = "06189361745a9cc175f1fe5bde27d758b71518ac1d2e955436939e3e7ed2a04d"


def errors(data):
    """Validate current evidence without promoting any gate from cloud metadata."""
    problems = []
    r = data["revision_review_reconciliation"]
    current = r["historical_four_lane_observation_20261102_2350"]
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

    require(app["head"] == APP_REVIEW and r["historical_image_review_observation_886b9214"]["current_review_head_sha"] == APP_REVIEW and r["historical_image_review_observation_886b9214"]["observation_snapshot_scope"].startswith("CURRENT_"), "APP_CURRENT_REVIEW_DRIFT")
    require(app["ci"] == [41449337747, 41449337454], "APP_CI_MISMATCH")
    require(app["score"] == 64 and app["real_buyers"] == 0 and not app["promoted"], "APP_MARKET_UNAUTHORIZED_PROMOTION")
    require(game["factory_review_pr"] == 16 and game["factory_review_head"] == GAME_UI_REVIEW, "GAME_PR16_NOT_CURRENT")
    require(game["factory_review_ci"] == [41443324856, 41443324988], "GAME_PR16_CI_MISMATCH")
    require(game["original_source_sha"] == GAME_SOURCE and data["active_product"]["source_sha"] == GAME_SOURCE, "GAME_IMMUTABLE_SOURCE_CHANGED")
    require(game["factory_artifact_run_head"] == GAME_RUN_HEAD and GAME_UI_REVIEW != GAME_RUN_HEAD, "GAME_REVIEW_SUBSTITUTED_FOR_ARTIFACT")
    require(obs["signal-sprint-ui-revision"]["current_review_head_sha"] == GAME_UI_REVIEW, "GAME_UI_OBSERVATION_STALE")
    require(obs["signal-sprint-ui-revision"]["old_artifact_sha_conflict"] == "HOLD_UNRESOLVED", "GAME_OLD_ARTIFACT_CONFLICT_LOST")
    require(not game["cas"] and not game["msixvc"] and not game["local_pass"], "GAME_UNVERIFIED_GATE_PROMOTED")
    require(prism["factory_pr"] == 19 and prism["head"] == PRISM_REVIEW and prism["qa_pr"] == 9 and prism["qa_head"] == PRISM_QA, "PRISM_CURRENT_PR18_QA9_MISMATCH")
    require(prism["artifact_id"] == 13142680551 and prism["artifact_run_id"] == 41444879105 and prism["historical_pr18_build"]["artifact_id"] == 13130487252 and prism["historical_pr18_build"]["artifact_run_id"] == 41422372852, "PRISM_ARTIFACT_PROVENANCE_CHANGED")
    require(prism["artifact_metadata_digest"] == "sha256:447c18e789acc1b1ca12c08bdce8b3cda030baf0c7abc70a452bde7e0c748800" and prism["historical_pr18_build"]["artifact_metadata_digest"] == "sha256:970288793436900405f9986f2da4c403345792fb7563398dfb21e9abaeaf3836", "PRISM_METADATA_DIGEST_CHANGED")
    require(obs["prism-route-3d-consumer-revision"]["historical_gate1_identity_return_commit"] == PRISM_OLD_GATE1, "PRISM_GATE1_HISTORY_CHANGED")
    require(obs["prism-route-3d-consumer-qa-pr9"]["current_review_head_sha"] == PRISM_QA and not obs["prism-route-3d-consumer-qa-pr9"]["prior_qa_pr6_is_current"] and prism["qa_ci"] == [41454758338, 41454758366], "OLD_PRISM_QA_MISLABELED_CURRENT")
    require(not prism["legacy_identity_cas_is_new_revision"] and not prism["new_cas"] and not prism["signed_msix"] and not prism["physical_gui"], "PRISM_OLD_IDENTITY_REUSED_OR_GATE_PROMOTED")
    require(not obs["prism-route-3d-consumer-revision"]["artifact_byte_sha256_rehashed_by_36"], "PRISM_METADATA_MISREPRESENTED_AS_BYTE_REHASH")
    require(prism["historical_pr18_build"]["review_head_sha"] == PRISM_PR18_BUILD and prism["historical_pr18_build"]["source_sha"] == PRISM_PR18_BUILD, "PRISM_PR18_IMMUTABLE_BUILD_PROVENANCE_CHANGED")
    require(prism["factory_quality_ci_artifact_count"] == 0 and prism["ci"] == [41444886971], "PRISM_PR19_CI_ARTIFACT_FALSE_PASS")
    require(prism["qa9_referenced_factory_artifact_id"] == 13142680551 and prism["pr19_new_pck_verified_by_36"] and prism["qa9_receipt_source_request_pck_sha_match"], "PRISM_QA9_REFERENCE_MISLABELED_BYTE_PROOF")
    require(not obs["prism-route-3d-first30s-pr19"]["pr18_artifact_is_pr19_build"] and not obs["prism-route-3d-first30s-pr19"]["legacy_gate1_identity_is_pr19_cas"], "PRISM_LEGACY_ARTIFACT_OR_CAS_PROMOTED")
    require(obs["prism-route-3d-first30s-pr19"]["qa9_factory_artifact_independently_rehashed_by_36"], "PRISM_QA9_INDEPENDENT_REHASH_LOST")
    require(game["hosted_gui_artifact_id"] == 13141335497 and not game["physical_gui_pass"], "GAME_HOSTED_GUI_MISLABELED_PHYSICAL")
    require(app["review_unsigned_exe_artifact_id"] == 13143283530 and not app["new_revision_promoted"], "APP_REVIEW_EXE_MISLABELED_APPROVED_SOURCE")
    require(data["revision_review_reconciliation"]["current_review_evidence_fail_closed"]["physical_local_processed"] == 0, "CURRENT_REVIEW_FAKE_LOCAL_PROCESSING")
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
        broken["revision_review_reconciliation"]["historical_four_lane_observation_20261102_2350"]["three_d"]["qa_head"] = "8aa8c20e1db0f2c30b91dd4e27cc141b1448d7d7"
        self.assertIn("PRISM_CURRENT_PR18_QA9_MISMATCH", errors(broken))

    def test_game_review_cannot_replace_immutable_source(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["historical_four_lane_observation_20261102_2350"]["game"]["original_source_sha"] = GAME_UI_REVIEW
        self.assertIn("GAME_IMMUTABLE_SOURCE_CHANGED", errors(broken))

    def test_cloud_batch_cannot_be_promoted_to_physical(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["historical_four_lane_observation_20261102_2350"]["windows_e2e"]["batch_local_processed"] = 4
        self.assertIn("CLOUD_BATCH_AS_LOCAL_SUCCESS", errors(broken))

    def test_old_prism_identity_cannot_be_new_cas(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["historical_four_lane_observation_20261102_2350"]["three_d"]["new_cas"] = True
        self.assertIn("PRISM_OLD_IDENTITY_REUSED_OR_GATE_PROMOTED", errors(broken))


    def test_pr18_artifact_cannot_be_current_pr19_build(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["historical_four_lane_observation_20261102_2350"]["three_d"]["artifact_id"] = 13130487252
        self.assertIn("PRISM_ARTIFACT_PROVENANCE_CHANGED", errors(broken))

    def test_pr19_quality_ci_without_artifact_cannot_be_pck_pass(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["historical_four_lane_observation_20261102_2350"]["three_d"]["factory_quality_ci_artifact_count"] = 1
        self.assertIn("PRISM_PR19_CI_ARTIFACT_FALSE_PASS", errors(broken))

    def test_qa9_independent_rehash_cannot_be_erased(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["historical_four_lane_observation_20261102_2350"]["three_d"]["pr19_new_pck_verified_by_36"] = False
        self.assertIn("PRISM_QA9_REFERENCE_MISLABELED_BYTE_PROOF", errors(broken))

    def test_game_hosted_gui_cannot_be_physical_pass(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["historical_four_lane_observation_20261102_2350"]["game"]["physical_gui_pass"] = True
        self.assertIn("GAME_HOSTED_GUI_MISLABELED_PHYSICAL", errors(broken))

    def test_app_unsigned_review_exe_cannot_be_promoted(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["historical_four_lane_observation_20261102_2350"]["app"]["new_revision_promoted"] = True
        self.assertIn("APP_REVIEW_EXE_MISLABELED_APPROVED_SOURCE", errors(broken))

    def test_legacy_prism_gate1_cannot_be_pr19_cas(self):
        broken = copy.deepcopy(self.ledger)
        broken["revision_review_reconciliation"]["observations"]["prism-route-3d-first30s-pr19"]["legacy_gate1_identity_is_pr19_cas"] = True
        self.assertIn("PRISM_LEGACY_ARTIFACT_OR_CAS_PROMOTED", errors(broken))


if __name__ == "__main__":
    unittest.main()
