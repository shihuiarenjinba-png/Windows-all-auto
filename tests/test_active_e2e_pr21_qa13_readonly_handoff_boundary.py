"""QA13 historical read-only binary handoff is byte-verified, never physical Windows or Store approval."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
SOURCE = "066d9f51d58cfecb994665d5c31adb1156c38942"
REQUEST = "3d-prism-route-3d-066d9f51d58c"
QA12 = "235b002571013eb82c2a561d463ac677c3cf7742"
QA13 = "79dc89f7d609e6f2a9f91543a0c0eadf5e8138fb"
HANDOFF_SHA = "816ac6dbca535e92b75bbc8f613b27559af1c35b913eab5bf6fb2bf7338a81f0"
FACTORY_ZIP_SHA = "1a19000c225b5165a1280ec36b4dcf5eaec4287e39d50f86512b8e9f5ad4dd44"
PCK_SHA = "a27c198ff4bdaa961780b4e42d5fb429c328c5bad0b5cb816e399c06e3fd8cb9"
GATE1 = "11417b75636ee18816028ffd5221884c4c9a9836"


def validate(d):
    r = d["revision_review_reconciliation"]
    c = r["historical_four_lane_observation_before_20261103_0636"]
    t = c["three_d"]
    current = r["observations"]["prism-route-3d-consumer-qa-pr13"]
    historical = r["historical_four_lane_observation_20261103_0236"]["three_d"]
    qa12 = r["observations"]["prism-route-3d-consumer-qa-pr12"]
    proof = r["latest_20261103_0336_pr21_qa13_handoff_independent_byte_provenance"]
    gates = r["cross_lane_gates"]

    assert r["writer"] == c["writer"] == proof["writer"] == "36_WINDOWS_E2E_ONLY"
    assert t["factory_pr"] == 21 and t["head"] == t["source_sha"] == SOURCE
    assert t["new_request_id"] == REQUEST and t["artifact_id"] == 13155398069
    assert t["qa_pr"] == current["draft_pr"] == 13
    assert t["qa_head"] == current["review_head_sha"] == current["handoff_artifact_head_sha"] == QA13
    assert t["qa_ci"] == current["ci_runs"] == [41500441890, 41500441464]
    assert current["ci_conclusion"] == "SUCCESS_BOTH_RUNS"
    assert current["compare"] == "AHEAD_6_BEHIND_0_FROM_QA12" and current["changed_files"] == 5
    assert current["previous_qa12_head_sha"] == historical["qa_head"] == QA12
    assert historical["qa_pr"] == 12 and not qa12["is_current_review_head"]
    assert qa12["qa12_independent_36_artifact_byte_rehash"]
    assert t["qa12_independent_36_artifact_byte_rehash"]
    assert current["qa12_historical_artifact_id"] == 13158359758
    assert current["handoff_artifact_id"] == t["qa13_handoff_artifact_id"] == proof["handoff_artifact_id"] == 13168745891
    assert current["handoff_run_id"] == 41500441890
    assert current["handoff_artifact_metadata_digest"] == "sha256:" + HANDOFF_SHA
    assert current["handoff_artifact_size_bytes"] == 129515493 and not current["handoff_artifact_expired"]
    assert current["independent_36_handoff_outer_zip_sha256"] == t["qa13_handoff_zip_sha256"] == proof["handoff_outer_zip_sha256"] == HANDOFF_SHA
    assert current["independent_36_outer_zip_crc_pass"] and proof["handoff_outer_zip_crc_pass"]
    assert current["independent_36_embedded_factory_zip_sha256"] == proof["embedded_factory_original_zip_sha256"] == FACTORY_ZIP_SHA
    assert current["independent_36_factory_zip_crc_pass"] and proof["embedded_factory_zip_crc_pass"]
    assert current["independent_36_pck_sha256"] == proof["pck_sha256"] == PCK_SHA
    assert current["independent_36_factory_members_match_handoff"]
    assert current["independent_36_source_request_receipt_match"]
    assert current["independent_36_qa11_screenshot_count"] == proof["software_pngs_verified"] == 7
    assert current["independent_36_qa11_screenshot_hash_size_dimensions_match"] and proof["software_png_sha_size_1024x768_pass"]
    assert current["factory_pr21_source_sha"] == proof["factory_source_sha"] == SOURCE
    assert current["factory_pr21_request_id"] == proof["factory_request_id"] == REQUEST
    assert current["factory_pr21_artifact_id"] == 13155398069
    assert current["hosted_software_artifact_id"] == 13168032881
    assert not current["hosted_software_artifact_independent_36_byte_rehash"]
    assert current["handoff_template_sessions"] == proof["physical_template_sessions"] == 4
    assert current["handoff_template_physical_png_placeholders"] == proof["physical_template_png_placeholders"] == 24
    assert current["physical_pngs_captured"] == proof["physical_pngs_captured"] == 0
    assert current["code_integrity_status"] == proof["code_integrity_status"] == "NOT_CHECKED"
    assert not current["physical_operator_receipt_present"] and not proof["physical_operator_receipt_present"]
    assert not current["physical_windows_gui_pass"] and not current["human_first30s_pass"]
    assert not current["human_real90s_pass"] and not proof["physical_windows_pass"]
    assert not current["is_new_factory_pck"] and not current["is_new_identity_cas"]
    assert t["legacy_identity_return_commit"] == GATE1
    assert not t["legacy_identity_cas_is_new_revision"] and not t["new_cas"]
    assert not current["approved_package_version"] and not current["signed_msix"]
    assert current["store_submission"] == "NOT_PERFORMED" and not current["sale_ready"]
    assert d["quality_gates"]["prism_pr21_qa13_readonly_handoff_independent_bytes_pass"]
    assert not d["quality_gates"]["prism_pr21_qa13_physical_human_gate_pass"]
    assert gates["prism_pr21_qa13_readonly_handoff_independent_bytes_pass"]
    assert not gates["prism_pr21_qa13_physical_human_pass"]
    assert proof["app_identity_returned"] == 2 and proof["app_cloud_discovered"] == 4
    assert proof["app_physical_processed"] == d["multi_product_partner_center_batch_4"]["processed_count"] == 0
    assert not d["quality_gates"]["local_source_code_sync_physical_pass"]
    assert not d["quality_gates"]["local_source_code_sync_scheduler_pass"]
    assert not d["e2e_pass"] and not d["sale_ready_windows_ux_gate"]["sale_ready"]


class Qa13ReadOnlyHandoffBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_exact_current_provenance_and_holds(self):
        validate(self.ledger)

    def reject(self, mutate):
        bad = copy.deepcopy(self.ledger)
        mutate(bad)
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_reject_stale_qa12_as_current(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_before_20261103_0636"]["three_d"].__setitem__("qa_head", QA12))

    def test_reject_qa12_artifact_as_current_handoff(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr13"].__setitem__("handoff_artifact_id", 13158359758))

    def test_reject_old_pr20_factory_pck(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr13"].__setitem__("independent_36_pck_sha256", "10acb61a586caa55b2da59ed0aae62f0952cfbaf7a69cac3cf219f3ae2a982c9"))

    def test_reject_qa13_metadata_without_independent_zip(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr13"].__setitem__("independent_36_handoff_outer_zip_sha256", "sha256:unverified"))

    def test_reject_false_physical_pass(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr13"].__setitem__("physical_windows_gui_pass", True))

    def test_reject_fake_operator_receipt(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr13"].__setitem__("physical_operator_receipt_present", True))

    def test_reject_template_count_as_captured_physical_pngs(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr13"].__setitem__("physical_pngs_captured", 24))

    def test_reject_unverified_code_integrity_as_pass(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr13"].__setitem__("code_integrity_status", "ALLOWED_BY_EXISTING_POLICY"))

    def test_reject_old_identity_as_new_cas(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["historical_four_lane_observation_before_20261103_0636"]["three_d"].__setitem__("new_cas", True))

    def test_reject_unsigned_msix_as_signed(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["prism-route-3d-consumer-qa-pr13"].__setitem__("signed_msix", True))

    def test_reject_cloud_cursor_as_local_processed(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"].__setitem__("processed_count", 4))

    def test_reject_false_scheduler_pass(self):
        self.reject(lambda d: d["quality_gates"].__setitem__("local_source_code_sync_scheduler_pass", True))


if __name__ == "__main__":
    unittest.main()
