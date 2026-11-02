"""Live four-lane evidence is exact-HEAD metadata, never an inferred physical/CAS pass."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
GAME = "15b666871eb6749133df671ca1b271d89ecdf3ae"
GAME_PREV = "495d5dc8488d28f7b88373ba20897613e8ed47e7"
GAME_SOURCE = "c058cbf7fe38e02d929c67d047d717ff74bd522e"
QA14 = "b56ef88f82f99626168bc487d4952d0285859ed7"
QA13 = "79dc89f7d609e6f2a9f91543a0c0eadf5e8138fb"
PRISM_SOURCE = "066d9f51d58cfecb994665d5c31adb1156c38942"
APP79 = "5098217d60a3a03580f6006fc7c0bdd62fd30dd9"
IMAGE76 = "25a93052dad41e1844c31fe84384714764a5ac4f"
GAME_EXE_DIGEST = "sha256:b3a57f479b987a6b32ea52bc3ba00fdd97cfc49ba06cc6f4771f257d8da0b78b"
GAME_GUI_DIGEST = "sha256:6ac8047e6b3fb159240d78c438c84d766f381fc0f778ee1a7ec02011576607ad"
QA_RUNTIME_DIGEST = "sha256:3db9eb7bac6fbc90b9f1fffdf3134b353bf52e217c9d8f1925a6f4472c31015a"
QA_BINARY_DIGEST = "sha256:d1bc15ae028ec1ed8f2d9ecb4dd77d162a8233c3d8aadc7d0e530f920a91e18b"


def validate(d):
    r = d["revision_review_reconciliation"]
    c = r["current_four_lane_observation"]
    latest = r["latest_20261103_0636_live_four_lane_reconciliation"]
    old = r["historical_four_lane_observation_before_20261103_0636"]
    game = c["game"]
    game_obs = r["observations"]["signal-sprint-physical-qa-pr17"]
    game_old = r["historical_signal_sprint_pr17_observation_495d5dc"]
    qa = c["three_d"]
    qa_obs = r["observations"]["prism-route-3d-consumer-qa-pr14"]
    qa13 = r["observations"]["prism-route-3d-consumer-qa-pr13"]
    app = c["app"]
    app_obs = r["observations"]["us-freelance-ledger-pr79"]
    app4 = r["current_app4_actions_artifact_availability"]

    assert r["writer"] == c["writer"] == latest["writer"] == "36_WINDOWS_E2E_ONLY"
    assert r["observed_at_utc"] == c["observed_at_utc"] == latest["observed_at_utc"]
    assert d["updated_at_utc"] == latest["observed_at_utc"]
    assert latest["source"] == "GITHUB_EXACT_PR_HEAD_CI_AND_RUN_ARTIFACT_METADATA"
    assert latest["artifact_metadata_is_not_independent_bytes"]
    assert latest["history_boundary"].startswith("last_36_execution_AND_current_identity_projection_ARE_HISTORICAL")
    assert d["last_36_execution"]["observed_at_utc"] < latest["observed_at_utc"]

    assert game["factory_review_pr"] == game_obs["draft_pr"] == latest["game"]["pr"] == 17
    assert game["factory_review_head"] == game_obs["current_review_head_sha"] == latest["game"]["head"] == GAME
    assert game["previous_factory_review_head"] == game_obs["previous_review_head_sha"] == GAME_PREV
    assert old["game"]["factory_review_head"] == game_old["current_review_head_sha"] == GAME_PREV
    assert game["factory_review_compare"] == "PR17_495D5DC8_TO_15B66687_AHEAD_5_BEHIND_0"
    assert game["factory_review_ci"] == [41525954596, 41525954534]
    assert [e["run_id"] for e in game_obs["exact_head_ci"]] == game["factory_review_ci"]
    assert all(e["conclusion"] == "SUCCESS" for e in game_obs["exact_head_ci"])
    assert game["physical_qa_artifact_run_id"] == game_obs["current_run_id"] == 41525954534
    assert game["physical_qa_artifact_run_head"] == game_obs["current_run_head_sha"] == GAME
    assert game["physical_qa_exe_artifact_id"] == game_obs["current_exe_artifact_id"] == latest["game"]["exe_artifact_id"] == 13180405918
    assert game["hosted_gui_artifact_id"] == game_obs["current_gui_artifact_id"] == latest["game"]["gui_artifact_id"] == 13180545199
    assert game["physical_qa_exe_artifact_digest"] == game_obs["current_exe_artifact_digest"] == GAME_EXE_DIGEST
    assert game["hosted_gui_artifact_digest"] == game_obs["current_gui_artifact_digest"] == GAME_GUI_DIGEST
    assert game_obs["current_exe_artifact_expires_at_utc"] == "2026-11-16T21:13:16Z"
    assert game_obs["current_gui_artifact_expires_at_utc"] == "2026-11-16T21:13:20Z"
    assert game["original_source_sha"] == game_obs["immutable_original_source_sha"] == latest["game"]["original_source_sha"] == GAME_SOURCE
    assert game["original_request_id"] == game_obs["immutable_original_request_id"] == "game-signal-sprint-" + GAME_SOURCE
    assert game_obs["registration_type"] == latest["game"]["registration_type"] == "GDK_GAME"
    assert game["factory_artifact_run_head"] == old["game"]["factory_artifact_run_head"]
    assert game_obs["previous_live_exe_artifact_id"] == 13171328223
    assert game_obs["previous_live_gui_artifact_id"] == 13171178413
    assert not game["physical_qa_artifacts_independently_rehashed_by_36"]
    assert not game_obs["artifact_independent_download_and_rehash_by_36"]
    assert not game["physical_gui_pass"] and not game["local_pass"] and not game["cas"] and not game["msixvc"]
    assert not game["physical_qa_artifact_is_gdk_msixvc"] and not game["physical_qa_artifact_is_approved_staging_exe"]
    assert not game_obs["physical_user_pc"] and not game_obs["new_cas_applied"] and not game_obs["gdk_msixvc2"]
    assert not game["physical_qa_operator_receipt_present"]

    assert qa["factory_pr"] == 21 and qa["source_sha"] == qa["head"] == PRISM_SOURCE
    assert qa["new_request_id"] == "3d-prism-route-3d-066d9f51d58c"
    assert qa["artifact_id"] == 13155398069
    assert qa["qa_pr"] == qa_obs["draft_pr"] == latest["three_d"]["qa_pr"] == 14
    assert qa["qa_head"] == qa_obs["review_head_sha"] == latest["three_d"]["qa_head"] == QA14
    assert qa["previous_qa_review_head"] == qa_obs["previous_qa13_head_sha"] == QA13
    assert old["three_d"]["qa_head"] == QA13
    assert qa["qa_review_compare"] == "QA13_79DC89F7_TO_QA14_B56EF88F_AHEAD_4_BEHIND_0"
    assert qa["qa_ci"] == qa_obs["ci_runs"] == [41518642608, 41518642879]
    assert qa_obs["ci_conclusion"] == "SUCCESS_BOTH_RUNS"
    assert qa["qa14_runtime_artifact_id"] == qa_obs["hosted_runtime_artifact_id"] == 13177110679
    assert qa["qa14_binary_handoff_artifact_id"] == qa_obs["binary_handoff_artifact_id"] == 13175239913
    assert qa["qa14_runtime_artifact_digest"] == qa_obs["hosted_runtime_artifact_digest"] == QA_RUNTIME_DIGEST
    assert qa["qa14_binary_handoff_digest"] == qa_obs["binary_handoff_artifact_digest"] == QA_BINARY_DIGEST
    assert qa_obs["hosted_runtime_artifact_expires_at_utc"] == "2026-11-09T20:23:08Z"
    assert qa_obs["binary_handoff_artifact_expires_at_utc"] == "2026-11-09T20:23:05Z"
    assert qa_obs["factory_source_sha"] == PRISM_SOURCE and qa_obs["factory_artifact_id"] == 13155398069
    assert qa13["handoff_artifact_id"] == 13168745891 and not qa13["is_current_review_head"]
    assert qa_obs["qa13_historical_independent_36_byte_pass"]
    assert not qa_obs["qa14_independent_36_zip_rehash"] and not qa["qa14_independent_36_byte_rehash"]
    assert not qa_obs["new_factory_pck_produced_by_qa14"] and not qa["qa14_new_factory_pck"]
    assert not qa_obs["physical_operator_receipt_present"] and not qa_obs["physical_windows_human_pass"]
    assert not qa["new_cas"] and not qa["legacy_identity_cas_is_new_revision"]
    assert qa["legacy_identity_return_commit"] == "11417b75636ee18816028ffd5221884c4c9a9836"
    assert not qa["signed_msix"] and not qa["physical_gui"] and not qa["qa14_physical_human_pass"]

    assert app["image_pr"] == 76 and app["head"] == latest["app"]["image_head"] == IMAGE76
    assert app["score"] == latest["app"]["image_score"] == 64
    assert app["real_buyers"] == latest["app"]["image_buyers"] == 0
    assert not app["promoted"]
    assert app["us_freelance_ledger_pr"] == app_obs["draft_pr"] == 79
    assert app["us_freelance_ledger_head"] == app_obs["review_head_sha"] == latest["app"]["us_ledger_head"] == APP79
    assert app["us_freelance_ledger_ci"] == [41516173051]
    assert app["us_freelance_ledger_artifact_count"] == app_obs["workflow_artifact_count"] == 0
    assert app["us_freelance_ledger_market_fit"] == app_obs["market_fit"] == "HOLD"
    assert not app_obs["source_promoted"] and not app_obs["physical_windows_gui_verified"]
    assert not app_obs["consumer_purchase_verified"] and not app_obs["real_msix"]

    assert app4["github_actions_available_count"] == latest["windows_e2e"]["app4_actions_artifacts_live"] == 0
    assert app4["library_archives_preserved_count"] == latest["windows_e2e"]["library_zip_preserved"] == 4
    assert app4["user_pc_archive_rehash_verified_count"] == latest["windows_e2e"]["user_pc_zip_readback"] == 0
    assert app4["github_identity_returned_count"] == latest["windows_e2e"]["github_identity_returned"] == 2
    assert app4["github_identity_pending_count"] == latest["windows_e2e"]["operator_pending"] == 2
    assert app4["local_batch_discovered_count"] == latest["windows_e2e"]["local_batch_discovered"] == 0
    assert app4["cloud_discovered_count"] == latest["windows_e2e"]["cloud_discovered"] == 4
    assert d["multi_product_partner_center_batch_4"]["processed_count"] == latest["windows_e2e"]["physical_processed"] == 0
    assert not app4["allow_actions_redownload"] and not app4["allow_regeneration"]
    assert not app4["allow_cas"] and not app4["allow_store_operations"]
    assert all(x["github_run_artifact_list_count"] == 0 and not x["github_artifact_download_allowed"] for x in app4["records"])
    assert latest["windows_e2e"]["local_code_sync"] == "CLOUD_PASS_ONLY"
    assert not d["quality_gates"]["local_source_code_sync_physical_pass"]
    assert not d["quality_gates"]["local_source_code_sync_scheduler_pass"]
    assert not r["cross_lane_gates"]["game_pr17_independent_36_exe_bytes_pass"]
    assert not r["cross_lane_gates"]["game_pr17_gdk_msixvc_pass"]
    assert not r["cross_lane_gates"]["prism_pr21_qa14_physical_human_pass"]
    assert not latest["windows_e2e"]["scheduler_receipt"]
    assert not latest["windows_e2e"]["real_msix"] and not latest["windows_e2e"]["gdk_msixvc"]
    assert not latest["windows_e2e"]["backlog"] and not latest["windows_e2e"]["checker"]
    assert not latest["windows_e2e"]["install_gui"] and not latest["windows_e2e"]["e2e_pass"]
    assert not d["e2e_pass"] and not d["sale_ready_windows_ux_gate"]["sale_ready"]


class LiveFourLaneBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_exact_live_head_and_historical_evidence(self):
        validate(self.data)

    def reject(self, change):
        altered = copy.deepcopy(self.data)
        change(altered)
        with self.assertRaises(AssertionError):
            validate(altered)

    def test_reject_old_game_head_as_current(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("factory_review_head", GAME_PREV))

    def test_reject_old_game_exe_as_current(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("physical_qa_exe_artifact_id", 13175054438))

    def test_reject_old_game_gui_as_current(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-physical-qa-pr17"].__setitem__("current_gui_artifact_id", 13175454592))

    def test_reject_swapped_game_exe_gui(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("hosted_gui_artifact_id", 13180405918))

    def test_reject_wrong_game_run_head(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-physical-qa-pr17"].__setitem__("current_run_head_sha", GAME_PREV))

    def test_reject_wrong_game_digest(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("physical_qa_exe_artifact_digest", GAME_GUI_DIGEST))

    def test_reject_review_head_rebinding_immutable_source(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("original_source_sha", GAME))

    def test_reject_exe_claimed_as_gdk(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("physical_qa_artifact_is_gdk_msixvc", True))

    def test_reject_unverified_game_byte_pass(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-physical-qa-pr17"].__setitem__("artifact_independent_download_and_rehash_by_36", True))

    def test_reject_old_qa13_as_current(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("qa_head", QA13))

    def test_reject_qa13_binary_as_qa14(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("qa14_binary_handoff_artifact_id", 13168745891))

    def test_reject_qa14_claimed_new_factory_pck(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr14"].__setitem__("new_factory_pck_produced_by_qa14", True))

    def test_reject_qa14_metadata_claimed_byte_verified(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("qa14_independent_36_byte_rehash", True))

    def test_reject_qa14_false_physical_pass(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr14"].__setitem__("physical_windows_human_pass", True))

    def test_reject_old_identity_as_new_cas(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("new_cas", True))

    def test_reject_us_ledger_wrong_head(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["app"].__setitem__("us_freelance_ledger_head", IMAGE76))

    def test_reject_us_ledger_fabricated_artifact(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["us-freelance-ledger-pr79"].__setitem__("workflow_artifact_count", 1))

    def test_reject_image_false_market_fit(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["app"].__setitem__("score", 90))

    def test_reject_library_zip_as_live_actions_artifact(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_app4_actions_artifact_availability"].__setitem__("github_actions_available_count", 4))

    def test_reject_cloud_cursor_as_local(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0636_live_four_lane_reconciliation"]["windows_e2e"].__setitem__("physical_processed", 4))

    def test_reject_fake_scheduler_receipt(self):
        self.reject(lambda d: d["quality_gates"].__setitem__("local_source_code_sync_scheduler_pass", True))

    def test_reject_false_e2e(self):
        self.reject(lambda d: d.__setitem__("e2e_pass", True))


if __name__ == "__main__":
    unittest.main()
