"""Latest PR76 / QA9 evidence stays review-only; metadata is not physical QA."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
APP = "886b9214b9cc79b35403ca168ca09df7a2e12404"
QA = "1a16b2a69083ca5698f29388c0eb59875a612450"


def validate(data):
    r = data["revision_review_reconciliation"]
    current = r["current_four_lane_observation"]
    app = r["observations"]["offline-image-inventory-desk"]
    qa = r["observations"]["prism-route-3d-consumer-qa-pr9"]
    latest = r["latest_20261102_2241_review_provenance"]
    assert latest["writer"] == "36_WINDOWS_E2E_ONLY"
    assert app["current_review_head_sha"] == current["app"]["head"] == latest["app"]["current_head"] == APP
    assert app["previous_review_head_sha"] == latest["app"]["previous_head"]
    assert current["app"]["ci"] == [41449337747, 41449337454]
    assert current["app"]["review_unsigned_exe_artifact_id"] == app["review_unsigned_exe_artifact_id"] == 13143283530
    assert app["cloud_buyer_task_artifact_id"] == current["app"]["cloud_buyer_task_artifact_id"] == 13144232281
    assert app["cloud_buyer_task_artifact_id"] != app["review_unsigned_exe_artifact_id"]
    assert latest["app"]["artifact_metadata_only"] and not latest["app"]["independent_byte_rehash_by_36"]
    assert not app["physical_os_dpi_receipt_verified"] and not app["independent_real_buyer_responses_verified"]
    assert app["score"] == 64 and app["independent_buyers_completed"] == 0
    assert not app["current_review_revision_promoted"] and app["new_revision_source_sha"] is None
    assert app["immutable_pre_identity_request_id"] == current["app"]["old_immutable_request_id"]
    assert qa["current_review_head_sha"] == current["three_d"]["qa_head"] == latest["three_d_qa"]["current_head"] == QA
    assert qa["previous_review_head_sha"] == latest["three_d_qa"]["previous_head"]
    assert current["three_d"]["qa_ci"] == [41454758338, 41454758366]
    assert qa["hosted_qa_artifact_id"] == current["three_d"]["qa9_runtime_artifact_id"] == 13145583388
    assert qa["factory_artifact_id_referenced_in_workflow"] == 13142680551
    assert not qa["factory_artifact_independently_verified_by_36"]
    assert latest["three_d_qa"]["artifact_metadata_only"] and not latest["three_d_qa"]["independent_pck_rehash_by_36"]
    assert qa["physical_capture_contract_reviewed"] and not qa["physical_capture_receipt_present"]
    assert not qa["independent_user_pc_ja_en_125_150_qa"]
    assert not current["three_d"]["qa9_physical_receipt_verified"]
    assert current["three_d"]["factory_pr"] == 19 and current["three_d"]["factory_quality_ci_artifact_count"] == 0
    assert current["three_d"]["artifact_id"] is None and not current["three_d"]["pr19_new_pck_verified_by_36"]
    assert current["three_d"]["historical_pr18_build"]["artifact_id"] == 13130487252
    assert not current["three_d"]["legacy_identity_cas_is_new_revision"] and not current["three_d"]["new_cas"]
    assert not data["quality_gates"]["gui_qa_pass"] and not data["e2e_pass"]
    assert not data["quality_gates"]["local_source_code_sync_physical_pass"]
    assert current["windows_e2e"]["batch_local_processed"] == 0 and not current["windows_e2e"]["task_scheduler_proof"]


class LatestReviewMetadataFailClosed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_checked_in_evidence(self):
        validate(self.ledger)

    def reject(self, mutate):
        broken = copy.deepcopy(self.ledger)
        mutate(broken)
        with self.assertRaises(AssertionError):
            validate(broken)

    def test_cloud_buyer_task_not_real_buyer(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["offline-image-inventory-desk"].__setitem__("independent_real_buyer_responses_verified", True))

    def test_unsigned_review_exe_not_approved_source(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["offline-image-inventory-desk"].__setitem__("current_review_revision_promoted", True))

    def test_qa_contract_not_physical_receipt(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr9"].__setitem__("physical_capture_receipt_present", True))

    def test_qa_artifact_metadata_not_independent_pck_rehash(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261102_2241_review_provenance"]["three_d_qa"].__setitem__("independent_pck_rehash_by_36", True))

    def test_pr18_pck_cannot_be_current_pr19_factory_artifact(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("artifact_id", 13130487252))

    def test_app_artifact_types_not_interchangeable(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["app"].__setitem__("review_unsigned_exe_artifact_id", 13144232281))

    def test_cloud_not_local(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["windows_e2e"].__setitem__("batch_local_processed", 4))


if __name__ == "__main__":
    unittest.main()
