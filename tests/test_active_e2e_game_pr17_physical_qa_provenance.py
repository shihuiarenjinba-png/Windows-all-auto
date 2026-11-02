"""Signal Sprint PR17 live review artifacts are not immutable source, GDK, CAS or physical QA."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
SOURCE = "c058cbf7fe38e02d929c67d047d717ff74bd522e"
REQUEST = "game-signal-sprint-" + SOURCE
PR16 = "f882cac70a7c2294ce0799ea27ec3909596b6002"
PR17 = "495d5dc8488d28f7b88373ba20897613e8ed47e7"
INITIAL_PR17 = "f5bc1e0d495bdcd65bf25fa370d7e68ef415d323"
EXE_DIGEST = "sha256:5d6a68d2f3a1affec7717a3d884a0f4045984485c4bf8e882bcbb49d2e1fb316"
GUI_DIGEST = "sha256:652e5a6da8004eaa76147dfd7cb3ddaaa0e82e675dbb7b1e0a469b73c462e51e"


def validate(d):
    r = d["revision_review_reconciliation"]
    c = r["current_four_lane_observation"]["game"]
    old = r["historical_four_lane_observation_20261103_0336"]["game"]
    o = r["observations"]["signal-sprint-physical-qa-pr17"]
    gates = r["cross_lane_gates"]
    assert r["writer"] == "36_WINDOWS_E2E_ONLY"
    assert c["factory_review_pr"] == o["draft_pr"] == 17
    assert c["factory_review_head"] == o["current_review_head_sha"] == PR17
    assert c["factory_review_ci"] == [41508700002, 41508700112]
    assert o["compare_from_pr16"] == "AHEAD_10_BEHIND_0"
    assert old["factory_review_pr"] == 16 and old["factory_review_head"] == PR16
    assert c["previous_factory_review_head"] == o["previous_review_head_sha"] == PR16
    assert o["historical_pr17_initial_run_head_sha"] == INITIAL_PR17
    assert o["historical_pr17_initial_exe_artifact_id"] == 13167801977
    assert o["historical_pr17_initial_gui_artifact_id"] == 13167951909
    assert o["historical_pr16_gui_artifact_id"] == 13159475933
    assert c["original_source_sha"] == o["immutable_original_source_sha"] == SOURCE
    assert c["original_request_id"] == o["immutable_original_request_id"] == REQUEST
    assert o["registration_type"] == "GDK_GAME"
    assert not o["review_head_is_immutable_source"]
    assert c["factory_artifact_run_head"] == old["factory_artifact_run_head"] == "a1af3448cd2edeae5bd54cbaca486a53fd991944"
    assert c["physical_qa_artifact_run_head"] == o["current_run_head_sha"] == PR17
    assert c["physical_qa_artifact_run_id"] == o["current_run_id"] == 41508700112
    assert c["physical_qa_exe_artifact_id"] == o["current_exe_artifact_id"] == 13171328223
    assert c["hosted_gui_artifact_id"] == o["current_gui_artifact_id"] == 13171178413
    assert c["physical_qa_exe_artifact_digest"] == o["current_exe_artifact_digest"] == EXE_DIGEST
    assert c["hosted_gui_artifact_digest"] == o["current_gui_artifact_digest"] == GUI_DIGEST
    assert o["artifacts_metadata_live_and_not_expired"]
    assert not o["artifact_independent_download_and_rehash_by_36"]
    assert not c["physical_qa_artifacts_independently_rehashed_by_36"]
    assert not gates["game_pr17_independent_36_exe_bytes_pass"]
    assert o["hosted_gui_check_only"] and not o["physical_user_pc"]
    assert not o["human_qa"] and not o["code_integrity_verified"]
    assert not c["physical_gui_pass"] and not c["local_pass"]
    assert not c["physical_qa_operator_receipt_present"]
    assert not o["approved_gdk_staging_exe"] and not c["physical_qa_artifact_is_approved_staging_exe"]
    assert not c["physical_qa_artifact_is_gdk_msixvc"] and not o["gdk_msixvc2"]
    assert not o["gdk_sdk"] and not o["approved_version"]
    assert not c["cas"] and not c["msixvc"] and not o["new_cas_applied"]
    assert not gates["game_pr17_gdk_msixvc_pass"] and not gates["game_pr17_physical_user_pc_pass"]
    assert o["store_submission"] == "NOT_PERFORMED" and not o["sale_ready"]
    assert not d["e2e_pass"] and not d["sale_ready_windows_ux_gate"]["sale_ready"]
    assert d["multi_product_partner_center_batch_4"]["processed_count"] == 0
    assert not d["quality_gates"]["local_source_code_sync_physical_pass"]
    assert not d["quality_gates"]["local_source_code_sync_scheduler_pass"]


class GamePr17CurrentReviewBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_live_review_metadata_with_historical_source_and_holds(self):
        validate(self.ledger)

    def reject(self, mutate):
        bad = copy.deepcopy(self.ledger)
        mutate(bad)
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_reject_stale_pr16_as_current(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("factory_review_head", PR16))

    def test_reject_old_pr17_run_as_live_head(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-physical-qa-pr17"].__setitem__("current_run_head_sha", INITIAL_PR17))

    def test_reject_old_pr16_gui_artifact_substitution(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("hosted_gui_artifact_id", 13159475933))

    def test_reject_initial_pr17_exe_as_latest(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-physical-qa-pr17"].__setitem__("current_exe_artifact_id", 13167801977))

    def test_reject_exe_gui_artifact_swapping(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("physical_qa_exe_artifact_id", 13171178413))

    def test_reject_wrong_digest(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-physical-qa-pr17"].__setitem__("current_exe_artifact_digest", GUI_DIGEST))

    def test_reject_mutated_original_source(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-physical-qa-pr17"].__setitem__("immutable_original_source_sha", PR17))

    def test_reject_exe_claimed_as_gdk_msixvc(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("physical_qa_artifact_is_gdk_msixvc", True))

    def test_reject_exe_claimed_approved_gdk_staging(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-physical-qa-pr17"].__setitem__("approved_gdk_staging_exe", True))

    def test_reject_false_physical_pass(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-physical-qa-pr17"].__setitem__("physical_user_pc", True))

    def test_reject_fake_local_receipt(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("physical_qa_operator_receipt_present", True))

    def test_reject_unverified_byte_claim(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-physical-qa-pr17"].__setitem__("artifact_independent_download_and_rehash_by_36", True))

    def test_reject_cas_claim(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["signal-sprint-physical-qa-pr17"].__setitem__("new_cas_applied", True))

    def test_reject_cloud_cursor_as_physical(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"].__setitem__("processed_count", 4))


if __name__ == "__main__":
    unittest.main()
