"""Prism PR20 Factory + QA10 actual bytes; PR19 remains historical, no sale promotion."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
SOURCE = "f015db1762fb63696bcca304028871235142bf3d"
REQUEST = "3d-prism-route-3d-f015db1762fb"
FACTORY_ZIP = "a04de188d2dd8c3bfbf454cffe77a4eb58fd99e0c5a7e247d95062523e2489c7"
QA_ZIP = "789ab8765a905e7e8e4a2500f2136590bbbcae212b6247c9e0f2c4b6814c83ea"
EXE = "66b26ad96df7458ea917b632a73ac7c88bb058db24dbd11a457fd50435ab7b13"
PCK = "10acb61a586caa55b2da59ed0aae62f0952cfbaf7a69cac3cf219f3ae2a982c9"
MANIFEST = "34528d42e14378b6236dfb95428ee727a4c6304be0021c5d1325b8b433b8766b"
GAME = "8e6a8c10a2678b76a2eddc897e5fea8cf7d5dc98"
ORIGINAL_GAME = "c058cbf7fe38e02d929c67d047d717ff74bd522e"
OLD_IDENTITY = "11417b75636ee18816028ffd5221884c4c9a9836"


def validate(d):
    r = d["revision_review_reconciliation"]
    c = r["current_four_lane_observation"]
    old = r["historical_four_lane_observation_20261102_2350"]
    p = r["latest_20261103_0043_pr20_qa10_independent_byte_provenance"]
    f, q, h, gates = p["factory"], p["qa"], p["historical"], p["gates"]
    t, game = c["three_d"], c["game"]
    o = r["observations"]
    assert c["writer"] == p["writer"] == "36_WINDOWS_E2E_ONLY"
    assert old["three_d"]["factory_pr"] == 19 and old["three_d"]["head"] == h["pr19_source_sha"]
    assert old["three_d"]["artifact_id"] == h["pr19_factory_artifact_id"] == 13142680551
    assert old["three_d"]["qa9_runtime_artifact_id"] == h["pr19_qa_artifact_id"] == 13145583388
    assert old["three_d"]["pr19_new_pck_verified_by_36"] and h["pr19_independent_36_pass"]
    assert t["factory_pr"] == f["pr"] == 20 and t["head"] == t["source_sha"] == f["source_sha"] == SOURCE
    assert t["new_request_id"] == f["request_id"] == REQUEST
    assert f["manifest_source_sha"] == f["manifest_build_head"] == SOURCE
    assert f["manifest_request_id"] == REQUEST
    assert t["ci"] == [f["quality_ci_run_id"]] == [41463172000]
    assert f["quality_ci_artifact_count"] == t["factory_quality_ci_artifact_count"] == 0
    assert f["export_run_id"] == t["artifact_run_id"] == 41463172094
    assert f["artifact_id"] == t["artifact_id"] == 13149467845
    assert f["artifact_id"] != h["pr19_factory_artifact_id"] != h["pr18_artifact_id"]
    assert f["archive_sha256"] == t["artifact_metadata_digest"].removeprefix("sha256:") == FACTORY_ZIP
    assert f["archive_size_bytes"] == 37794197 and f["crc_pass"]
    assert f["exact_members"] == ["candidate.exe", "candidate.pck", "export-evidence.json"]
    assert f["exe_sha256"] == EXE and f["exe_bytes"] == 84214784
    assert f["pck_sha256"] == PCK and f["pck_bytes"] == 6982288
    assert f["manifest_sha256"] == MANIFEST and f["independent_36_bytes_verified"]
    assert t["qa_pr"] == q["pr"] == 10 and t["qa_head"] == q["head_sha"] == "e2f05d844d155b9a3a8bd5b493f8d96fef659de3"
    assert t["qa_ci"] == q["ci_runs"] == [41463704723, 41463704874]
    assert q["artifact_id"] == t["qa10_runtime_artifact_id"] == 13150622623
    assert q["run_id"] == 41463704874 and q["archive_sha256"] == QA_ZIP and q["crc_pass"]
    assert q["receipt_source_sha"] == f["source_sha"] == SOURCE
    assert q["receipt_request_id"] == f["request_id"] == REQUEST
    assert q["receipt_factory_artifact_id"] == f["artifact_id"] and q["receipt_factory_run_id"] == f["export_run_id"]
    assert q["receipt_zip_sha256"] == f["archive_sha256"] == FACTORY_ZIP
    assert q["receipt_exe_sha256"] == f["exe_sha256"] == EXE
    assert q["receipt_pck_sha256"] == f["pck_sha256"] == PCK
    assert q["receipt_manifest_sha256"] == f["manifest_sha256"] == MANIFEST
    assert q["screenshot_count"] == t["pr20_qa10_screenshots_verified"] == 7
    assert q["screenshot_dimensions"] == [1024, 768] and q["screenshot_sha_and_bytes_match"]
    assert q["hosted_software_runtime_reported_pass"] and q["hosted_runtime_not_36_executed"]
    assert not q["physical_windows_gui_verified"] and not t["physical_gui"]
    assert t["pr20_factory_bytes_independently_verified_by_36"] and t["pr20_qa10_receipt_bytes_independently_verified_by_36"]
    assert t["pr20_factory_qa10_source_request_exe_pck_manifest_match"]
    assert o["prism-route-3d-consumer-pr20"]["source_sha"] == SOURCE
    assert o["prism-route-3d-consumer-qa-pr10"]["receipt_pck_sha256"] == PCK
    assert game["factory_review_head"] == GAME and game["factory_review_ci"] == [41470115915, 41470116296]
    assert game["hosted_gui_artifact_id"] == 13154872780
    assert game["original_source_sha"] == ORIGINAL_GAME and game["factory_artifact_run_head"] != GAME
    assert not game["physical_gui_pass"] and not game["cas"] and not game["msixvc"]
    assert h["legacy_identity_commit"] == t["legacy_identity_return_commit"] == OLD_IDENTITY
    assert not h["legacy_identity_is_pr20_cas"] and not t["legacy_identity_cas_is_new_revision"] and not t["new_cas"]
    assert not t["signed_msix"] and not gates["new_revision_cas"] and not gates["package_version_approved"]
    assert not gates["signed_msix"] and not gates["physical_windows_ja_en_125_150"]
    assert not gates["uncoached_human_30s"] and not gates["real_wall_clock_90s"]
    assert not gates["sale_ready"] and not d["sale_ready_windows_ux_gate"]["sale_ready"]
    assert d["quality_gates"]["prism_pr20_factory_pck_independent_bytes_pass"]
    assert d["quality_gates"]["prism_pr20_qa10_receipt_crosscheck_pass"]
    assert not d["quality_gates"]["prism_pr20_physical_gui_pass"]
    assert not d["quality_gates"]["local_source_code_sync_physical_pass"]
    assert not d["quality_gates"]["local_source_code_sync_scheduler_pass"]
    assert d["multi_product_partner_center_batch_4"]["processed_count"] == 0
    assert d["current_identity_projection"]["github_identity_returned"] == 2
    assert not d["e2e_pass"]


class CurrentPr20Provenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_current_exact_byte_provenance_fail_closed(self):
        validate(self.ledger)

    def reject(self, mutate):
        bad = copy.deepcopy(self.ledger)
        mutate(bad)
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_old_pr19_artifact_cannot_replace_pr20(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("artifact_id", 13142680551))

    def test_pr20_quality_ci_cannot_claim_export_artifact(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0043_pr20_qa10_independent_byte_provenance"]["factory"].__setitem__("export_run_id", 41463172000))

    def test_old_pck_cannot_be_new_pck(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0043_pr20_qa10_independent_byte_provenance"]["factory"].__setitem__("pck_sha256", "4036486c320c858b06a43ce632d063a6ab034f273b5f70e7861a5b663d1406fc"))

    def test_wrong_qa_request_rejected(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0043_pr20_qa10_independent_byte_provenance"]["qa"].__setitem__("receipt_request_id", "3d-prism-route-3d-0878f48c7907"))

    def test_wrong_screenshot_count_rejected(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0043_pr20_qa10_independent_byte_provenance"]["qa"].__setitem__("screenshot_count", 6))

    def test_old_gate1_identity_cannot_be_new_cas(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("new_cas", True))

    def test_review_game_head_cannot_be_original_source(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["game"].__setitem__("original_source_sha", GAME))

    def test_cloud_runtime_cannot_be_physical(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0043_pr20_qa10_independent_byte_provenance"]["qa"].__setitem__("physical_windows_gui_verified", True))

    def test_cloud_cursor_cannot_be_local_batch(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"].__setitem__("processed_count", 4))


if __name__ == "__main__":
    unittest.main()
