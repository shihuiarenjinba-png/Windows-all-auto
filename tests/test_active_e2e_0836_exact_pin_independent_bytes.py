"""08:36 review evidence: exact QA83 source pin, independent bytes, and fail-closed physical/CAS boundaries."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
APP82 = "19f0bee05322d7e347513092e2e56d4d8a5a45d3"
QA83 = "05c667da0b04610bde38beed7b9bd4a5b7848165"
QA83_BASE = "97beffedec6f5657a4c3a66439e90ce68637ba53"
QA83_RUN_HEAD = "73b7c55bd133f63d783dd3ff97a157534e720348"
APP_EXE = "20e625d9f6bed782bf68c1df83496fadf81812dea075baabe93ee1a73c7bdba2"
GAME18 = "6ce4a9b47b55d865c33c7e0a50ffb18f5219c138"
GAME_SOURCE = "c058cbf7fe38e02d929c67d047d717ff74bd522e"
GAME_EXE = "352b198c40fe5888af41047bd897e4357327c296691ccb77c7dae6a691da7a86"
PRISM22 = "f4b458384243fdf379683ca793329614f61c9ead"
QA15 = "395ab342091c420e0ebdafd1b922dd9d3255539e"
PCK = "d1363805e4f899b0a895b6c4153f3fc902d548529c0cc47579b965666fcd98ec"
PRISM_EXE = "66b26ad96df7458ea917b632a73ac7c88bb058db24dbd11a457fd50435ab7b13"
PRISM_MANIFEST = "aea18d476ec7cc0a54c38a46fdbb78639d45ed3d0e55ec5814e46751cacdd2bb"


def validate(d):
    r = d["revision_review_reconciliation"]
    c = r["current_four_lane_observation"]
    live = r["latest_20261103_0836_review_qa_byte_reconciliation"]
    prior = r["historical_four_lane_observation_before_20261103_0836"]
    prior_qa = r["historical_post_handoff_candidates_before_20261103_0836"]
    candidates = r["post_handoff_newer_review_candidates_20261103_0736"]
    gates = r["cross_lane_gates"]
    # Historical 08:36 byte custody must not be overwritten by newer review revisions.
    archived = r["historical_four_lane_observation_before_20261103_1036"]
    app = archived["app"]
    game = archived["game"]
    prism = archived["three_d"]
    ao = r["observations"]["us-freelance-ledger-pr82-qa83"]
    go = r["observations"]["signal-sprint-current-artifact-pr18"]
    po = r["observations"]["prism-route-3d-consumer-qa-pr15"]

    assert d["updated_at_utc"] == c["observed_at_utc"] > r["observed_at_utc"] == live["observed_at_utc"]
    assert prior["observed_at_utc"] < live["observed_at_utc"]
    assert r["writer"] == c["writer"] == live["writer"] == "36_WINDOWS_E2E_ONLY"
    assert prior_qa["app"]["qa83_pinned_product_source_sha"] == QA83_BASE
    assert not prior_qa["app"]["qa83_is_current_pr82_exe_proof"]
    assert prior_qa["status"].startswith("SUPERSEDED")
    assert r["latest_20261103_0736_live_four_lane_reconciliation"]["historical_after_0836"]
    assert not d["e2e_pass"] and not d["sale_ready_windows_ux_gate"]["sale_ready"]

    a = candidates["app"]
    assert a["pr82_product_review_head"] == APP82
    assert a["qa83_review_head"] == QA83
    assert a["qa83_pinned_product_source_sha"] == APP82
    assert a["qa83_pinned_source_is_current_pr82_head"]
    assert a["qa83_is_current_pr82_exe_proof"]
    assert a["qa83_workflow_and_script_pin_verified"]
    assert a["qa83_base_sha"] == QA83_BASE != APP82
    assert not a["qa83_base_is_current_pr82_head"]
    assert a["qa83_base_compare_to_pr82"] == "DIVERGED_AHEAD_6_BEHIND_1__BLIND_MERGE_FORBIDDEN"
    assert a["qa83_exe_artifact_run_head"] == QA83_RUN_HEAD != QA83
    assert a["qa83_exe_artifact_run_id"] == 41535057027
    assert a["qa83_exe_artifact_id"] == ao["artifact_id"] == live["app"]["qa_artifact_id"] == 13183372299
    assert a["qa83_exe_artifact_digest"] == ao["artifact_zip_sha256"] == live["app"]["qa_zip_sha256"] == "sha256:c92ac7345ca09525810e01ca6f2f62203d8cb4bd59c200ac769eeb2753082a75"
    assert a["qa83_exe_artifact_independent_36_zip_crc_pass"]
    assert a["qa83_exe_member_independent_36_sha256"] == ao["independent_36_exe_sha256"] == live["app"]["independent_36_exe_sha256"] == APP_EXE
    assert ao["qa_workflow_source_pin"] == ao["qa_script_source_pin"] == ao["product_head_sha"] == APP82
    assert ao["qa_base_sha"] == QA83_BASE and ao["qa_base_diverged_from_product_head"]
    assert ao["hosted_gui_qa_pass"] and live["app"]["hosted_gui_pass"]
    assert c["app"]["us_freelance_ledger_pr80_is_historical_product_review_baseline"]
    assert app["us_freelance_ledger_product_review_head"] == APP82
    assert app["us_freelance_ledger_qa_product_source_pin"] == APP82
    assert app["us_freelance_ledger_qa_artifact_id"] == ao["artifact_id"] == 13183372299
    assert app["us_freelance_ledger_qa_exe_sha256"] == APP_EXE
    assert app["us_freelance_ledger_qa_base_diverged"]
    assert not app["us_freelance_ledger_qa_physical_human_pass"]
    assert not ao["approved_request_id"] and not ao["identity_cas"] and not ao["real_msix"]
    assert not a["qa83_approved_identity_binding"] and not a["qa83_physical_windows_125_150_human_pass"]
    assert not live["app"]["physical_human_pass"] and not live["app"]["approved_identity_binding"]
    assert a["market_fit"] if "market_fit" in a else True

    g = candidates["game"]
    assert game["factory_review_pr"] == 18 and game["factory_review_head"] == GAME18
    assert game["factory_review_ci"] == [41536644003, 41536644056]
    assert game["factory_review_compare"] == "PR17_15B666_TO_PR18_6CE4_AHEAD_13_BEHIND_0"
    assert g["pr18_artifact_head"] == go["review_head_sha"] == live["game"]["review_head"] == GAME18
    assert game["original_source_sha"] == go["immutable_original_source_sha"] == live["game"]["original_source_sha"] == GAME_SOURCE
    assert go["immutable_original_request_id"] == live["game"]["original_request_id"] == "game-signal-sprint-" + GAME_SOURCE
    assert live["game"]["registration_type"] == "GDK_GAME"
    assert game["physical_qa_exe_artifact_id"] == g["pr18_exe_artifact_id"] == go["exe_artifact_id"] == live["game"]["exe_artifact_id"] == 13185196046
    assert game["hosted_gui_artifact_id"] == g["pr18_gui_artifact_id"] == go["gui_artifact_id"] == live["game"]["gui_artifact_id"] == 13185220900
    assert go["exe_zip_sha256"] == live["game"]["exe_zip_sha256"] == "sha256:8fa5f5aad0f63abedc43b9c057f5ebb2c1e0350b0bf29055edda21cca797925a"
    assert go["gui_zip_sha256"] == live["game"]["gui_zip_sha256"] == "sha256:1ee46777af9d0afdc08d05800ea526710ccfef6b6419aad5e8d0f7f0af80f092"
    assert g["pr18_exe_sha256"] == go["independent_36_exe_member_sha256"] == live["game"]["independent_36_exe_sha256"] == GAME_EXE
    assert game["physical_qa_artifacts_independently_rehashed_by_36"]
    assert go["independent_36_exe_and_gui_zip_crc_pass"]
    assert not go["physical_user_pc_pass"] and not go["cas"] and not go["msixvc2"]
    assert not game["physical_qa_artifact_is_gdk_msixvc"] and not game["physical_qa_artifact_is_approved_staging_exe"]
    assert not game["physical_gui_pass"] and not game["msixvc"] and not game["cas"]
    assert not live["game"]["approved_gdk_staging"] and not live["game"]["physical_human_pass"]

    p = candidates["three_d"]
    assert prism["factory_pr"] == 22 and prism["source_sha"] == PRISM22
    assert prism["new_request_id"] == po["factory_request_id"] == live["three_d"]["request_id"] == "3d-prism-route-3d-f4b458384243"
    assert prism["qa_pr"] == 15 and prism["qa_head"] == po["review_head_sha"] == live["three_d"]["qa_head"] == QA15
    assert prism["previous_qa_review_head"] == "b56ef88f82f99626168bc487d4952d0285859ed7"
    assert prism["qa_review_compare"] == "QA14_B56EF88_TO_QA15_395AB342_AHEAD_6_BEHIND_0"
    assert p["qa15_factory_artifact_id"] == prism["artifact_id"] == po["factory_artifact_id"] == 13180284133
    assert p["qa15_artifact_id"] == prism["pr22_qa_artifact_id"] == po["qa_artifact_id"] == 13185037028
    assert p["qa15_36_independent_artifact_byte_rehash"] and po["independent_36_both_zip_crc_pass"]
    assert p["qa15_screenshots_independent_36_sha_size_verified"] == po["screenshot_sha_size_1024x768_count"] == live["three_d"]["independent_36_screenshot_sha_size_count"] == 8
    assert p["qa15_factory_pck_sha256"] == prism["pr22_factory_pck_sha256"] == po["pck_sha256"] == live["three_d"]["pck_sha256"] == PCK
    assert p["qa15_factory_exe_sha256"] == po["exe_sha256"] == live["three_d"]["exe_sha256"] == PRISM_EXE
    assert p["qa15_factory_manifest_sha256"] == po["manifest_sha256"] == live["three_d"]["manifest_sha256"] == PRISM_MANIFEST
    assert prism["pr22_export_artifact_independently_rehashed_by_36"]
    assert prism["pr22_pck_qa_independent_pass"] and prism["pr22_source_request_exe_pck_manifest_independent_match"]
    assert prism["qa14_historical_pr21_only"] and not prism["qa14_is_current_factory_pck_qa"]
    assert not prism["legacy_identity_cas_is_new_revision"] and not prism["new_cas"] and not prism["signed_msix"]
    assert not po["physical_windows_human_pass"] and not po["legacy_identity_is_new_cas"]
    assert not live["three_d"]["physical_human_pass"] and not live["three_d"]["signed_msix"]

    assert gates["prism_pr22_factory_independent_bytes_pass"] and gates["prism_pr22_independent_pck_qa_pass"]
    assert gates["app_pr82_qa83_unsigned_exe_independent_bytes_pass"] and gates["game_pr18_exe_gui_independent_bytes_pass"]
    assert not gates["prism_pr22_physical_human_pass"]
    assert not gates["app_pr82_qa83_physical_human_pass"] and not gates["game_pr18_physical_user_pc_pass"]
    w = live["windows_e2e"]
    assert w["app4_actions_artifacts_live"] == 0 and w["library_zip_preserved"] == 4
    assert w["user_pc_zip_readback"] == 0 and w["github_identity_returned"] == 2
    assert w["operator_pending"] == 2 and w["cloud_discovered"] == 4
    assert w["local_batch_discovered"] == 0 and w["physical_processed"] == 0
    assert w["local_code_sync"] == "CLOUD_PASS_ONLY"
    assert not w["scheduler_receipt"] and not w["real_msix"] and not w["gdk_msixvc"]
    assert not w["backlog"] and not w["checker"] and not w["install_gui"] and not w["e2e_pass"]


class ExactPinAndByteCustody(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_current_evidence_and_historical_boundary(self):
        validate(self.data)

    def reject(self, mutate):
        d = copy.deepcopy(self.data)
        mutate(d)
        with self.assertRaises(AssertionError):
            validate(d)

    def test_reject_qa83_old_base_as_product_pin(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["post_handoff_newer_review_candidates_20261103_0736"]["app"].__setitem__("qa83_pinned_product_source_sha", QA83_BASE))

    def test_reject_qa83_base_claimed_current(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["post_handoff_newer_review_candidates_20261103_0736"]["app"].__setitem__("qa83_base_is_current_pr82_head", True))

    def test_reject_qa83_false_divergence_clean(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["us-freelance-ledger-pr82-qa83"].__setitem__("qa_base_diverged_from_product_head", False))

    def test_reject_qa83_wrong_run_head(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["post_handoff_newer_review_candidates_20261103_0736"]["app"].__setitem__("qa83_exe_artifact_run_head", QA83))

    def test_reject_qa83_wrong_exe_artifact(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["app"].__setitem__("us_freelance_ledger_qa_artifact_id", 13180405918))

    def test_reject_qa83_false_identity_cas(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["us-freelance-ledger-pr82-qa83"].__setitem__("identity_cas", True))

    def test_reject_qa83_false_physical_dpi(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["post_handoff_newer_review_candidates_20261103_0736"]["app"].__setitem__("qa83_physical_windows_125_150_human_pass", True))

    def test_reject_game_old_pr17_as_live(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("factory_review_head", "15b666871eb6749133df671ca1b271d89ecdf3ae"))

    def test_reject_game_exe_gui_swap(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("physical_qa_exe_artifact_id", 13185220900))

    def test_reject_game_review_as_immutable_source(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("original_source_sha", GAME18))

    def test_reject_game_exe_as_gdk_package(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-current-artifact-pr18"].__setitem__("msixvc2", True))

    def test_reject_game_false_physical(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-current-artifact-pr18"].__setitem__("physical_user_pc_pass", True))

    def test_reject_pr21_pck_as_pr22(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("pr22_factory_pck_sha256", "a27c198ff4bdaa961780b4e42d5fb429c328c5bad0b5cb816e399c06e3fd8cb9"))

    def test_reject_qa14_as_current_pr22(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("qa_head", "b56ef88f82f99626168bc487d4952d0285859ed7"))

    def test_reject_wrong_pr22_request(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("new_request_id", "3d-prism-route-3d-066d9f51d58c"))

    def test_reject_false_eight_screenshot_proof(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["post_handoff_newer_review_candidates_20261103_0736"]["three_d"].__setitem__("qa15_screenshots_independent_36_sha_size_verified", 7))

    def test_reject_old_identity_new_pr22_cas(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("legacy_identity_cas_is_new_revision", True))

    def test_reject_qa15_software_as_physical(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr15"].__setitem__("physical_windows_human_pass", True))

    def test_reject_app4_library_as_live_actions(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0836_review_qa_byte_reconciliation"]["windows_e2e"].__setitem__("app4_actions_artifacts_live", 4))

    def test_reject_cloud_discovery_as_local(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0836_review_qa_byte_reconciliation"]["windows_e2e"].__setitem__("local_batch_discovered", 4))

    def test_reject_fake_scheduler_receipt(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0836_review_qa_byte_reconciliation"]["windows_e2e"].__setitem__("scheduler_receipt", True))

    def test_reject_false_e2e(self):
        self.reject(lambda d: d.__setitem__("e2e_pass", True))


if __name__ == "__main__":
    unittest.main()
