from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
HEX40 = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class GroupBConveyorCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.registry = json.loads(
            (ROOT / "ops" / "group_b_standard_store_products.json").read_text(
                encoding="utf-8"
            )
        )
        self.checkpoint = json.loads(
            (ROOT / "ops" / "group_b_conveyor_checkpoint_20261117.json").read_text(
                encoding="utf-8"
            )
        )

    def test_snapshot_never_authorizes_store_write_or_merge(self):
        self.assertEqual(
            self.checkpoint["schema_version"], "group-b-conveyor-checkpoint/1"
        )
        self.assertEqual(self.checkpoint["authority"], "evidence_snapshot_only")
        self.assertFalse(self.checkpoint["store_write_authorized"])
        self.assertFalse(self.checkpoint["main_release_merge_authorized"])
        self.assertFalse(
            self.checkpoint["central"]["partner_center_write_performed"]
        )

    def test_folder_snapshot_preserves_frozen_pilot_and_reconcile_hold(self):
        folder = self.checkpoint["products"]["folder-engine"]
        self.assertEqual(
            folder["conveyor_state"], "HOLD_SUBMISSION_RECONCILE_REQUIRED"
        )
        self.assertFalse(folder["direct_product_artifact_pull_supported"])
        self.assertTrue(HEX40.fullmatch(folder["frozen_source_sha"]))
        self.assertEqual(len(folder["frozen_msix_sha256"]), 64)
        self.assertEqual(len(folder["frozen_exe_sha256"]), 64)

    def test_scheduled_checkpoint_is_static_pass_gui_pending(self):
        scheduled = self.checkpoint["products"]["scheduled-api-runner"]
        self.assertEqual(
            scheduled["conveyor_state"],
            "PASS_STATIC_ONLY_GUI_PENDING",
        )
        local = scheduled["local_confirmation"]
        self.assertEqual(local["status"], "PASS_STATIC_ONLY_GUI_PENDING")
        self.assertTrue(local["artifact_receipt_verified"])
        self.assertTrue(local["evidence_rerun_refused_and_hashes_unchanged"])
        self.assertEqual(local["makeappx_unpack"], "PASS")
        self.assertEqual(
            local["manifest_identity_publisher_version_architecture"],
            "PASS",
        )
        self.assertEqual(local["unpacked_exe_hash"], "PASS")
        self.assertEqual(local["defender_exact_msix"], "NO_THREATS")
        self.assertEqual(local["defender_exact_exe"], "NO_THREATS")
        self.assertEqual(local["authenticode_msix"], "NotSigned")
        self.assertEqual(local["authenticode_exe"], "NotSigned")
        self.assertTrue(local["github_ci_primary"])
        self.assertFalse(local["local_full_suite_run"])
        self.assertEqual(local["qa_template_status"], "HOLD")
        self.assertFalse(local["gui_launch_attempted"])
        self.assertTrue(local["action_time_confirmation_required"])
        self.assertEqual(
            local["next_action"],
            "ONE_SHOT_NORMAL_USER_EXE_LAUNCH",
        )

    def test_direct_product_snapshot_matches_registry_routes(self):
        products = self.checkpoint["products"]
        registry = self.registry["products"]
        for product_id in (
            "scheduled-api-runner",
            "workflow-automation-hub",
            "browser-automation-runner",
        ):
            with self.subTest(product_id=product_id):
                snap = products[product_id]
                reg = registry[product_id]
                self.assertEqual(
                    snap["repository_full_name"], reg["repository_full_name"]
                )
                self.assertEqual(
                    snap["store_workflow_name"], reg["workflow_name"]
                )
                self.assertEqual(
                    snap["store_artifact"]["name"], reg["artifact_name"]
                )
                self.assertTrue(HEX40.fullmatch(snap["head_sha"]))
                self.assertGreater(snap["store_run_id"], 0)
                self.assertGreater(snap["store_artifact"]["id"], 0)
                self.assertTrue(
                    DIGEST.fullmatch(snap["store_artifact"]["digest"])
                )
                self.assertFalse(snap["store_artifact"]["expired"])
                self.assertEqual(snap["ci_conclusion"], "success")


if __name__ == "__main__":
    unittest.main()
