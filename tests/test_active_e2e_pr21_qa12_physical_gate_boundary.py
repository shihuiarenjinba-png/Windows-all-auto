"""QA12 is current review-only physical gate; QA11 independent bytes stay historical."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
SOURCE = "066d9f51d58cfecb994665d5c31adb1156c38942"
REQUEST = "3d-prism-route-3d-066d9f51d58c"
QA11 = "09597432adbe1b03be66252224c969ed9dc35c57"
QA12 = "235b002571013eb82c2a561d463ac677c3cf7742"
GATE1 = "11417b75636ee18816028ffd5221884c4c9a9836"


def validate(d):
    r = d["revision_review_reconciliation"]
    c = r["current_four_lane_observation"]
    t = c["three_d"]
    historical = r["historical_four_lane_observation_20261103_0136"]["three_d"]
    current = r["observations"]["prism-route-3d-consumer-qa-pr12"]
    baseline = r["observations"]["prism-route-3d-consumer-qa-pr11"]
    proof = r["latest_20261103_0136_pr21_qa11_independent_byte_provenance"]
    gate = r["latest_20261103_0236_pr21_qa12_physical_gate_observation"]
    assert r["writer"] == c["writer"] == gate["writer"] == "36_WINDOWS_E2E_ONLY"
    assert t["factory_pr"] == 21 and t["head"] == t["source_sha"] == SOURCE
    assert t["new_request_id"] == REQUEST and t["artifact_id"] == 13155398069
    assert t["qa_pr"] == current["draft_pr"] == 12
    assert t["qa_head"] == current["review_head_sha"] == current["artifact_head_sha"] == QA12
    assert t["qa_head"] != historical["qa_head"] == baseline["review_head_sha"] == QA11
    assert t["qa_ci"] == current["ci_runs"] == [41481268928, 41481268900]
    assert current["ci_conclusion"] == "SUCCESS_BOTH_RUNS"
    assert t["qa12_runtime_artifact_id"] == current["artifact_id"] == 13158359758
    assert current["artifact_run_id"] == 41481268928
    assert current["artifact_metadata_digest"] == t["qa12_artifact_metadata_digest"] == "sha256:86aed34aa00b7611994f0d34c0711e47ef1496c0e7a42b6f006c5b669ca44ca3"
    assert current["artifact_size_bytes"] == 440946 and not current["artifact_expired"]
    assert current["previous_qa11_head_sha"] == QA11
    assert current["compare"] == "AHEAD_7_BEHIND_0_FROM_QA11"
    assert current["factory_pr21_source_sha"] == SOURCE
    assert current["factory_pr21_request_id"] == REQUEST
    assert current["factory_pr21_artifact_id"] == 13155398069
    assert historical["qa_pr"] == 11 and historical["qa11_runtime_artifact_id"] == 13156640316
    assert proof["factory"]["source_sha"] == SOURCE and proof["factory"]["request_id"] == REQUEST
    assert proof["factory"]["independent_36_bytes_verified"]
    assert proof["qa"]["independent_36_receipt_bytes_verified"]
    assert proof["qa"]["artifact_id"] == 13156640316 and proof["qa"]["screenshot_count"] == 7
    assert baseline["historical_underlying_software_baseline"] and not baseline["is_current_review_head"]
    assert current["qa11_historical_independent_36_byte_proof"]
    assert not current["qa12_independent_36_artifact_byte_rehash"]
    assert not t["qa12_independent_36_artifact_byte_rehash"]
    assert not gate["qa12_artifact_bytes_independently_rehashed_by_36"]
    assert t["qa12_physical_human_gate_ci_pass"]
    assert not t["qa12_physical_windows_human_pass"]
    assert not t["qa12_physical_operator_receipt_present"]
    assert current["required_physical_pngs"] == 24
    assert current["required_physical_sessions"] == "4_DISTINCT_JA_EN_X_125_150_DPI"
    assert not current["physical_operator_receipt_present"]
    assert not current["physical_windows_gui_pass"] and not current["human_qa_pass"]
    assert not gate["physical_windows_ja_en_125_150"] and not gate["human_first30s"]
    assert not gate["wall_clock_90s"] and not gate["sale_ready"]
    assert t["legacy_identity_return_commit"] == gate["historical_identity_return_commit"] == GATE1
    assert not t["legacy_identity_cas_is_new_revision"] and not gate["historical_identity_is_new_pr21_cas"]
    assert not t["new_cas"] and not current["new_revision_identity_cas"]
    assert not t["signed_msix"] and not t["physical_gui"] and not current["real_signed_msix"]
    assert not d["quality_gates"]["prism_pr21_qa12_physical_human_gate_pass"]
    assert not d["quality_gates"]["local_source_code_sync_physical_pass"]
    assert not d["quality_gates"]["local_source_code_sync_scheduler_pass"]
    assert gate["app_identity_returned"] == 2 and gate["app_cloud_discovered"] == 4
    assert gate["app_physical_processed"] == d["multi_product_partner_center_batch_4"]["processed_count"] == 0
    assert not d["e2e_pass"] and not d["sale_ready_windows_ux_gate"]["sale_ready"]


class Qa12CurrentBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_exact_current_and_historical_boundaries(self):
        validate(self.ledger)

    def reject(self, mutate):
        bad = copy.deepcopy(self.ledger)
        mutate(bad)
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_reject_stale_qa11_current_head(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("qa_head", QA11))

    def test_reject_qa11_artifact_as_qa12(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("qa12_runtime_artifact_id", 13156640316))

    def test_reject_old_factory_pck_as_current(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("artifact_id", 13149467845))

    def test_reject_old_identity_new_cas(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("new_cas", True))

    def test_reject_false_physical_pass(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("qa12_physical_windows_human_pass", True))

    def test_reject_fake_physical_receipt(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr12"].__setitem__("physical_operator_receipt_present", True))

    def test_reject_qa12_metadata_as_independent_byte_pass(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("qa12_independent_36_artifact_byte_rehash", True))

    def test_reject_wrong_request(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr12"].__setitem__("factory_pr21_request_id", "3d-prism-route-3d-f015db1762fb"))

    def test_reject_cloud_cursor_as_local(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"].__setitem__("processed_count", 4))

    def test_reject_false_scheduler_pass(self):
        self.reject(lambda d: d["quality_gates"].__setitem__("local_source_code_sync_scheduler_pass", True))


if __name__ == "__main__":
    unittest.main()
