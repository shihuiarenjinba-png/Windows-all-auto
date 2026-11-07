"""Prism PR19 actual Factory ZIP bytes and QA9 hosted receipt: fail-closed provenance.

These are ledger regression fixtures. They do not replace the independently
downloaded ZIP/EXE/PCK/manifest and QA receipt hash check, nor physical QA.
"""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
SOURCE = "0878f48c79073596e30fed37a5703e0826389862"
REQUEST = "3d-prism-route-3d-0878f48c7907"
ZIP = "447c18e789acc1b1ca12c08bdce8b3cda030baf0c7abc70a452bde7e0c748800"
EXE = "66b26ad96df7458ea917b632a73ac7c88bb058db24dbd11a457fd50435ab7b13"
PCK = "4036486c320c858b06a43ce632d063a6ab034f273b5f70e7861a5b663d1406fc"
MANIFEST = "5d06d46fc2a3a19325e77edc311f4dcb58d456c0dc9df5e872242b8c6098f11e"
QA_ZIP = "53173d2ec94a411bb24d34ec6ff3a3d8f4dcb6eb7eb8034ef83f56e382b247d4"


def validate(d):
    r = d["revision_review_reconciliation"]
    proof = r["latest_20261102_2350_pr19_byte_provenance"]
    f = proof["factory"]
    q = proof["qa"]
    h = proof["historical"]
    g = proof["gates"]
    current = r["historical_four_lane_observation_20261102_2350"]["three_d"]
    first = r["observations"]["prism-route-3d-first30s-pr19"]
    qa = r["observations"]["prism-route-3d-consumer-qa-pr9"]
    old_snapshot = r["latest_20261102_2241_review_provenance"]["three_d_qa"]
    assert proof["writer"] == "36_WINDOWS_E2E_ONLY"
    assert f["draft_pr"] == current["factory_pr"] == 19
    assert f["review_head"] == f["export_run_head"] == current["head"] == SOURCE
    assert f["manifest_source_sha"] == f["manifest_factory_build_head"] == SOURCE
    assert f["manifest_request_id"] == current["new_request_id"] == first["request_id"] == REQUEST
    assert f["quality_ci_run_id"] == 41444886971
    assert f["quality_ci_artifact_count"] == current["factory_quality_ci_artifact_count"] == 0
    assert f["export_run_id"] == current["artifact_run_id"] == 41444879105
    assert f["artifact_id"] == current["artifact_id"] == qa["factory_artifact_id_referenced_in_workflow"] == 13142680551
    assert f["artifact_id"] != h["pr18_artifact_id"] == current["historical_pr18_build"]["artifact_id"]
    assert f["archive_sha256"] == current["artifact_metadata_digest"].removeprefix("sha256:") == ZIP
    assert f["exe_sha256"] == first["real_factory_export_exe_sha256"] == EXE
    assert f["pck_sha256"] == first["real_factory_export_pck_sha256"] == PCK
    assert f["manifest_sha256"] == first["real_factory_export_manifest_sha256"] == MANIFEST
    assert f["exe_size_bytes"] == 84214784 and f["pck_size_bytes"] == 6979328
    assert f["artifact_size_bytes"] == 37793096 and not f["artifact_expired"]
    assert f["zip_crc_pass"] and f["independent_36_bytes_verified"]
    assert f["exact_member_names"] == ["candidate.exe", "candidate.pck", "export-evidence.json"]
    assert current["pr19_new_pck_verified_by_36"] and current["factory_export_independent_zip_crc_pass"]
    assert first["qa9_factory_artifact_independently_rehashed_by_36"]
    assert qa["factory_artifact_independently_verified_by_36"]
    assert q["software_runtime_artifact_id"] == qa["hosted_qa_artifact_id"] == 13145583388
    assert q["software_runtime_artifact_sha256"] == qa["hosted_qa_artifact_byte_sha256_rehashed_by_36"] == QA_ZIP
    assert q["receipt_factory_artifact_id"] == f["artifact_id"]
    assert q["receipt_factory_run_id"] == f["export_run_id"]
    assert q["receipt_source_sha"] == f["manifest_source_sha"] == qa["qa_receipt_source_sha"]
    assert q["receipt_request_id"] == f["manifest_request_id"] == qa["qa_receipt_request_id"]
    assert q["receipt_factory_zip_sha256"] == f["archive_sha256"] == qa["qa_receipt_zip_sha256"]
    assert q["receipt_exe_sha256"] == f["exe_sha256"]
    assert q["receipt_pck_sha256"] == f["pck_sha256"] == qa["qa_receipt_pck_sha256"]
    assert q["receipt_manifest_sha256"] == f["manifest_sha256"]
    assert q["receipt_godot_pck_executed_this_run"] and q["receipt_software_screenshot_count"] == 7
    assert q["receipt_japanese_font_glyphs_available"]
    assert q["independent_36_receipt_bytes_verified"] and q["source_request_and_pck_match_factory_bytes"]
    assert q["hosted_software_runtime_not_36_executed"]
    assert old_snapshot["artifact_metadata_only"] and not old_snapshot["independent_pck_rehash_by_36"]
    assert not h["old_identity_not_pr19_cas"] is False
    assert h["gate1_identity_return_commit"] == "11417b75636ee18816028ffd5221884c4c9a9836"
    assert h["pr18_source_sha"] != SOURCE and h["old_artifact_cannot_substitute_for_pr19"]
    assert not current["new_cas"] and not current["signed_msix"] and not current["physical_gui"]
    assert not qa["physical_user_pc_gui_pass"] and not qa["real_msix_pass"]
    assert not g["physical_windows_1024x768_125_150"] and not g["uncoached_human_30s"]
    assert not g["new_source_identity_cas"] and not g["signed_msix"] and not g["sale_ready"]
    assert d["quality_gates"]["prism_pr19_factory_pck_independent_bytes_pass"]
    assert d["quality_gates"]["prism_pr19_qa_receipt_crosscheck_pass"]
    assert not d["quality_gates"]["local_source_code_sync_physical_pass"]
    assert not d["quality_gates"]["local_source_code_sync_scheduler_pass"]
    assert not d["quality_gates"]["real_msix_pass"] and not d["quality_gates"]["gui_qa_pass"]
    assert not d["e2e_pass"] and not d["sale_ready_windows_ux_gate"]["sale_ready"]
    assert d["multi_product_partner_center_batch_4"]["processed_count"] == 0
    assert d["current_identity_projection"]["github_identity_returned"] == 2


class PrismIndependentFactoryBytes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_real_byte_proof_without_sale_ready(self):
        validate(self.ledger)

    def reject(self, mutate):
        bad = copy.deepcopy(self.ledger)
        mutate(bad)
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_reject_old_pr18_artifact_as_new_factory_export(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_20261102_2350"]["three_d"].__setitem__("artifact_id", 13130487252))

    def test_reject_old_prism_identity_as_new_cas(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_20261102_2350"]["three_d"].__setitem__("new_cas", True))

    def test_reject_factory_quality_ci_as_artifact_run(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261102_2350_pr19_byte_provenance"]["factory"].__setitem__("export_run_id", 41444886971))

    def test_reject_mismatched_factory_pck(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261102_2350_pr19_byte_provenance"]["factory"].__setitem__("pck_sha256", "7a7d5243452786dcb7eb265d1dbdd6309e596f9d370d73bf0d8f8023b5096060"))

    def test_reject_mismatched_qa_request(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261102_2350_pr19_byte_provenance"]["qa"].__setitem__("receipt_request_id", "3d-prism-route-3d-3c5a1e683711"))

    def test_reject_mismatched_qa_zip(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261102_2350_pr19_byte_provenance"]["qa"].__setitem__("receipt_factory_zip_sha256", "0" * 64))

    def test_reject_qa_hosted_as_physical(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr9"].__setitem__("physical_user_pc_gui_pass", True))

    def test_reject_new_cas_gate_promotion(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261102_2350_pr19_byte_provenance"]["gates"].__setitem__("new_source_identity_cas", True))

    def test_reject_fake_local_batch(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"].__setitem__("processed_count", 4))


if __name__ == "__main__":
    unittest.main()
