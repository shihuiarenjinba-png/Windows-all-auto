"""Fail-closed evidence boundaries for expired APP4 GitHub Actions artifacts.

Historical ZIP custody in ChatGPT Library is not live GitHub availability and
does not prove a physical Windows readback. This test uses no network or writes.
"""
import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
RUNS = {
    "focus-session-desk": 40668807091,
    "file-integrity-ledger": 40711443897,
    "offline-text-diff-desk": 40686212829,
    "offline-image-inventory-desk": 40693150965,
}
IMAGE_REVIEW = "25a93052dad41e1844c31fe84384714764a5ac4f"
IMAGE_OLD = "886b9214b9cc79b35403ca168ca09df7a2e12404"


def validate(d):
    b = d["multi_product_partner_center_batch_4"]
    q = d["revision_review_reconciliation"]
    a = q["current_app4_actions_artifact_availability"]
    m = d["mixed_rotation_live_recheck"]
    t = d["last_36_execution"]
    obs = q["observations"]["offline-image-inventory-desk"]
    current = q["current_four_lane_observation"]["app"]
    assert a["writer"] == "36_WINDOWS_E2E_ONLY"
    assert a["github_actions_available_count"] == 0
    assert a["github_actions_expired_or_unavailable_count"] == 4
    assert a["library_archives_preserved_count"] == 4
    assert a["library_prior_digest_readback_verified_count"] == 4
    assert a["user_pc_archive_rehash_verified_count"] == 0
    assert a["physical_processed_count"] == b["processed_count"] == 0
    assert a["cloud_discovered_count"] == b["cloud_preflight_discovered_count"] == 4
    assert a["local_batch_discovered_count"] == b["local_batch_discovered_count"] == 0
    assert a["github_identity_returned_count"] == 2
    assert a["github_identity_pending_count"] == 2
    assert not a["allow_actions_redownload"]
    assert not a["allow_regeneration"] and not a["allow_cas"]
    assert not a["allow_store_operations"] and not a["task_scheduler_receipt_present"]
    assert not a["real_msix_gdk_checker_install_gui_pass"]
    assert b["artifact_live_recheck"]["artifact_unexpired_count"] == 0
    assert b["artifact_live_recheck"]["github_actions_artifacts_available_count"] == 0
    assert b["artifact_live_recheck"]["artifact_expired_or_unavailable_count"] == 4
    assert m["artifact_live_recheck"]["available_count"] == 0
    assert m["artifact_live_recheck"]["expired_count"] == 4
    assert t["app_artifact_metadata_recheck"]["available_count"] == 0
    assert t["focus_artifact_expiry_recheck"]["expired"]
    assert not t["focus_artifact_expiry_recheck"]["download_allowed"]
    preserved = (
        q["artifact_byte_preservation_20261102"]["records"]
        + q["artifact_byte_preservation_image_20261102"]["records"]
    )
    assert len(preserved) == 4
    by_slug = {r["slug"]: r for r in preserved}
    records = {r["slug"]: r for r in a["records"]}
    assert len(records) == len(b["products"]) == 4
    assert set(records) == set(RUNS) == set(by_slug)
    assert set(a["exact_workflow_run_ids"]) == set(RUNS.values())
    now = datetime.fromisoformat(a["observed_at_utc"].replace("Z", "+00:00"))
    for product in b["products"]:
        slug = product["slug"]
        r = records[slug]
        archive = by_slug[slug]
        assert r["run_id"] == RUNS[slug]
        assert r["historical_artifact_id"] == product["artifact_id"] == archive["artifact_id"]
        assert r["source_sha"] == product["source_sha"]
        assert r["request_id"] == product["request_id"]
        assert r["github_run_artifact_list_count"] == 0
        assert not r["github_artifact_download_allowed"]
        assert not r["user_pc_readback_verified"]
        assert "EXPIRED" in r["live_metadata_status"]
        assert "PRESENT_UNEXPIRED" not in product["artifact_live_metadata_status"]
        assert not product["github_actions_download_allowed"]
        assert product["github_actions_current_artifacts_count"] == 0
        assert product["library_archive_sha256"] == r["library_archive_sha256"] == archive["archive_sha256"]
        assert r["library_embedded_exe_sha256"] == archive["exe_sha256"]
        assert r["library_path"] == archive["library_path"]
        assert r["library_archive_prior_readback_verified"]
        assert "NO_REGEN_NO_CAS" in r["archive_reuse_condition"]
        expiry = datetime.fromisoformat(product["artifact_expiry_utc"].replace("Z", "+00:00"))
        assert expiry < now
    assert all(j["artifact_expired"] and not j["github_actions_artifact_download_allowed"] for j in m["jobs"])
    assert all(c["expired"] and c["github_actions_current_artifacts_count"] == 0
               and not c["download_allowed"] and c["digest_matched"] is None
               for c in m["latest_app_remote_evidence"]["artifact_checks"])
    assert obs["current_review_head_sha"] == current["head"] == IMAGE_REVIEW
    assert obs["previous_review_head_sha"] == current["previous_review_head"] == IMAGE_OLD
    assert obs["review_head_compare"] == "AHEAD_4_BEHIND_0_FROM_886B9214"
    assert {c["run_id"] for c in obs["exact_head_ci"]} == {41477415558, 41477415526}
    assert not obs["current_review_revision_promoted"]
    assert obs["new_revision_source_sha"] is None and obs["new_revision_request_id"] is None
    assert obs["immutable_pre_identity_source_sha"] != IMAGE_REVIEW
    assert obs["independent_buyers_completed"] == 0 and obs["score"] == 64
    assert not obs["physical_os_dpi_receipt_verified"]
    assert q["historical_image_review_observation_886b9214"]["current_review_head_sha"] == IMAGE_OLD
    assert q["focus_artifact_expiry_current"]["github_current_artifacts_count"] == 0
    assert not q["focus_artifact_expiry_current"]["github_download_allowed"]
    assert not d["e2e_pass"] and not d["sale_ready_windows_ux_gate"]["sale_ready"]


class App4ActionsExpiryBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_current_observation(self):
        validate(self.ledger)

    def reject(self, change):
        bad = copy.deepcopy(self.ledger)
        change(bad)
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_reject_expired_artifact_claimed_present(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["products"][0].__setitem__(
            "artifact_live_metadata_status", "GITHUB_ACTIONS_ARTIFACT_PRESENT_UNEXPIRED_DIGEST_MATCH"))

    def test_reject_archive_count_as_live_actions_count(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_app4_actions_artifact_availability"].__setitem__(
            "github_actions_available_count", 4))

    def test_reject_preserved_zip_as_downloadable_actions_artifact(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_app4_actions_artifact_availability"]["records"][0].__setitem__(
            "github_artifact_download_allowed", True))

    def test_reject_stale_image_review_sha(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["offline-image-inventory-desk"].__setitem__(
            "current_review_head_sha", IMAGE_OLD))

    def test_reject_old_image_ci(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["observations"]["offline-image-inventory-desk"].__setitem__(
            "exact_head_ci", [{"run_id": 41449337747}]))

    def test_reject_archive_digest_cross_product(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_app4_actions_artifact_availability"]["records"][0].__setitem__(
            "library_archive_sha256", d["revision_review_reconciliation"]["current_app4_actions_artifact_availability"]["records"][1]["library_archive_sha256"]))

    def test_reject_future_expiry_fabrication(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"]["products"][0].__setitem__(
            "artifact_expiry_utc", "2030-01-01T00:00:00Z"))

    def test_reject_local_readback_fabrication(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_app4_actions_artifact_availability"].__setitem__(
            "user_pc_archive_rehash_verified_count", 4))

    def test_reject_cloud_cursor_as_local_batch(self):
        self.reject(lambda d: d["multi_product_partner_center_batch_4"].__setitem__("processed_count", 4))

    def test_reject_false_cas(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_app4_actions_artifact_availability"].__setitem__(
            "allow_cas", True))

    def test_reject_false_store_permission(self):
        self.reject(lambda d: d["revision_review_reconciliation"]["current_app4_actions_artifact_availability"].__setitem__(
            "allow_store_operations", True))


if __name__ == "__main__":
    unittest.main()
