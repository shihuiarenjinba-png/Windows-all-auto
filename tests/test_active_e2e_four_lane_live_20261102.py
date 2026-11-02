"""Live four-lane ledger projection: cloud evidence cannot authorize physical or Store gates."""
import copy
import json
import unittest
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
GAME = "b53f89fc0b59871ba8f5cc7c62703bfdcc20d53a"
GAME_PRIOR = "d77cf88977db943d83cf898aae5bbf027e5aed90"
IMAGE = "9407225df68db3fb9c4e49b6d49db431c2c9094a"
PRISM = "9a73d0d56427b70fc0e0eba705a6be3e71c59390"
LEGACY_PRISM_SOURCE = "15fdcb52e46e35e6de8e87c55af99719c21e09b9"


def validate(data):
    active = data["active_product"]
    review = data["revision_review_reconciliation"]
    obs = review["observations"]
    current = review["current_four_lane_observation"]
    batch = data["multi_product_partner_center_batch_4"]
    post = {p["product"]: p for p in data["post_identity_pipeline"]["products"]}
    assert current["writer"] == "36_WINDOWS_E2E_ONLY"
    assert active["provisioner_head_observed"] == GAME
    assert active["provisioner_head_observation"]["previous_observed_head"] == GAME_PRIOR
    assert active["provisioner_game_gdk_pr"]["head_sha"] == GAME
    assert data["latest_provisioner_heads_observed"]["game"]["sha"] == GAME
    assert data["latest_provisioner_heads_observed"]["game"]["ci_run_id"] == 41412494345
    assert obs["signal-sprint"]["current_review_head_sha"] == GAME
    assert GAME in "\n".join(active["local_commands"])
    assert GAME_PRIOR not in "\n".join(active["local_commands"])
    assert GAME_PRIOR in "\n".join(active["historical_local_commands_20261102_1836"])
    assert "--apply" not in "\n".join(active["local_commands"])
    assert active["source_sha"] == "c058cbf7fe38e02d929c67d047d717ff74bd522e"
    assert current["game"]["new_lineage_artifact_id"] == 13105352227
    assert current["game"]["new_lineage_request_id"] != active["request_id"]
    assert active["original_exe_artifact_audit"]["ready_for_cas"] is False
    gui = obs["signal-sprint"]["hosted_windows_gui_evidence"]
    assert gui["window_bounds"] == [0, 0, 1040, 788]
    assert gui["work_area_bounds"] == [0, 0, 1024, 720]
    assert gui["status"] == "WINDOW_VISIBILITY_HOLD"
    assert gui["outside_workarea_area_px2"] > 0
    assert gui["user_pc"] is False and gui["human_qa"] is False
    assert current["game"]["cas"] is False and current["game"]["msixvc"] is False
    prism = obs["prism-route-3d-sentinel"]["latest_factory_pr17_observation"]
    assert prism["current_review_head_sha"] == PRISM
    assert prism["request_id"] == "3d-prism-route-3d-9a73d0d56427"
    assert prism["source_sha"] != LEGACY_PRISM_SOURCE
    assert prism["historical_identity_source_sha"] == LEGACY_PRISM_SOURCE
    assert prism["new_revision_cas_applied"] is False
    assert prism["approved_version"] is False and prism["real_signed_msix"] is False
    assert prism["physical_windows_gui"] is False
    assert current["three_d"]["legacy_identity_cas_is_new_revision"] is False
    image = obs["offline-image-inventory-desk"]
    assert image["current_review_head_sha"] == IMAGE
    assert image["immutable_pre_identity_source_sha"] != IMAGE
    assert image["current_review_revision_promoted"] is False
    assert image["new_revision_source_sha"] is None and image["new_revision_request_id"] is None
    assert image["score"] == 64 and image["independent_buyers_completed"] == 0
    assert image["market_fit_gate"] == "MARKET_FIT_HOLD"
    assert (batch["cloud_preflight_discovered_count"], batch["processed_count"]) == (4, 0)
    assert batch["trigger_proof"] != "SCHEDULED_TRIGGER_PROVEN"
    assert current["windows_e2e"]["batch_local_discovered"] == 0
    assert current["windows_e2e"]["next_index_is_cloud_logical"] is True
    for name in ("Focus Session Desk", "File Integrity Ledger"):
        assert post[name]["state"] == "POST_IDENTITY_READY"
        assert post[name]["identity_return_commit_sha"]
    for name in ("Offline Text Diff Desk", "Offline Image Inventory Desk"):
        assert post[name]["identity_return_commit_sha"] is None
    assert data["post_identity_pipeline"]["post_identity_ready_count"] == 3
    assert current["windows_e2e"]["archive_cloud_verified"] == 4
    assert data["local_source_code_sync"]["local_receipt_verified"] is False
    assert data["local_source_code_sync"]["local_task_scheduler_registered"] is False
    assert data["quality_gates"]["local_source_code_sync_physical_pass"] is False
    assert data["quality_gates"]["local_source_code_sync_scheduler_pass"] is False
    for gate in ("real_msix_pass", "real_gdk_msixvc_pass", "github_backlog_real_product_pass",
                 "local_pull_pass", "checker_pass", "gui_qa_pass", "e2e_pass"):
        assert data["quality_gates"][gate] is False
    assert data["e2e_pass"] is False
    assert data["sale_ready_windows_ux_gate"]["sale_ready"] is False


class FourLaneLiveEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_live_projection_is_fail_closed(self):
        validate(self.ledger)

    def test_reject_old_game_head_as_current(self):
        bad = copy.deepcopy(self.ledger)
        bad["active_product"]["provisioner_head_observed"] = GAME_PRIOR
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_reject_old_prism_identity_as_new_revision(self):
        bad = copy.deepcopy(self.ledger)
        bad["revision_review_reconciliation"]["observations"]["prism-route-3d-sentinel"]["latest_factory_pr17_observation"]["new_revision_cas_applied"] = True
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_reject_unverified_gui_pass(self):
        bad = copy.deepcopy(self.ledger)
        bad["revision_review_reconciliation"]["observations"]["signal-sprint"]["hosted_windows_gui_evidence"]["human_qa"] = True
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_reject_fake_local_scheduler_receipt(self):
        bad = copy.deepcopy(self.ledger)
        bad["local_source_code_sync"]["local_task_scheduler_registered"] = True
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_reject_image_market_promotion(self):
        bad = copy.deepcopy(self.ledger)
        bad["revision_review_reconciliation"]["observations"]["offline-image-inventory-desk"]["current_review_revision_promoted"] = True
        with self.assertRaises(AssertionError):
            validate(bad)

    def test_reject_batch_local_progress_from_cloud_cursor(self):
        bad = copy.deepcopy(self.ledger)
        bad["multi_product_partner_center_batch_4"]["processed_count"] = 2
        with self.assertRaises(AssertionError):
            validate(bad)


if __name__ == "__main__":
    unittest.main()
