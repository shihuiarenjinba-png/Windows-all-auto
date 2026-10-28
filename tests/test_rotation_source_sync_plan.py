"""Regression tests for read-only rotation -> local exact-source manifest bridge."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from scripts.rotation_source_sync_plan import (
    PlanHold, build_plan, write_manifest_once,
)
from scripts.rotation_pre_identity_intake import IntakeHold, IDENTITY_TARGET


def make_ledger(app_count=1, three_d=True, drift=True):
    ledger = {
        "e2e_pass": False,
        "new_product_allowed": False,
        "rotation_cohorts": {"app_jobs": [], "three_d_jobs": []},
        "user_id_requests": {"items": []},
    }
    for index in range(app_count):
        slug = f"cohort-app-{index}"
        sha = f"{index + 1:040x}"
        rid = f"app-cohort-{index}-{sha[:12]}"
        branch = f"codex/cohort-app-{index}"
        job = {
            "status": "PRE_IDENTITY_READY", "product_type": "APP",
            "request_id": rid, "slug": slug,
            "source_repository": "shihuiarenjinba-png/AI-App-Factory",
            "source_branch": branch, "source_sha": sha,
            "factory_build_head": sha,
            "expected_exe_sha256": f"{index + 1:064x}",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
        }
        ledger["rotation_cohorts"]["app_jobs"].append(job)
        ledger["user_id_requests"]["items"].append({
            "request_id": rid, "slug": slug,
            "repo": job["source_repository"],
            "source_branch": branch, "source_sha": sha,
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "identity_target": IDENTITY_TARGET,
            "identity_return_target": f"products/{slug}/store/approved-identity.json",
            "status": "WAITING_USER_IDENTITY",
        })
    if three_d:
        slug = "prism-route-3d"
        sha = "a" * 40
        rid = "3d-prism-route-3d-aaaaaaaaaaaa"
        branch = "codex/3d-prism-route"
        ledger["rotation_cohorts"]["three_d_jobs"].append({
            "status": "PRE_IDENTITY_READY", "product_type": "GAME_3D",
            "request_id": rid, "slug": slug,
            "source_repository": "shihuiarenjinba-png/3d-game-factory",
            "source_branch": branch, "source_sha": sha,
            "factory_build_head": sha,
            "expected_exe_sha256": "b" * 64,
            "registration_type": "MSIX_OR_PWA_GAME",
            "partner_center_selection": "MSIX or PWA game",
            "packaging_strategy": "GODOT_WINDOWS_EXE_PCK_MAKEAPPX_MSIX",
            "packaging_family": "MSIX",
            "observed_pr_head": ("c" * 40 if drift else sha),
        })
        ledger["user_id_requests"]["items"].append({
            "request_id": rid, "slug": slug,
            "repo": "shihuiarenjinba-png/3d-game-factory",
            "source_branch": branch, "source_sha": sha,
            "registration_type": "MSIX_OR_PWA_GAME",
            "partner_center_selection": "MSIX or PWA game",
            "identity_target": IDENTITY_TARGET,
            "identity_return_target": f"products/{slug}/store/approved-identity.json",
            "status": "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE",
            "allow_local_product_creation": False,
        })
    return ledger


class RotationSourceSyncPlanTests(unittest.TestCase):
    def test_five_app_jobs_and_prism_drift_do_not_block_each_other(self):
        plan = build_plan(make_ledger(app_count=5))
        self.assertEqual(len(plan["sync_manifest"]["jobs"]), 5)
        self.assertEqual(len(plan["holds"]), 1)
        self.assertEqual(plan["holds"][0]["status"], "HOLD_SOURCE_BRANCH_HEAD_DRIFT")
        self.assertEqual(len({j["request_id"] for j in plan["sync_manifest"]["jobs"]}), 5)
        self.assertFalse(plan["physical_local_sync_pass"])
        self.assertFalse(plan["github_queue_origin_verified"])

    def test_matching_three_d_source_can_be_rechecked_by_worker(self):
        plan = build_plan(make_ledger(app_count=0, drift=False))
        self.assertEqual(len(plan["sync_manifest"]["jobs"]), 1)
        self.assertEqual(plan["holds"], [])
        self.assertFalse(plan["remote_head_verified"])

    def test_only_drifted_prism_has_no_executable_manifest(self):
        plan = build_plan(make_ledger(app_count=0, drift=True))
        self.assertEqual(plan["sync_manifest"]["jobs"], [])
        self.assertEqual(plan["metrics"]["source_head_drift_holds"], 1)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(PlanHold, "NO_ELIGIBLE_JOBS"):
                write_manifest_once(Path(temp) / "targets.json", plan)

    def test_duplicate_request_across_lanes_fails_closed(self):
        ledger = make_ledger()
        ledger["rotation_cohorts"]["three_d_jobs"][0]["request_id"] = (
            ledger["rotation_cohorts"]["app_jobs"][0]["request_id"])
        with self.assertRaises(IntakeHold):
            build_plan(ledger)

    def test_cross_product_identity_return_target_fails_closed(self):
        ledger = make_ledger()
        ledger["user_id_requests"]["items"][0]["identity_return_target"] = (
            "products/prism-route-3d/store/approved-identity.json")
        with self.assertRaises(IntakeHold):
            build_plan(ledger)

    def test_registration_family_conflict_fails_closed(self):
        ledger = make_ledger()
        ledger["rotation_cohorts"]["app_jobs"][0]["registration_type"] = "GDK_GAME"
        ledger["rotation_cohorts"]["app_jobs"][0]["partner_center_selection"] = "GDK game"
        ledger["user_id_requests"]["items"][0]["registration_type"] = "GDK_GAME"
        ledger["user_id_requests"]["items"][0]["partner_center_selection"] = "GDK game"
        with self.assertRaises(IntakeHold):
            build_plan(ledger)

    def test_manifest_is_idempotent_but_never_overwritten_with_different_jobs(self):
        plan = build_plan(make_ledger(1, False))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "targets.json"
            self.assertEqual(write_manifest_once(path, plan), "CREATED_NEW_MANIFEST")
            original = path.read_bytes()
            self.assertEqual(write_manifest_once(path, plan), "REUSED_IDENTICAL_MANIFEST")
            changed = copy.deepcopy(plan)
            changed["sync_manifest"]["jobs"][0]["source_sha"] = "f" * 40
            with self.assertRaisesRegex(PlanHold, "MANIFEST_CONFLICT"):
                write_manifest_once(path, changed)
            self.assertEqual(path.read_bytes(), original)

    def test_manifest_refuses_symlink_destination(self):
        plan = build_plan(make_ledger(1, False))
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "original.json"
            target.write_text("sentinel", encoding="utf-8")
            link = Path(temp) / "linked.json"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlink privilege unavailable")
            with self.assertRaisesRegex(PlanHold, "UNSAFE"):
                write_manifest_once(link, plan)
            self.assertEqual(target.read_text(encoding="utf-8"), "sentinel")


if __name__ == "__main__":
    unittest.main()
