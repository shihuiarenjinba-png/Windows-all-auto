"""09:36 APP4 accounting: GitHub Identity returns are NOT physical operator processing."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
FOCUS = "8a7139375524830bf823469526837259266172be"
LEDGER_RETURN = "db9a57af822788af4c8384499a6e343ec7b0353d"
GAME_SOURCE = "c058cbf7fe38e02d929c67d047d717ff74bd522e"
PRISM_SOURCE = "f4b458384243fdf379683ca793329614f61c9ead"
ROUTES = {"MSIX_OR_PWA_APP", "EXE_OR_MSI_APP", "GDK_GAME", "MSIX_OR_PWA_GAME"}
STAMP = "2026-11-03T00:37:35Z"


def validate(d):
    b = d["multi_product_partner_center_batch_4"]
    cohort = d["rotation_cohorts"]["app_jobs"]
    p = b["identity_return_accounting"]
    q = b["physical_operator_accounting"]
    projection = d["current_identity_projection"]
    live = d["revision_review_reconciliation"]["latest_20261103_0936_batch4_identity_vs_physical_accounting"]
    r = d["revision_review_reconciliation"]
    assert d["updated_at_utc"] > r["observed_at_utc"] == STAMP
    assert p["observed_at_utc"] == q["observed_at_utc"] == live["observed_at_utc"] == STAMP
    assert p["source"] == "TWO_EXACT_GITHUB_APPROVED_IDENTITY_FILES_READ_AT_RETURN_COMMITS__NOT_LOCAL_PC_RECEIPTS"
    assert q["source"] == "NO_TRUSTED_USER_PC_BATCH_RECEIPT__NO_OS_TASK_SCHEDULER_RECEIPT"
    assert b["batch_total"] == 4 and len(b["products"]) == len(cohort) == 4
    assert b["cloud_preflight_discovered_count"] == q["cloud_preflight_discovered_count"] == 4
    assert b["local_batch_discovered_count"] == q["local_batch_discovered_count"] == 0
    assert b["processed_count"] == b["success_count"] == 0
    assert b["physical_operator_processed_count"] == q["physical_operator_processed_count"] == 0
    assert b["physical_operator_success_count"] == q["physical_operator_success_count"] == 0
    assert q["legacy_processed_count"] == q["legacy_success_count"] == 0
    assert "PHYSICAL_LOCAL_OPERATOR_EXECUTION_ONLY" in b["legacy_processed_count_scope"]
    assert "PHYSICAL_LOCAL_OPERATOR_SUCCESS_RECEIPTS_ONLY" in b["legacy_success_count_scope"]
    assert b["github_identity_returned_count"] == p["github_identity_returned_count"] == 2
    assert b["github_identity_return_pending_count"] == p["github_return_pending_count"] == 2
    assert p["post_identity_ready_count"] == p["pre_identity_ready_count"] == 2
    assert len(p["verified_return_receipts"]) == len(p["pending_identity_returns"]) == 2
    assert b["next_resume_index"] == 3 and "NOT_LOCAL_PROCESSING" in b["next_resume_index_semantics"]
    assert [x["status"] for x in cohort] == ["POST_IDENTITY_READY", "POST_IDENTITY_READY", "PRE_IDENTITY_READY", "PRE_IDENTITY_READY"]
    assert [x["current_identity_state"] for x in b["products"]] == [x["status"] for x in cohort]
    assert [x["github_return_status"] for x in b["products"]] == [
        "APPLIED__GITHUB_RETURN_COMMIT_VERIFIED", "APPLIED__GITHUB_RETURN_COMMIT_VERIFIED", "NOT_RUN", "NOT_RUN"
    ]
    expected = [
        ("focus-session-desk", FOCUS, "00c56e85ec7590783284e372ba100a3127614971"),
        ("file-integrity-ledger", LEDGER_RETURN, "78034cf62be3479f9ed752a2585ab31bb24c49ff"),
    ]
    for i, (slug, commit, blob) in enumerate(expected):
        rec, product, job = p["verified_return_receipts"][i], b["products"][i], cohort[i]
        assert rec["slug"] == product["slug"] == job["slug"] == slug
        assert rec["github_return_commit_sha"] == product["identity_return_commit_sha"] == commit
        assert rec["identity_file_blob_sha"] == blob
        assert rec["request_id"] == product["request_id"] == job["request_id"]
        assert rec["source_sha"] == product["source_sha"] == job["source_sha"]
        assert rec["identity_file_path"] == job["identity_return_target"]
        assert rec["registration_type"] == job["registration_type"] == "MSIX_OR_PWA_APP"
        assert rec["verified_at_utc"] == STAMP
        assert rec["github_identity_return_verified"] and not rec["physical_local_receipt_verified"]
        assert not rec["cas_applied_by_36"]
    for i, rec in enumerate(p["pending_identity_returns"], start=2):
        product, job = b["products"][i], cohort[i]
        assert rec["slug"] == product["slug"] == job["slug"]
        assert rec["request_id"] == job["request_id"] and rec["source_sha"] == job["source_sha"]
        assert rec["identity_file_path"] == job["identity_return_target"]
        assert rec["registration_type"] == "MSIX_OR_PWA_APP"
        assert rec["github_return_commit_sha"] is None and not rec["github_identity_return_verified"]
        assert not rec["physical_local_receipt_verified"] and rec["status"].startswith("PRE_IDENTITY_READY")
        assert product["identity_return_commit_sha"] is None
    assert p["no_duplicate_identity_request"] and p["no_identity_cas_authorized"]
    assert p["no_new_product_creation_authorized"] and p["distinct_from_physical_operator_processed_count"]
    archive = b["artifact_live_recheck"]
    assert archive["github_actions_artifacts_available_count"] == q["github_actions_live_artifacts_available_count"] == 0
    assert archive["library_zip_archives_preserved_count"] == q["library_zip_archives_preserved_count"] == 4
    assert archive["user_pc_archive_rehash_verified_count"] == q["physical_local_archive_readback_count"] == 0
    assert all(not x["github_artifact_download_allowed"] for x in archive["artifacts"])
    assert not q["task_scheduler_receipt_verified"] and not q["scheduled_trigger_proven"]
    assert q["local_code_sync"] == "CLOUD_PASS_ONLY"
    assert not q["real_signed_msix_or_gdk_pass"] and not q["backlog_pass"]
    assert not q["checker_pass"] and not q["install_gui_pass"]
    assert q["no_store_upload_or_submission"] and not d["e2e_pass"]
    assert projection["github_identity_returned"] == 2 and projection["physical_local_processed"] == 0
    assert projection["latest_batch4_accounting"]["github_identity_returned"] == 2
    assert projection["latest_batch4_accounting"]["physical_operator_processed"] == 0
    assert projection["latest_batch4_accounting"]["historical_projection_observed_at_utc"] == projection["observed_at_utc"]
    assert projection["latest_batch4_accounting"]["no_local_pass"]
    assert live["github_returned"] == 2 and live["github_pending"] == 2
    assert live["cloud_discovered"] == 4 and live["local_discovered"] == live["physical_processed"] == 0
    assert live["actions_artifacts_live"] == 0 and live["library_archives_preserved"] == 4
    assert live["user_pc_readback"] == 0 and not live["physical_scheduler_receipt"]
    assert live["local_code_sync"] == "CLOUD_PASS_ONLY"
    assert set(d["registration_router"]["allowed_types"]) == set(live["registration_types"]) == ROUTES
    assert live["app4_registration_type"] == "MSIX_OR_PWA_APP"
    assert live["game_registration_type"] == "GDK_GAME"
    assert live["prism_registration_type"] == "MSIX_OR_PWA_GAME"
    assert d["active_product"]["source_sha"] == live["immutable_game_source_sha"] == GAME_SOURCE
    assert d["active_product"]["request_id"] == live["immutable_game_request_id"] == "game-signal-sprint-" + GAME_SOURCE
    assert live["prism_current_review_source_sha"] == r["current_four_lane_observation"]["three_d"]["source_sha"] == PRISM_SOURCE
    assert live["prism_current_review_request_id"] == r["current_four_lane_observation"]["three_d"]["new_request_id"] == "3d-prism-route-3d-f4b458384243"
    assert GAME_SOURCE != PRISM_SOURCE and all(x["source_sha"] not in (GAME_SOURCE, PRISM_SOURCE) for x in cohort)
    assert not r["current_four_lane_observation"]["three_d"]["legacy_identity_cas_is_new_revision"]
    assert not live["real_msix"] and not live["gdk_msixvc"] and not live["identity_cas"]
    assert not live["store_upload"] and not live["store_submit"] and not live["physical_gui"] and not live["e2e_pass"]


class Batch4SeparateEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_current_ledger(self):
        validate(self.data)

    def reject(self, change):
        d = copy.deepcopy(self.data)
        change(d)
        with self.assertRaises(AssertionError):
            validate(d)

    def test_reject_false_physical_processed_two(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"].__setitem__("processed_count", 2))

    def test_reject_false_physical_success_two(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["physical_operator_accounting"].__setitem__("physical_operator_success_count", 2))

    def test_reject_false_four_github_returns(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["identity_return_accounting"].__setitem__("github_identity_returned_count", 4))

    def test_reject_returned_focus_regressed_to_pre(self):
        self.reject(lambda d: d["rotation_cohorts"]["app_jobs"][0].__setitem__("status", "PRE_IDENTITY_READY"))

    def test_reject_pending_image_promoted_to_post(self):
        self.reject(lambda d: d["rotation_cohorts"]["app_jobs"][3].__setitem__("status", "POST_IDENTITY_READY"))

    def test_reject_wrong_identity_return_commit(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["identity_return_accounting"]["verified_return_receipts"][0].__setitem__("github_return_commit_sha", LEDGER_RETURN))

    def test_reject_stale_identity_blob_receipt(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["identity_return_accounting"]["verified_return_receipts"][1].__setitem__("identity_file_blob_sha", "0" * 40))

    def test_reject_stale_identity_receipt_time(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["identity_return_accounting"]["verified_return_receipts"][0].__setitem__("verified_at_utc", "2026-10-28T00:00:00Z"))

    def test_reject_cross_app_request_swap(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["identity_return_accounting"]["verified_return_receipts"][0].__setitem__("request_id", d["rotation_cohorts"]["app_jobs"][1]["request_id"]))

    def test_reject_app_game_registration_swap(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["identity_return_accounting"]["verified_return_receipts"][0].__setitem__("registration_type", "GDK_GAME"))

    def test_reject_missing_fourth_routing_type(self):
        self.reject(lambda d: d["registration_router"].__setitem__("allowed_types", ["MSIX_OR_PWA_APP", "GDK_GAME", "MSIX_OR_PWA_GAME"]))

    def test_reject_game_request_from_prism(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0936_batch4_identity_vs_physical_accounting"].__setitem__("immutable_game_request_id", "3d-prism-route-3d-f4b458384243"))

    def test_reject_prism_source_from_game(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0936_batch4_identity_vs_physical_accounting"].__setitem__("prism_current_review_source_sha", GAME_SOURCE))

    def test_reject_old_prism_identity_as_new_cas(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_four_lane_observation"]["three_d"].__setitem__("legacy_identity_cas_is_new_revision", True))

    def test_reject_library_archive_as_live_actions(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["physical_operator_accounting"].__setitem__("github_actions_live_artifacts_available_count", 4))

    def test_reject_physical_archive_readback_without_receipt(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["physical_operator_accounting"].__setitem__("physical_local_archive_readback_count", 4))

    def test_reject_false_scheduler_receipt(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["physical_operator_accounting"].__setitem__("task_scheduler_receipt_verified", True))

    def test_reject_cloud_as_local_pass(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["physical_operator_accounting"].__setitem__("local_code_sync", "LOCAL_PASS"))

    def test_reject_unsigned_exe_as_gdk(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0936_batch4_identity_vs_physical_accounting"].__setitem__("gdk_msixvc", True))

    def test_reject_false_store_submission(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["latest_20261103_0936_batch4_identity_vs_physical_accounting"].__setitem__("store_submit", True))


if __name__ == "__main__":
    unittest.main()
