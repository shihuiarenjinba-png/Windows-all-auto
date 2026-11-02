"""Fail-closed live review-head vs immutable product lineage evidence guards.

This tests the central JSON ledger only. No browser, Store, CAS or local PC
operations are performed. CI success is not a physical Windows QA receipt.
"""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
GAME_HEAD = "b53f89fc0b59871ba8f5cc7c62703bfdcc20d53a"
OLD_GAME_HEAD = "da2068a4a3c17b2742949966944fa1a39f22c626"
IMAGE_HEAD = "886b9214b9cc79b35403ca168ca09df7a2e12404"
QA_HEAD = "8aa8c20e1db0f2c30b91dd4e27cc141b1448d7d7"
NEW_3D_SOURCE = "da6f7c129687922c58c43496da4667ecef903e17"


def validate_live_review_evidence(data):
    active = data["active_product"]
    latest = data["latest_provisioner_heads_observed"]["game"]
    review = data["revision_review_reconciliation"]["observations"]
    game = review["signal-sprint"]
    lineage = active["provisioner_game_gdk_pr"]["new_lineage_contract"]
    staging = lineage["staging_dry_run_evidence"]
    image = review["offline-image-inventory-desk"]
    sentinel = review["prism-route-3d-sentinel"]
    consumer = sentinel["new_consumer_revision"]
    qa = sentinel["independent_3d_qa_pr6"]
    app_jobs = {j["slug"]: j for j in data["rotation_cohorts"]["app_jobs"]}
    batch = data["multi_product_partner_center_batch_4"]
    gates = data["quality_gates"]

    assert active["provisioner_head_observed"] == latest["sha"] == GAME_HEAD
    assert game["current_review_head_sha"] == GAME_HEAD
    assert active["provisioner_game_gdk_pr"]["head_sha"] == GAME_HEAD
    assert lineage["current_head"] == GAME_HEAD
    assert staging["review_head_sha"] == "e69e9b9b96f10426b9a9e3eb7d540a85d49778d6"
    assert staging["historical_at_review_head"] is True
    assert staging["not_current_live_head"] is True
    assert staging["ci_run_id"] == 41392855055
    assert staging["status"] == "NEW_LINEAGE_STAGING_DRY_RUN_HOLD"
    assert staging["artifact_id"] == 13105352227
    assert staging["evidence_boundary"].startswith("12_LANE_REPORTED_")
    assert staging["staging_persisted"] is False
    assert staging["authenticated_cas"] is False
    assert staging["approved_version"] is False
    assert staging["approved_four_gdk_assets"] is False
    assert staging["real_msixvc"] is False
    assert lineage["cas_applied"] is False
    assert lineage["gdk_msixvc_built"] is False
    assert active["cas_returned"] is False
    assert active["original_exe_artifact_audit"]["ready_for_cas"] is False
    assert latest["previous_observation_sha"] == "d77cf88977db943d83cf898aae5bbf027e5aed90"
    commands = "\n".join(active["local_commands"])
    assert GAME_HEAD in commands
    assert OLD_GAME_HEAD not in commands
    assert "ARTIFACT_EXACT_BYTES_HOLD" in commands
    assert "--apply" not in commands
    assert any(OLD_GAME_HEAD in c for c in active["historical_local_commands_20261102_1236"])

    assert image["current_review_head_sha"] == IMAGE_HEAD
    assert image["score"] == 64 and image["independent_buyers_completed"] == 0
    assert image["market_fit_gate"] == "MARKET_FIT_HOLD"
    assert image["current_review_revision_promoted"] is False
    assert image["new_revision_source_sha"] is None
    assert image["new_revision_request_id"] is None
    assert image["immutable_pre_identity_source_sha"] == app_jobs["offline-image-inventory-desk"]["source_sha"]
    assert image["current_review_head_sha"] != app_jobs["offline-image-inventory-desk"]["source_sha"]

    assert qa["review_head_sha"] == QA_HEAD
    assert qa["ci_run_id"] == 41400432166
    assert consumer["independent_qa_pr6_head"] == QA_HEAD
    assert consumer["source_sha"] == NEW_3D_SOURCE
    assert consumer["request_id"] == "3d-prism-route-3d-da6f7c129687"
    assert consumer["source_sha"] != sentinel["immutable_sentinel_source_sha"]
    assert consumer["source_sha"] != sentinel["historical_identity_source_sha"]
    assert consumer["identity_cas"] == "HOLD_NEW_REVISION"
    assert consumer["approved_version"] is False
    assert consumer["real_signed_msix"] is False
    assert consumer["backlog"] is False
    assert consumer["physical_gui"] is False
    assert sentinel["new_sentinel_cas_applied"] is False

    assert batch["cloud_preflight_discovered_count"] == 4
    assert batch["processed_count"] == 0
    assert batch["trigger_proof"] != "SCHEDULED_TRIGGER_PROVEN"
    assert gates["local_source_code_sync_physical_pass"] is False
    assert gates["local_source_code_sync_scheduler_pass"] is False
    for key in ("real_msix_pass", "real_gdk_msixvc_pass",
                "github_backlog_real_product_pass", "local_pull_pass",
                "checker_pass", "gui_qa_pass", "e2e_pass"):
        assert gates[key] is False
    assert data["e2e_pass"] is False


class LiveReviewLineageGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_live_evidence_is_consistent_and_hold(self):
        validate_live_review_evidence(self.ledger)

    def test_old_pr10_pin_cannot_be_reintroduced_as_current(self):
        data = copy.deepcopy(self.ledger)
        data["active_product"]["local_commands"][1] = data["active_product"]["historical_local_commands_20261102_1236"][1]
        with self.assertRaises(AssertionError):
            validate_live_review_evidence(data)

    def test_stubbed_staging_cannot_become_cas_pass(self):
        data = copy.deepcopy(self.ledger)
        data["active_product"]["provisioner_game_gdk_pr"]["new_lineage_contract"]["staging_dry_run_evidence"]["authenticated_cas"] = True
        with self.assertRaises(AssertionError):
            validate_live_review_evidence(data)

    def test_new_3d_revision_cannot_inherit_old_identity(self):
        data = copy.deepcopy(self.ledger)
        consumer = data["revision_review_reconciliation"]["observations"]["prism-route-3d-sentinel"]["new_consumer_revision"]
        consumer["source_sha"] = consumer["historical_identity_source_sha"]
        with self.assertRaises(AssertionError):
            validate_live_review_evidence(data)

    def test_image_review_cannot_promote_without_market_fit(self):
        data = copy.deepcopy(self.ledger)
        data["revision_review_reconciliation"]["observations"]["offline-image-inventory-desk"]["current_review_revision_promoted"] = True
        with self.assertRaises(AssertionError):
            validate_live_review_evidence(data)

    def test_cloud_success_cannot_be_reported_as_local_gui(self):
        data = copy.deepcopy(self.ledger)
        data["quality_gates"]["gui_qa_pass"] = True
        with self.assertRaises(AssertionError):
            validate_live_review_evidence(data)

    def test_batch_cloud_discovery_cannot_fake_physical_processing(self):
        data = copy.deepcopy(self.ledger)
        data["multi_product_partner_center_batch_4"]["processed_count"] = 4
        with self.assertRaises(AssertionError):
            validate_live_review_evidence(data)


if __name__ == "__main__":
    unittest.main()
