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

    def test_folder_snapshot_binds_polished_candidate_and_remaining_holds(self):
        folder = self.checkpoint["products"]["folder-engine"]
        self.assertEqual(
            folder["conveyor_state"],
            "HOLD_OWNER_VISUAL_APPROVAL_PRICE_AUDIENCE_SECURITY_VERSION_REVERIFY",
        )
        self.assertFalse(folder["direct_product_artifact_pull_supported"])
        self.assertEqual(
            folder["frozen_source_sha"],
            "adfc0d08efb0a94602d5286557d399f9cb28b9dd",
        )
        self.assertEqual(
            folder["frozen_msix_sha256"],
            "3c6bc8c1291450905ae71834f2704a59325d1aaa1c9de3f064bcb8c7ebca9fb9",
        )
        self.assertEqual(
            folder["frozen_exe_sha256"],
            "de6894ae39cbe0fbe1889b4aa005e500f30a2ef95ee67403ddfb210dbcfb9f18",
        )
        self.assertEqual(folder["ci"]["conclusion"], "success")
        self.assertEqual(folder["package"]["makeappx_pack_unpack"], "PASS")
        self.assertEqual(folder["screenshots"]["ja_count"], 5)
        self.assertEqual(folder["screenshots"]["en_count"], 5)
        self.assertEqual(folder["screenshots"]["resolution"], "1366x768")
        self.assertTrue(folder["screenshots"]["native_pixels"])
        self.assertFalse(folder["screenshots"]["resized"])
        self.assertEqual(folder["screenshots"]["internal_visual_qa"], "PASS")
        self.assertFalse(folder["screenshots"]["owner_visual_approval"])
        self.assertTrue(folder["superseded_candidate"]["upload_forbidden"])
        self.assertFalse(folder["start_submission_repeated"])
        self.assertFalse(folder["package_uploaded"])
        self.assertFalse(folder["certification_submitted"])
        self.assertFalse(folder["published"])

    def test_scheduled_checkpoint_records_private_signing_lane_ready(self):
        scheduled = self.checkpoint["products"]["scheduled-api-runner"]
        self.assertEqual(
            scheduled["conveyor_state"],
            "PRIVATE_STORE_SIGNING_LANE_READY",
        )
        local = scheduled["local_confirmation"]
        self.assertEqual(
            local["status"],
            "PRIVATE_STORE_SIGNING_LANE_READY",
        )
        self.assertTrue(local["artifact_receipt_verified"])
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
        self.assertTrue(local["launch_action_time_approved"])
        self.assertEqual(local["launch_attempts"], 1)
        self.assertTrue(local["normal_user_context"])
        self.assertFalse(local["process_started"])
        self.assertIsNone(local["exit_code"])
        self.assertFalse(local["normal_exit"])
        self.assertEqual(local["original_wrapper_status"], "LAUNCH_FAILED")
        self.assertEqual(
            local["reconciled_classification"],
            "APPLICATION_CONTROL_BLOCKED",
        )
        self.assertEqual(
            local["code_integrity_blocking_event_ids"],
            [3033, 3077],
        )
        self.assertEqual(
            local["policy_guid"],
            "{0283ac0f-fff1-49ae-ada1-8a933130cad6}",
        )
        self.assertFalse(local["security_bypass_used"])
        self.assertFalse(local["package_installed"])
        self.assertFalse(local["store_write_performed"])
        self.assertTrue(local["unsigned_launch_retries_forbidden"])
        self.assertEqual(local["jp_en_gui"], "NOT_TESTED")
        self.assertEqual(local["dpi_matrix"], "NOT_TESTED")
        self.assertEqual(local["https_get"], "NOT_TESTED")
        self.assertEqual(local["task_scheduler_lifecycle"], "NOT_TESTED")
        self.assertTrue(local["atomic_finalizer_reported_complete"])
        self.assertEqual(
            local["atomic_finalizer_report_source"],
            "code_owner_local_report_20261118",
        )
        self.assertTrue(local["pre_store_static_pass"])
        self.assertTrue(local["private_store_signing_lane_ready"])
        self.assertFalse(local["local_final_pass"])
        self.assertFalse(local["store_signed_install_pass"])
        self.assertEqual(
            local["next_action"],
            "STORE_OWNER_CONFIRM_ZERO_COST_PRIVATE_ACQUISITION",
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
