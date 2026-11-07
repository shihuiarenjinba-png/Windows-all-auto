"""Historical 07:36 snapshot; newer 08:36 live evidence has separate tests."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
APP80 = "ffbff04f642634093468cbf7267facd6a075ddb3"
APP79 = "5098217d60a3a03580f6006fc7c0bdd62fd30dd9"
PR22 = "f4b458384243fdf379683ca793329614f61c9ead"
PR21 = "066d9f51d58cfecb994665d5c31adb1156c38942"
REQUEST22 = "3d-prism-route-3d-f4b458384243"
DIGEST22 = "sha256:71ff9fca61ea310939f777a8c29cf93a57f25e19237ceb0fe1cacdbe3b977785"
QA14 = "b56ef88f82f99626168bc487d4952d0285859ed7"
GAME = "15b666871eb6749133df671ca1b271d89ecdf3ae"
GAME_SOURCE = "c058cbf7fe38e02d929c67d047d717ff74bd522e"


def validate(data):
    r = data["revision_review_reconciliation"]
    c = r["historical_four_lane_observation_before_20261103_0836"]
    live = r["latest_20261103_0736_live_four_lane_reconciliation"]
    prev = r["historical_four_lane_observation_before_20261103_0736"]
    old_live = r["historical_latest_live_four_lane_before_20261103_0736"]
    app = c["app"]
    app_obs = r["observations"]["us-freelance-ledger-pr80"]
    prism = c["three_d"]
    prism_obs = r["historical_pr22_observation_before_20261103_0836"]
    qa14 = r["observations"]["prism-route-3d-consumer-qa-pr14"]
    game = c["game"]
    gates = r["historical_cross_lane_gates_before_20261103_0836"]

    assert r["writer"] == c["writer"] == live["writer"] == "36_WINDOWS_E2E_ONLY"
    assert data["updated_at_utc"] > r["observed_at_utc"] > c["observed_at_utc"] == live["observed_at_utc"]
    assert prev["observed_at_utc"] == old_live["observed_at_utc"] < live["observed_at_utc"]
    assert prev["app"]["us_freelance_ledger_pr"] == old_live["app"]["us_ledger_pr"] == 79
    assert prev["app"]["us_freelance_ledger_head"] == APP79
    assert prev["three_d"]["factory_pr"] == old_live["three_d"]["factory_pr"] == 21
    assert prev["three_d"]["source_sha"] == PR21
    assert r["observations"]["us-freelance-ledger-pr79"]["historical_only_after_20261103_0736"]
    assert qa14["historical_pr21_only_after_20261103_0736"]

    assert app["us_freelance_ledger_pr"] == app_obs["draft_pr"] == live["app"]["us_ledger_pr"] == 80
    assert app["us_freelance_ledger_head"] == app_obs["review_head_sha"] == live["app"]["us_ledger_head"] == APP80
    assert app["us_freelance_ledger_previous_head"] == app_obs["previous_review_head_sha"] == APP79
    assert app_obs["compare"] == "AHEAD_11_BEHIND_0_FROM_PR79"
    assert app["us_freelance_ledger_ci"] == live["app"]["us_ledger_ci"] == [41525219564]
    assert [x["run_id"] for x in app_obs["exact_head_ci"]] == [41525219564]
    assert all(x["conclusion"] == "SUCCESS" for x in app_obs["exact_head_ci"])
    assert app["us_freelance_ledger_artifact_count"] == app_obs["workflow_artifact_count"] == live["app"]["us_ledger_artifact_count"] == 0
    assert not app["us_freelance_ledger_independent_exe_bytes"]
    assert not app_obs["source_promoted"] and not app_obs["identity_return_verified_for_this_review"]
    assert not app_obs["physical_windows_gui_verified"] and not app_obs["consumer_purchase_verified"]
    assert not app_obs["real_msix"] and app_obs["store_submission"] == "NOT_PERFORMED"
    assert app["score"] == live["app"]["image_score"] == 64
    assert app["real_buyers"] == live["app"]["image_buyers"] == 0
    assert app["head"] == live["app"]["image_head"] == "25a93052dad41e1844c31fe84384714764a5ac4f"

    assert prism["factory_pr"] == prism_obs["draft_pr"] == live["three_d"]["factory_pr"] == 22
    assert prism["head"] == prism["source_sha"] == prism_obs["source_sha"] == live["three_d"]["source_sha"] == PR22
    assert prism["new_request_id"] == prism_obs["request_id"] == live["three_d"]["request_id"] == REQUEST22
    assert prism["previous_factory_source_sha"] == prism_obs["previous_pr21_source_sha"] == PR21
    assert prism_obs["compare"] == "AHEAD_7_BEHIND_0_FROM_PR21"
    assert prism["ci"] == live["three_d"]["ci"] == [41528683557, 41528683539]
    assert [x["run_id"] for x in prism_obs["exact_head_ci"]] == prism["ci"]
    assert all(x["conclusion"] == "SUCCESS" for x in prism_obs["exact_head_ci"])
    assert prism_obs["exact_head_ci"][0]["artifact_count"] == 0
    assert prism_obs["exact_head_ci"][1]["artifact_count"] == 3
    assert prism["factory_quality_ci_artifact_count"] == 0 and prism["factory_ci_artifact_count"] == 3
    assert prism["artifact_id"] == prism_obs["export_artifact_id"] == live["three_d"]["factory_artifact_id"] == 13180284133
    assert prism["artifact_run_id"] == prism_obs["export_run_id"] == 41528683539
    assert prism["artifact_metadata_digest"] == prism_obs["export_artifact_digest"] == live["three_d"]["artifact_digest"] == DIGEST22
    assert prism_obs["export_artifact_size_bytes"] == 37794728
    assert prism_obs["export_artifact_expires_at_utc"] == prism["artifact_expires_at_utc"] == "2026-11-09T21:29:29Z"
    assert prism_obs["resource_audit_artifact_id"] == 13180343961
    assert prism_obs["identity_reuse_evidence_artifact_id"] == 13180359001
    assert prism["qa_pr"] == 14 and prism["qa_head"] == qa14["review_head_sha"] == QA14
    assert qa14["factory_source_sha"] == PR21 and qa14["factory_artifact_id"] == 13155398069
    assert prism["qa14_historical_pr21_only"] and prism_obs["qa14_is_pr21_only"]
    assert not prism["qa14_is_current_factory_pck_qa"]
    assert not prism["pr22_export_artifact_independently_rehashed_by_36"]
    assert not prism["pr22_pck_qa_independent_pass"] and prism["pr22_qa_artifact_id"] is None
    assert not prism["pr22_source_request_exe_pck_manifest_independent_match"]
    assert not prism_obs["independent_36_download_rehash"]
    assert not prism_obs["independent_pr22_exe_pck_manifest_sha_verified"]
    assert not prism_obs["independent_pr22_qa_pass"]
    assert prism_obs["legacy_identity_return_commit"] == "11417b75636ee18816028ffd5221884c4c9a9836"
    assert not prism_obs["legacy_identity_is_pr22_cas"] and not prism["legacy_identity_cas_is_new_revision"]
    assert not prism["new_cas"] and not prism_obs["new_revision_cas"]
    assert not prism_obs["approved_version"] and not prism_obs["real_signed_msix"]
    assert not prism_obs["physical_windows_human_pass"] and not prism["physical_gui"]
    assert prism_obs["store_submission"] == "NOT_PERFORMED"

    assert game["factory_review_head"] == live["game"]["head"] == GAME
    assert game["original_source_sha"] == live["game"]["original_source_sha"] == GAME_SOURCE
    assert not game["cas"] and not game["msixvc"] and not game["physical_gui_pass"]
    assert not game["physical_qa_artifacts_independently_rehashed_by_36"]
    assert live["game"]["registration_type"] == "GDK_GAME"

    assert not gates["prism_pr22_factory_independent_bytes_pass"]
    assert not gates["prism_pr22_independent_pck_qa_pass"]
    assert not gates["prism_pr22_physical_human_pass"]
    assert not gates["app_us_ledger_pr80_exe_artifact_present"]
    assert not gates["app_us_ledger_pr80_physical_windows_pass"]
    assert live["windows_e2e"]["app4_actions_artifacts_live"] == 0
    assert live["windows_e2e"]["library_zip_preserved"] == 4
    assert live["windows_e2e"]["user_pc_zip_readback"] == 0
    assert live["windows_e2e"]["github_identity_returned"] == 2
    assert live["windows_e2e"]["operator_pending"] == 2
    assert live["windows_e2e"]["cloud_discovered"] == 4
    assert live["windows_e2e"]["local_batch_discovered"] == 0
    assert live["windows_e2e"]["physical_processed"] == 0
    assert live["windows_e2e"]["local_code_sync"] == "CLOUD_PASS_ONLY"
    assert not live["windows_e2e"]["scheduler_receipt"]
    assert not live["windows_e2e"]["real_msix"] and not live["windows_e2e"]["gdk_msixvc"]
    assert not live["windows_e2e"]["backlog"] and not live["windows_e2e"]["checker"]
    assert not live["windows_e2e"]["install_gui"] and not live["windows_e2e"]["e2e_pass"]
    newer = r["historical_post_handoff_candidates_before_20261103_0836"]
    a2, g2, p2 = newer["app"], newer["game"], newer["three_d"]
    assert a2["pr80_product_baseline_sha"] == APP80
    assert a2["pr82_product_review_head"] == "19f0bee05322d7e347513092e2e56d4d8a5a45d3"
    assert a2["pr82_core_ci_run_id"] == 41535034535 and a2["pr82_core_ci_conclusion"] == "SUCCESS"
    assert a2["qa83_review_head"] == "05c667da0b04610bde38beed7b9bd4a5b7848165"
    assert a2["qa83_pinned_product_source_sha"] == "97beffedec6f5657a4c3a66439e90ce68637ba53"
    assert not a2["qa83_pinned_source_is_current_pr82_head"]
    assert not a2["qa83_is_current_pr82_exe_proof"]
    assert not a2["physical_windows_125_150_human_pass"] and not a2["cas"]
    assert g2["pr17_product_ui_head"] == GAME
    assert g2["pr18_physical_protocol_review_head"] == "6ce4a9b47b55d865c33c7e0a50ffb18f5219c138"
    assert g2["pr18_core_ci_run_id"] == 41536644003 and g2["pr18_gui_ci_run_id"] == 41536644056
    assert g2["pr18_ci_success"] and g2["pr18_qa_only"]
    assert not g2["pr18_is_new_gdk_package"] and not g2["pr18_is_physical_user_pc_pass"] and not g2["cas"]
    assert p2["factory_pr22_source_sha"] == PR22
    assert p2["qa15_head"] == "395ab342091c420e0ebdafd1b922dd9d3255539e"
    assert p2["qa15_ci_runs"] == [41537438979, 41537439002, 41537438993]
    assert p2["qa15_ci_success"] and p2["qa15_exact_pr22_software_pck_qa_reported_by_24"]
    assert p2["qa15_artifact_id"] == 13185037028
    assert p2["qa15_artifact_metadata_digest"] == "sha256:df4999581b280f0663e4f72a0ba80379849163a42efe54cf311ec138be7c0caf"
    assert p2["qa15_reported_screenshots"] == 8
    assert not p2["qa15_36_independent_artifact_byte_rehash"]
    assert not p2["qa15_physical_windows_human_pass"] and not p2["legacy_identity_is_pr22_cas"]
    assert not p2["signed_msix"] and p2["qa14_is_pr21_historical"]

    assert not data["e2e_pass"] and not data["sale_ready_windows_ux_gate"]["sale_ready"]


class Live0736FailClosed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_live_consistency(self):
        validate(self.data)

    def reject(self, mutate):
        changed = copy.deepcopy(self.data)
        mutate(changed)
        with self.assertRaises(AssertionError):
            validate(changed)

    def test_reject_pr79_as_live(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_before_20261103_0836"]["app"].__setitem__("us_freelance_ledger_head", APP79))

    def test_reject_pr79_observation_as_pr80(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["us-freelance-ledger-pr80"].__setitem__("draft_pr", 79))

    def test_reject_app_fake_exe(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_before_20261103_0836"]["app"].__setitem__("us_freelance_ledger_artifact_count", 1))

    def test_reject_app_false_promotion(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["us-freelance-ledger-pr80"].__setitem__("source_promoted", True))

    def test_reject_pr21_as_live(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_before_20261103_0836"]["three_d"].__setitem__("source_sha", PR21))

    def test_reject_cross_revision_request(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_before_20261103_0836"]["three_d"].__setitem__("new_request_id", "3d-prism-route-3d-066d9f51d58c"))

    def test_reject_old_pr21_artifact_as_new(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_before_20261103_0836"]["three_d"].__setitem__("artifact_id", 13155398069))

    def test_reject_qa14_as_new_pr22_qa(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_before_20261103_0836"]["three_d"].__setitem__("qa14_is_current_factory_pck_qa", True))

    def test_reject_false_pr22_byte_pass(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_before_20261103_0836"]["three_d"].__setitem__("pr22_export_artifact_independently_rehashed_by_36", True))

    def test_reject_false_pr22_qa_pass(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_pr22_observation_before_20261103_0836"].__setitem__("independent_pr22_qa_pass", True))

    def test_reject_wrong_artifact_digest(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_before_20261103_0836"]["three_d"].__setitem__("artifact_metadata_digest", "sha256:1a19000c225b5165a1280ec36b4dcf5eaec4287e39d50f86512b8e9f5ad4dd44"))

    def test_reject_quality_ci_falsely_claiming_export_artifact(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_pr22_observation_before_20261103_0836"]["exact_head_ci"][0].__setitem__("artifact_count", 3))

    def test_reject_legacy_identity_new_cas(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_pr22_observation_before_20261103_0836"].__setitem__("legacy_identity_is_pr22_cas", True))

    def test_reject_false_physical_pass(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_pr22_observation_before_20261103_0836"].__setitem__("physical_windows_human_pass", True))

    def test_reject_false_gdk(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_before_20261103_0836"]["game"].__setitem__("msixvc", True))

    def test_reject_app4_library_as_actions(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0736_live_four_lane_reconciliation"]["windows_e2e"].__setitem__("app4_actions_artifacts_live", 4))

    def test_reject_cloud_as_local(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0736_live_four_lane_reconciliation"]["windows_e2e"].__setitem__("physical_processed", 4))

    def test_reject_fake_scheduler(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0736_live_four_lane_reconciliation"]["windows_e2e"].__setitem__("scheduler_receipt", True))

    def test_reject_qa83_stale_source_as_current(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_post_handoff_candidates_before_20261103_0836"]["app"].__setitem__("qa83_pinned_source_is_current_pr82_head", True))

    def test_reject_game18_protocol_as_gdk_package(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_post_handoff_candidates_before_20261103_0836"]["game"].__setitem__("pr18_is_new_gdk_package", True))

    def test_reject_qa15_metadata_as_36_byte_rehash(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_post_handoff_candidates_before_20261103_0836"]["three_d"].__setitem__("qa15_36_independent_artifact_byte_rehash", True))

    def test_reject_qa15_software_as_physical(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_post_handoff_candidates_before_20261103_0836"]["three_d"].__setitem__("qa15_physical_windows_human_pass", True))

    def test_reject_false_e2e(self):
        self.reject(lambda d: d.__setitem__("e2e_pass", True))


if __name__ == "__main__":
    unittest.main()
