"""PR21/QA11 current provenance: real downloaded bytes, historical PR20 and physical HOLD."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
SOURCE = "066d9f51d58cfecb994665d5c31adb1156c38942"
REQUEST = "3d-prism-route-3d-066d9f51d58c"
FACTORY_ZIP = "1a19000c225b5165a1280ec36b4dcf5eaec4287e39d50f86512b8e9f5ad4dd44"
QA_ZIP = "1f6622373de0a4626e5480dc28465af7b90eb753d4801eb6d354c04581e5999a"
EXE = "66b26ad96df7458ea917b632a73ac7c88bb058db24dbd11a457fd50435ab7b13"
PCK = "a27c198ff4bdaa961780b4e42d5fb429c328c5bad0b5cb816e399c06e3fd8cb9"
MANIFEST = "03c04fc0958383ffcffa6e0bed35706b813f517526c793278e662ac2413f8ed9"
OLD_IDENTITY = "11417b75636ee18816028ffd5221884c4c9a9836"
APP_HEAD = "25a93052dad41e1844c31fe84384714764a5ac4f"
GAME_HEAD = "f882cac70a7c2294ce0799ea27ec3909596b6002"


def validate(d):
    r = d["revision_review_reconciliation"]
    p = r["latest_20261103_0136_pr21_qa11_independent_byte_provenance"]
    c = r["current_four_lane_observation"]
    old = r["historical_four_lane_observation_20261103_0043"]
    f, q, h, g = p["factory"], p["qa"], p["historical"], p["gates"]
    t = r["historical_four_lane_observation_20261103_0136"]["three_d"]
    now = c["three_d"]
    assert now["factory_pr"] == 21 and now["head"] == SOURCE
    assert now["artifact_id"] == 13155398069
    assert now["qa_pr"] == 12
    assert now["qa_head"] == "235b002571013eb82c2a561d463ac677c3cf7742"
    assert now["qa_ci"] == [41481268928, 41481268900]
    assert not now["new_cas"] and not now["physical_gui"]
    assert not now["qa12_physical_windows_human_pass"]
    assert p["writer"] == c["writer"] == "36_WINDOWS_E2E_ONLY"
    assert old["three_d"]["factory_pr"] == 20
    assert old["three_d"]["source_sha"] == h["pr20_factory_source_sha"]
    assert old["three_d"]["artifact_id"] == h["pr20_factory_artifact_id"] == 13149467845
    assert old["three_d"]["qa10_runtime_artifact_id"] == h["pr20_qa10_artifact_id"] == 13150622623
    assert h["pr20_independent_36_byte_pass"] and not h["old_artifacts_are_current_pr21"]
    assert t["factory_pr"] == f["pr"] == 21
    assert t["head"] == t["source_sha"] == f["head_sha"] == f["source_sha"] == SOURCE
    assert t["new_request_id"] == f["request_id"] == REQUEST
    assert f["manifest_source_sha"] == f["manifest_build_head"] == SOURCE
    assert f["manifest_request_id"] == REQUEST
    assert f["export_run_id"] == t["artifact_run_id"] == 41472458097
    assert t["ci"] == [41472458097] and f["export_ci_conclusion"] == "SUCCESS"
    assert t["factory_ci_artifact_count"] == 3
    assert t["artifact_id"] == f["artifact_id"] == 13155398069
    assert t["artifact_id"] != h["pr20_factory_artifact_id"] != h["pr19_factory_artifact_id"]
    assert t["artifact_metadata_digest"] == "sha256:" + FACTORY_ZIP
    assert f["archive_sha256"] == FACTORY_ZIP and f["archive_size_bytes"] == 37794175
    assert f["crc_pass"] and f["independent_36_bytes_verified"]
    assert f["exact_members"] == ["candidate.exe", "candidate.pck", "export-evidence.json"]
    assert f["exe_sha256"] == EXE and f["exe_size_bytes"] == 84214784
    assert f["pck_sha256"] == PCK and f["pck_size_bytes"] == 6982208
    assert f["manifest_sha256"] == MANIFEST
    assert t["qa_pr"] == q["pr"] == 11
    assert t["qa_head"] == q["head_sha"] == "09597432adbe1b03be66252224c969ed9dc35c57"
    assert t["qa_ci"] == [q["ci_run_id"]] == [41472861586]
    assert q["ci_conclusion"] == "SUCCESS"
    assert t["qa11_runtime_artifact_id"] == q["artifact_id"] == 13156640316
    assert q["archive_sha256"] == QA_ZIP and q["archive_size_bytes"] == 441656 and q["crc_pass"]
    assert q["receipt_factory_artifact_id"] == f["artifact_id"]
    assert q["receipt_factory_run_id"] == f["export_run_id"]
    assert q["receipt_source_sha"] == f["source_sha"]
    assert q["receipt_request_id"] == f["request_id"]
    assert q["receipt_zip_sha256"] == f["archive_sha256"]
    assert q["receipt_exe_sha256"] == f["exe_sha256"]
    assert q["receipt_pck_sha256"] == f["pck_sha256"]
    assert q["receipt_manifest_sha256"] == f["manifest_sha256"]
    assert q["screenshot_count"] == t["pr21_qa11_screenshots_verified"] == 7
    assert len(q["screenshots"]) == 7 and q["screenshot_sha_and_bytes_match"]
    assert all(v["width"] == 1024 and v["height"] == 768 and len(v["sha256"]) == 64 and v["bytes"] > 0 for v in q["screenshots"].values())
    assert q["independent_36_receipt_bytes_verified"]
    assert q["hosted_software_runtime_reported_pass"] and q["hosted_runtime_not_36_executed"]
    assert not q["physical_windows_gui_verified"] and not q["human_first_30s_verified"]
    assert not q["human_real_time_90s_verified"] and not q["dpi_125_150_verified"]
    assert t["pr21_factory_bytes_independently_verified_by_36"]
    assert t["pr21_qa11_receipt_bytes_independently_verified_by_36"]
    assert t["pr21_qa11_source_request_exe_pck_manifest_match"]
    assert h["gate1_identity_return_commit"] == t["legacy_identity_return_commit"] == OLD_IDENTITY
    assert not h["old_identity_is_new_pr21_cas"] and not t["legacy_identity_cas_is_new_revision"]
    assert not t["new_cas"] and not t["signed_msix"] and not t["physical_gui"]
    assert c["app"]["head"] == p["review_only"]["app_pr76_head"] == APP_HEAD
    assert c["app"]["ci"] == p["review_only"]["app_ci_runs"] == [41477415558, 41477415526]
    assert c["app"]["score"] == 64 and c["app"]["real_buyers"] == 0 and not c["app"]["promoted"]
    assert c["game"]["factory_review_head"] == p["review_only"]["game_pr16_head"] == GAME_HEAD
    assert c["game"]["factory_review_ci"] == p["review_only"]["game_ci_runs"] == [41479105394, 41479105190]
    assert c["game"]["original_source_sha"] == p["review_only"]["game_original_immutable_source"]
    assert c["game"]["original_source_sha"] != GAME_HEAD and not c["game"]["cas"]
    assert not any(g[k] for k in ("new_revision_cas","package_version_approved","signed_msix","real_gdk_msixvc","physical_windows_ja_en_125_150","uncoached_human_30s","real_wall_clock_90s","local_exact_3_sha","task_scheduler_receipt","sale_ready"))
    assert (g["app_batch4_github_identity_returned"], g["app_batch4_local_processed"]) == (2, 0)
    assert d["current_identity_projection"]["github_identity_returned"] == 2
    assert d["multi_product_partner_center_batch_4"]["processed_count"] == 0
    assert d["quality_gates"]["prism_pr21_factory_pck_independent_bytes_pass"]
    assert d["quality_gates"]["prism_pr21_qa11_receipt_crosscheck_pass"]
    assert not d["quality_gates"]["prism_pr21_physical_gui_pass"]
    assert not d["quality_gates"]["local_source_code_sync_physical_pass"]
    assert not d["quality_gates"]["local_source_code_sync_scheduler_pass"]
    assert not d["e2e_pass"] and not d["sale_ready_windows_ux_gate"]["sale_ready"]


class CurrentPr21FailClosed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_current_exact_provenance(self):
        validate(self.data)

    def reject(self, fn):
        bad = copy.deepcopy(self.data)
        fn(bad)
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_reject_stale_pr20_current_source(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("head", "f015db1762fb63696bcca304028871235142bf3d"))

    def test_reject_stale_qa10_current_head(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("qa_head", "e2f05d844d155b9a3a8bd5b493f8d96fef659de3"))

    def test_reject_pr20_factory_artifact_as_pr21(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("artifact_id", 13149467845))

    def test_reject_pr20_pck_as_pr21(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0136_pr21_qa11_independent_byte_provenance"]["factory"].__setitem__("pck_sha256", "10acb61a586caa55b2da59ed0aae62f0952cfbaf7a69cac3cf219f3ae2a982c9"))

    def test_reject_mismatched_qa_request(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0136_pr21_qa11_independent_byte_provenance"]["qa"].__setitem__("receipt_request_id", "3d-prism-route-3d-f015db1762fb"))

    def test_reject_fake_screenshot_dimensions(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0136_pr21_qa11_independent_byte_provenance"]["qa"]["screenshots"]["ja"].__setitem__("height", 720))

    def test_reject_old_gate1_identity_as_new_cas(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("new_cas", True))

    def test_reject_hosted_runtime_as_physical_windows(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0136_pr21_qa11_independent_byte_provenance"]["qa"].__setitem__("physical_windows_gui_verified", True))

    def test_reject_game_review_as_immutable_source(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("original_source_sha", GAME_HEAD))

    def test_reject_app_market_promotion(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["app"].__setitem__("promoted", True))

    def test_reject_cloud_cursor_as_local_processing(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"].__setitem__("processed_count", 4))

    def test_reject_unverified_scheduler_receipt(self):
        self.reject(lambda d: d["quality_gates"].__setitem__("local_source_code_sync_scheduler_pass", True))


if __name__ == "__main__":
    unittest.main()
