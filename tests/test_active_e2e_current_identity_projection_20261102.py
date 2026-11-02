"""Current-vs-historical APP identity projection regression (read-only)."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
RETURNED = {
    "Focus Session Desk": ("app-focus-session-desk-8b00bc4e9082", "8b00bc4e90828c4282463826873aa8dfd2eb93f4", "8a7139375524830bf823469526837259266172be"),
    "File Integrity Ledger": ("app-file-integrity-ledger-d1108d12f7d1", "d1108d12f7d1697af30400f97c7db39cba5e6791", "db9a57af822788af4c8384499a6e343ec7b0353d"),
}
PENDING = {
    "Offline Text Diff Desk": ("app-offline-text-diff-desk-a7d372800898", "a7d37280089893a9ea4b9ac3336020a920e73e0c"),
    "Offline Image Inventory Desk": ("app-offline-image-inventory-desk-16b6a772952c", "16b6a772952ca0988f2ae2f8b5f4db2e59ec5877"),
}

def validate_current_projection(data):
    """Fail closed if a ledger subsection disagrees with the evidence projection."""
    jobs = {p["display_name"]: p for p in data["rotation_cohorts"]["app_jobs"]}
    pipeline = {p["product"]: p for p in data["post_identity_pipeline"]["products"]}
    sync = {p["product_name"]: p for p in data["local_source_code_sync"]["products"]}
    batch = {p["product"]: p for p in data["multi_product_partner_center_batch_4"]["products"]}
    requests = {p["product_name"]: p for p in data["user_id_requests"]["items"]}
    expected = set(RETURNED) | set(PENDING)
    assert set(jobs) == set(batch) == expected
    metrics = data["rotation_metrics"]
    projection = data["current_identity_projection"]
    b = data["multi_product_partner_center_batch_4"]
    p = data["post_identity_pipeline"]
    q = data["quality_gates"]
    assert metrics["total_jobs"] == metrics["pre_identity_pass"] == len(expected)
    assert metrics["historical_waiting_user_identity"] == 2
    assert metrics["waiting_user_identity"] == projection["waiting_user_identity"] == 0
    assert metrics["local_operator_return_pending"] == projection["local_operator_return_pending"] == 2
    assert metrics["current_post_identity_ready"] == projection["github_identity_returned"] == 2
    assert metrics["current_pre_identity_ready"] == 2
    assert metrics["identity_received"] == 2
    assert p["post_identity_ready_count"] == 3  # includes legacy Prism
    assert p["identity_return_pending_count"] == p["operator_return_pending_count"] == 2
    assert p["waiting_user_identity_count"] == 0
    assert p["current_app_github_return_count"] == 2
    assert p["current_app_pre_identity_count"] == 2
    assert b["cloud_preflight_discovered_count"] == 4
    assert b["github_verified_return_count"] == 2
    assert b["github_pending_pre_identity_count"] == 2
    assert b["processed_count"] == b["success_count"] == b["hold_count"] == 0
    assert b["local_batch_discovered_count"] == 0
    assert b["next_resume_index"] == 3
    assert b["trigger_proof"] == "BATCH_SCHEDULE_TRIGGER_NOT_PROVEN"
    assert b["current_projection"]["next_resume_index_semantics"] == "CLOUD_LOGICAL_CURSOR_NOT_LOCAL_PROCESSED_COUNT"
    assert b["current_projection"]["physical_local_processed"] == 0
    assert b["current_projection"]["local_operator_return_pending"] == 2
    assert b["current_projection"]["waiting_user_identity"] == 0
    assert q["app_local_operator_return_pending_count"] == 2
    assert q["app_github_identity_return_count"] == 2
    assert q["app_waiting_user_identity_count"] == 0
    assert q["app_physical_local_processed_count"] == 0
    assert q["historical_waiting_user_identity_projection"]
    assert "LOCAL_OPERATOR_RETURN_PENDING" in q["waiting_user_identity"]
    assert not q["local_source_code_sync_physical_pass"]
    assert not q["local_source_code_sync_scheduler_pass"]
    assert not q["app_batch_schedule_trigger_proven"]
    assert not q["app_batch_physical_local_pass"]
    assert not q["real_msix_pass"]
    assert not q["github_backlog_real_product_pass"]
    assert not q["local_pull_pass"]
    assert not q["checker_pass"]
    assert not q["gui_qa_pass"]
    assert not q["e2e_pass"]
    assert not data["e2e_pass"]
    assert not projection["e2e_pass"]
    for name, (request_id, source_sha, commit_sha) in RETURNED.items():
        j, pi, s, result = jobs[name], pipeline[name], sync[name], batch[name]
        assert j["request_id"] == pi["request_id"] == result["request_id"] == request_id
        assert j["source_sha"] == pi["source_sha"] == s["source_sha"] == result["source_sha"] == source_sha
        assert j["status"] == pi["state"] == s["current_pipeline_state"] == result["current_identity_state"] == "POST_IDENTITY_READY"
        assert j["identity_return_commit_sha"] == pi["identity_return_commit_sha"] == s["identity_return_commit_sha"] == result["identity_return_commit_sha"] == commit_sha
        assert s["identity_status"] == "GITHUB_APPROVED_IDENTITY_RETURN_VERIFIED__POST_IDENTITY_READY"
        assert s["historical_identity_status"] == "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE"
        assert j["local_operator_return_status"] == "GITHUB_RETURN_VERIFIED__NO_LOCAL_RECEIPT"
        assert not j["identity_cas_allowed"]
        assert result["source_sync_status"] == "LOCAL_NOT_RUN"
        assert not s["physical_local_snapshot_verified"]
        assert not s["local_operator_receipt_verified"]
    for name, (request_id, source_sha) in PENDING.items():
        j, pi, s, result = jobs[name], pipeline[name], sync[name], batch[name]
        assert j["request_id"] == pi["request_id"] == result["request_id"] == request_id
        assert j["source_sha"] == pi["source_sha"] == s["source_sha"] == result["source_sha"] == source_sha
        assert j["status"] == pi["state"].replace("WAITING_IDENTITY_CAPTURE_AND_CAS", "PRE_IDENTITY_READY") == "PRE_IDENTITY_READY"
        assert s["current_pipeline_state"] == result["current_identity_state"] == "PRE_IDENTITY_READY"
        assert j["identity_status"] == s["identity_status"] == "LOCAL_OPERATOR_RETURN_PENDING__NO_APPROVED_FILE"
        assert j["historical_identity_status"] == "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE__NO_CAPTURE_YET"
        assert s["historical_identity_status"] == "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE"
        assert pi["identity_status"] == "PRE_IDENTITY_READY__NO_APPROVED_FILE"
        assert pi["local_operator_return_status"] == result["local_operator_return_status"] == "LOCAL_OPERATOR_RETURN_PENDING"
        assert j.get("identity_return_commit_sha") is None
        assert pi["identity_return_commit_sha"] is None
        assert result["identity_return_commit_sha"] is None
        assert result["github_return_status"] == "NOT_RUN"
        assert requests[name]["status"] == "LOCAL_OPERATOR_RETURN_PENDING"
        assert requests[name]["historical_status"] == "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE"
        assert requests[name]["user_manual_identity_entry_required"] is False
        assert not j["identity_cas_allowed"]
        assert not s["physical_local_snapshot_verified"]
        assert not s["local_operator_receipt_verified"]
    for product in p["products"]:
        assert product["gates"]["package_version"] == "HOLD_NOT_APPROVED"
        assert product["gates"]["real_msix_or_gdk"] in ("NOT_BUILT", "GDK_PACKAGE_NOT_BUILT")
        assert product["gates"]["github_backlog"] == "NOT_QUEUED_REAL_PACKAGE"
        assert product["gates"]["local_pull"] == "NOT_RUN"
        assert product["gates"]["windows_checker"] == "NOT_RUN"
        assert product["gates"]["gui_install_qa"] == "NOT_RUN"
        assert product["gates"]["store_final_submission"] == "NOT_PERFORMED"

class CurrentIdentityProjectionRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_current_projection(self):
        validate_current_projection(self.data)

    def test_reject_post_identity_demoted_to_pre(self):
        bad = copy.deepcopy(self.data)
        bad["local_source_code_sync"]["products"][3]["identity_status"] = "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE"
        with self.assertRaises(AssertionError):
            validate_current_projection(bad)

    def test_reject_pending_product_inherits_identity(self):
        bad = copy.deepcopy(self.data)
        bad["multi_product_partner_center_batch_4"]["products"][2]["identity_return_commit_sha"] = RETURNED["Focus Session Desk"][2]
        with self.assertRaises(AssertionError):
            validate_current_projection(bad)

    def test_reject_pending_mislabeled_user_identity_wait(self):
        bad = copy.deepcopy(self.data)
        bad["rotation_metrics"]["waiting_user_identity"] = 2
        with self.assertRaises(AssertionError):
            validate_current_projection(bad)

    def test_reject_fake_local_processed_or_scheduler(self):
        for path, value in [(("multi_product_partner_center_batch_4", "processed_count"), 2),
                            (("quality_gates", "local_source_code_sync_physical_pass"), True),
                            (("quality_gates", "app_batch_schedule_trigger_proven"), True)]:
            bad = copy.deepcopy(self.data)
            bad[path[0]][path[1]] = value
            with self.subTest(path=path), self.assertRaises(AssertionError):
                validate_current_projection(bad)

    def test_reject_unapproved_package_or_sale_ready(self):
        for key in ("real_msix_pass", "github_backlog_real_product_pass", "gui_qa_pass", "e2e_pass"):
            bad = copy.deepcopy(self.data)
            bad["quality_gates"][key] = True
            with self.subTest(gate=key), self.assertRaises(AssertionError):
                validate_current_projection(bad)

if __name__ == "__main__":
    unittest.main()
