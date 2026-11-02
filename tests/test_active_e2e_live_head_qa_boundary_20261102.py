"""Fail-closed evidence-boundary regression for 2026-11-02 live head reconciliation."""
import copy
import json
from pathlib import Path
import unittest

LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
GAME = "b53f89fc0b59871ba8f5cc7c62703bfdcc20d53a"
GAME_PRIOR = "d77cf88977db943d83cf898aae5bbf027e5aed90"
QA = "8aa8c20e1db0f2c30b91dd4e27cc141b1448d7d7"
QA_PRIOR = "5438bb11516b8af8d9e68226ab2f82303b30391c"
IMAGE = "9407225df68db3fb9c4e49b6d49db431c2c9094a"
IMAGE_PRIOR = "de514cd29d2c930ec7dcff1263070cc6bf83b2c0"
SOURCE_GAME = "c058cbf7fe38e02d929c67d047d717ff74bd522e"
SOURCE_IMAGE = "16b6a772952ca0988f2ae2f8b5f4db2e59ec5877"


def validate_current_evidence(data):
    review = data["revision_review_reconciliation"]
    snap = review["live_head_ci_qa_reconciliation_20261102"]
    obs = review["observations"]
    active = data["active_product"]
    assert snap["writer"] == "36_WINDOWS_E2E_ONLY"
    assert active["source_sha"] == SOURCE_GAME
    assert active["provisioner_head_observed"] == GAME
    assert active["provisioner_game_gdk_pr"]["head_sha"] == GAME
    assert active["local_identity_return_worker"]["required_provisioner_sha"] == GAME
    assert data["latest_provisioner_heads_observed"]["game"]["sha"] == GAME
    assert obs["signal-sprint"]["current_review_head_sha"] == GAME
    assert obs["signal-sprint"]["previous_review_head_sha"] == GAME_PRIOR
    assert snap["observations"]["game_provisioner_pr10"]["ci_run_id"] == 41412494345
    assert snap["observations"]["game_provisioner_pr10"]["ahead"] == 4
    assert not snap["observations"]["game_provisioner_pr10"]["cas"]
    assert not snap["observations"]["game_provisioner_pr10"]["gdk_msixvc"]
    assert "HOLD" in obs["signal-sprint"]["hosted_windows_gui_evidence"]["status"]
    assert obs["signal-sprint"]["hosted_windows_gui_evidence"]["user_pc"] is False
    assert obs["signal-sprint"]["hosted_windows_gui_evidence"]["human_qa"] is False
    assert "1024x768_TASKBAR_OCCLUDES_BOTTOM_WINDOW" in obs["signal-sprint"]["hosted_windows_gui_evidence"]["consumer_defects"]
    assert "JP_TOGGLE_BUT_GAME_STATUS_REMAINS_ENGLISH" in obs["signal-sprint"]["hosted_windows_gui_evidence"]["consumer_defects"]
    assert QA == obs["prism-route-3d-sentinel"]["independent_3d_qa_pr6"]["review_head_sha"]
    assert QA == obs["prism-route-3d-sentinel"]["new_consumer_revision"]["independent_qa_pr6_head"]
    assert QA_PRIOR == obs["prism-route-3d-sentinel"]["independent_3d_qa_pr6"]["previous_head_sha"]
    assert "HOLD_MISSING_JAPANESE_GLYPHS" in obs["prism-route-3d-sentinel"]["independent_3d_qa_pr6"]["japanese_visual_quality"]
    assert obs["prism-route-3d-sentinel"]["independent_3d_qa_pr6"]["real_pck_software_runtime"]["physical_windows"] is False
    assert obs["prism-route-3d-sentinel"]["new_consumer_revision"]["identity_cas"] == "HOLD_NEW_REVISION"
    image = obs["offline-image-inventory-desk"]
    assert image["current_review_head_sha"] == IMAGE
    assert image["previous_review_head_sha"] == IMAGE_PRIOR
    assert image["immutable_pre_identity_source_sha"] == SOURCE_IMAGE
    assert image["current_review_head_sha"] != SOURCE_IMAGE
    assert image["current_review_revision_promoted"] is False
    assert image["new_revision_source_sha"] is None
    assert image["new_revision_request_id"] is None
    assert image["score"] == 64 and image["independent_buyers_completed"] == 0
    assert image["market_fit_gate"] == "MARKET_FIT_HOLD"
    batch = snap["batch4"]
    assert (batch["cloud_discovered"], batch["github_identity_returns"], batch["physical_processed"], batch["physical_discovered"]) == (4, 2, 0, 0)
    assert batch["cloud_next_index"] == 3 and batch["local_scheduler_proven"] is False
    assert batch["archive_zip_sha_crc_preserved"] == 4
    assert snap["local_code_sync"]["cloud_pass"] is True
    assert snap["local_code_sync"]["user_pc_exact_3_sha_verified"] is False
    assert snap["local_code_sync"]["task_scheduler_receipt_verified"] is False
    assert data["local_source_code_sync"]["local_receipt_verified"] is False
    assert data["local_source_code_sync"]["local_task_scheduler_registered"] is False
    assert data["quality_gates"]["local_source_code_sync_physical_pass"] is False
    assert data["quality_gates"]["local_source_code_sync_scheduler_pass"] is False
    assert data["quality_gates"]["real_msix_pass"] is False
    assert data["quality_gates"]["real_gdk_msixvc_pass"] is False
    assert data["quality_gates"]["gui_qa_pass"] is False
    assert data["e2e_pass"] is False
    assert data["sale_ready_windows_ux_gate"]["sale_ready"] is False
    assert data["sale_ready_windows_ux_gate"]["verdict"] == "NO"
    post = {p["product"]: p for p in data["post_identity_pipeline"]["products"]}
    for name in ("Focus Session Desk", "File Integrity Ledger"):
        assert post[name]["state"] == "POST_IDENTITY_READY"
        assert post[name]["identity_return_commit_sha"]
    for name in ("Offline Text Diff Desk", "Offline Image Inventory Desk"):
        assert post[name]["identity_return_commit_sha"] is None
    assert not active["cas_returned"]
    assert active["original_exe_artifact_audit"]["ready_for_cas"] is False
    assert "e69e9b9b96f10426b9a9e3eb7d540a85d49778d6" in "\n".join(active["historical_local_commands_20261102_1636"])
    assert GAME_PRIOR not in "\n".join(active["local_commands"])
    assert GAME in "\n".join(active["local_commands"])
    assert "--apply-request-id" not in "\n".join(active["local_commands"])


class LiveHeadQABoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))

    def test_current_projection_and_historical_commands(self):
        validate_current_evidence(self.data)

    def test_reject_false_local_receipt_promotion(self):
        bad = copy.deepcopy(self.data)
        bad["local_source_code_sync"]["local_receipt_verified"] = True
        with self.assertRaises(AssertionError):
            validate_current_evidence(bad)

    def test_reject_wrong_game_review_head(self):
        bad = copy.deepcopy(self.data)
        bad["revision_review_reconciliation"]["observations"]["signal-sprint"]["current_review_head_sha"] = GAME_PRIOR
        with self.assertRaises(AssertionError):
            validate_current_evidence(bad)

    def test_reject_image_review_promotion_without_buyers(self):
        bad = copy.deepcopy(self.data)
        bad["revision_review_reconciliation"]["observations"]["offline-image-inventory-desk"]["current_review_revision_promoted"] = True
        with self.assertRaises(AssertionError):
            validate_current_evidence(bad)

    def test_reject_new_prism_cas_inferred_from_software_render(self):
        bad = copy.deepcopy(self.data)
        bad["revision_review_reconciliation"]["observations"]["prism-route-3d-sentinel"]["new_consumer_revision"]["identity_cas"] = "CAS_RETURN_PASS"
        with self.assertRaises(AssertionError):
            validate_current_evidence(bad)

    def test_reject_hosted_screenshot_as_human_qa(self):
        bad = copy.deepcopy(self.data)
        bad["revision_review_reconciliation"]["observations"]["signal-sprint"]["hosted_windows_gui_evidence"]["human_qa"] = True
        with self.assertRaises(AssertionError):
            validate_current_evidence(bad)


if __name__ == "__main__":
    unittest.main()
