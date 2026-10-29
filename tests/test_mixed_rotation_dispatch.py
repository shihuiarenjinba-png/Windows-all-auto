"""Mixed APP queue planning tests; no Partner Center, CAS or local IO."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from scripts import mixed_rotation_dispatch as planner
from scripts import run_local_partner_center_batch as runner


def fixture(post_count=1):
    jobs, batch, proofs = [], [], []
    for index, slug in enumerate(planner.ORDER, 1):
        sha = str(index) * 40
        request = f"app-{slug}-{sha[:12]}"
        post = index <= post_count
        job = {
            "product_type": "APP", "slug": slug,
            "request_id": request,
            "source_repository": "shihuiarenjinba-png/AI-App-Factory",
            "source_branch": f"codex/{slug}", "source_sha": sha,
            "identity_return_target": f"products/{slug}/store/approved-identity.json",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "status": "POST_IDENTITY_READY" if post else "PRE_IDENTITY_READY",
        }
        proof = {"batch_index": index, "slug": slug, "request_id": request}
        if post:
            job.update({
                "identity_return_commit_sha": "a" * 39 + str(index),
                "identity_store_id": f"9P123456789{index}",
                "package_version_gate": "HOLD",
            })
            proof.update({
                "status": "POST_IDENTITY_GITHUB_VERIFIED",
                "return_commit_sha": job["identity_return_commit_sha"],
                "store_id": job["identity_store_id"],
                "next_gate": "PACKAGE_VERSION_HOLD",
            })
        else:
            proof.update({
                "status": "PRE_IDENTITY_GITHUB_VERIFIED",
                "source_sha": sha, "next_gate": "LOCAL_OPERATOR_REQUIRED",
            })
        jobs.append(job)
        batch.append({
            "batch_index": index, "slug": slug, "request_id": request,
            "source_repository": job["source_repository"],
            "source_branch": job["source_branch"], "source_sha": sha,
        })
        proofs.append(proof)
    ledger = {
        "rotation_cohorts": {"app_jobs": jobs, "three_d_jobs": [], "game_jobs": []},
        "multi_product_partner_center_batch_4": {"products": batch},
    }
    audit = {
        "status": "MIXED_ROTATION_AUDITED", "discovered_count": 4,
        "post_identity_github_verified": post_count,
        "pre_identity_github_verified": 4 - post_count,
        "local_windows_no_llm_pass": False,
        "local_partner_center_operator_pass": False,
        "local_batch_runner_ready": False,
        "store_submission": "NOT_PERFORMED",
        "cas": "NOT_PERFORMED",
        "products": proofs,
    }
    return ledger, audit


class MixedPlanTests(unittest.TestCase):
    def test_one_post_three_pre_skips_only_verified_return(self):
        ledger, audit = fixture()
        before = deepcopy(ledger)
        plan = planner.build_dispatch_plan(ledger, audit)
        self.assertEqual(ledger, before)
        self.assertEqual(plan["post_identity_skip_count"], 1)
        self.assertEqual(plan["pre_identity_pending_count"], 3)
        self.assertEqual(
            plan["products"][0]["dispatch_action"], "SKIP_IDENTITY_ALREADY_RETURNED")
        self.assertEqual(
            plan["products"][1]["dispatch_action"],
            "LOCAL_OPERATOR_PENDING_REVIEWED_MIXED_RUNNER")
        self.assertFalse(plan["task_scheduler_registration_allowed"])
        self.assertFalse(plan["mixed_state_local_runner_ready"])
        self.assertFalse(plan["multi_product_identity_batch_pass"])
        self.assertEqual(plan["store_submission"], "NOT_PERFORMED")

    def test_four_post_is_no_work_but_not_local_pass(self):
        ledger, audit = fixture(4)
        plan = planner.build_dispatch_plan(ledger, audit)
        self.assertTrue(plan["no_identity_work_in_github_queue"])
        self.assertEqual(plan["post_identity_skip_count"], 4)
        self.assertFalse(plan["local_windows_no_llm_pass"])
        self.assertFalse(plan["task_scheduler_registration_allowed"])

    def test_missing_independent_audit_fails_closed(self):
        ledger, audit = fixture()
        audit["local_batch_runner_ready"] = True
        with self.assertRaisesRegex(planner.PlanHold, "AUDIT_NOT_INDEPENDENT"):
            planner.build_dispatch_plan(ledger, audit)

    def test_post_identity_return_commit_drift_holds(self):
        ledger, audit = fixture()
        audit["products"][0]["return_commit_sha"] = "b" * 40
        with self.assertRaisesRegex(planner.PlanHold, "POST_CONFLICT"):
            planner.build_dispatch_plan(ledger, audit)

    def test_pre_job_marked_as_post_in_evidence_holds(self):
        ledger, audit = fixture()
        audit["products"][1]["status"] = "POST_IDENTITY_GITHUB_VERIFIED"
        with self.assertRaisesRegex(planner.PlanHold, "PRE_CONFLICT"):
            planner.build_dispatch_plan(ledger, audit)

    def test_cross_lane_request_collision_holds(self):
        ledger, audit = fixture()
        ledger["rotation_cohorts"]["three_d_jobs"] = [{
            "product_type": "GAME_3D", "slug": "prism-route-3d",
            "request_id": ledger["rotation_cohorts"]["app_jobs"][0]["request_id"],
            "identity_return_target": "products/prism-route-3d/store/approved-identity.json",
        }]
        with self.assertRaisesRegex(planner.PlanHold, "CROSS_PRODUCT"):
            planner.build_dispatch_plan(ledger, audit)

    def test_duplicate_post_store_id_holds(self):
        ledger, audit = fixture(2)
        ledger["rotation_cohorts"]["app_jobs"][1]["identity_store_id"] = (
            ledger["rotation_cohorts"]["app_jobs"][0]["identity_store_id"])
        audit["products"][1]["store_id"] = audit["products"][0]["store_id"]
        with self.assertRaisesRegex(planner.PlanHold, "IDENTITY_COLLISION"):
            planner.build_dispatch_plan(ledger, audit)

    def test_malformed_batch_entry_fails_with_hold(self):
        ledger, audit = fixture()
        ledger["multi_product_partner_center_batch_4"]["products"][2] = None
        with self.assertRaisesRegex(planner.PlanHold, "PLAN_SCHEMA"):
            planner.build_dispatch_plan(ledger, audit)

    def test_batch_binding_tamper_holds(self):
        ledger, audit = fixture()
        ledger["multi_product_partner_center_batch_4"]["products"][2]["source_sha"] = "f" * 40
        with self.assertRaisesRegex(planner.PlanHold, "BATCH_BINDING"):
            planner.build_dispatch_plan(ledger, audit)

    def test_read_only_cli_creates_no_state_and_never_uses_browser(self):
        ledger, audit = fixture()
        with TemporaryDirectory() as directory:
            state = Path(directory) / "must-not-exist"
            with (
                patch.object(runner, "fetch_central",
                             return_value=(ledger, "c" * 40, "blob")),
                patch.object(runner, "audit_queue_only",
                             return_value={**audit, "central_head_sha": "c" * 40}),
                patch.object(runner, "recheck_central"),
                patch.object(runner, "PartnerCenterDriver") as browser,
                patch.object(runner, "import_provisioner") as provisioner,
                patch.object(runner, "sync_sources") as sync,
            ):
                code = runner.main(["--plan-queue", "--state-dir", str(state)])
            self.assertEqual(code, 0)
            self.assertFalse(state.exists())
            browser.assert_not_called()
            provisioner.assert_not_called()
            sync.assert_not_called()

    def test_read_only_plan_hold_creates_no_state(self):
        with TemporaryDirectory() as directory:
            state = Path(directory) / "must-not-exist"
            with patch.object(runner, "plan_queue_only",
                              side_effect=planner.PlanHold("HOLD_MIXED_PLAN_SCHEMA")):
                code = runner.main(["--plan-queue", "--state-dir", str(state)])
            self.assertEqual(code, 2)
            self.assertFalse(state.exists())


class MixedLocalPreflightTests(unittest.TestCase):
    """Preflight is real local IO, but never browser/CAS/Store work."""

    @staticmethod
    def prepared(post_count=1):
        ledger, audit = fixture(post_count)
        for index, job in enumerate(ledger["rotation_cohorts"]["app_jobs"], 1):
            if job["status"] != "PRE_IDENTITY_READY":
                continue
            job.update({
                "factory_artifact_id": 12340 + index,
                "factory_artifact_name": f"artifact-{index}",
                "factory_artifact_zip_sha256": str(index) * 64,
                "factory_build_head": job["source_sha"],
                "factory_artifact_expiry_utc": "2099-01-01T00:00:00Z",
                "artifact_metadata_verified": True,
            })
        return ledger, audit

    def test_mixed_preflight_skips_post_and_verifies_three_exact_pre(self):
        ledger, audit = self.prepared()
        jobs = ledger["rotation_cohorts"]["app_jobs"]
        central = "c" * 40
        with TemporaryDirectory() as directory:
            args = SimpleNamespace(
                state_dir=Path(directory), provisioner_root=Path(directory))
            def head(_repo, branch):
                return next(j["source_sha"] for j in jobs
                            if j["source_branch"] == branch)
            def artifact(endpoint):
                j = next(j for j in jobs if
                         endpoint.endswith("/" + str(j.get("factory_artifact_id"))))
                return {
                    "expired": False, "name": j["factory_artifact_name"],
                    "expires_at": j["factory_artifact_expiry_utc"],
                    "digest": "sha256:" + j["factory_artifact_zip_sha256"],
                }
            def prepared(_ledger, _receipt, _root, slug, **_kwargs):
                j = next(j for j in jobs if j["slug"] == slug)
                return {
                    "request_id": j["request_id"],
                    "source_snapshot_head": j["source_sha"],
                    "source_snapshot_status": "REUSED_EXACT_SNAPSHOT",
                    "queue_job_digest": runner.operator.canonical_digest(j),
                }
            def verified(job, _root):
                return {
                    "artifact_id": job["factory_artifact_id"],
                    "exe_sha256": "a" * 64, "exe_bytes": 123,
                }
            with (
                patch.object(runner, "check_prerequisites",
                             return_value={"provisioner_head": "p" * 40}),
                patch.object(runner, "fetch_central",
                             return_value=(ledger, central, "blob")),
                patch.object(runner, "audit_queue_only", return_value=audit),
                patch.object(runner, "live_branch_head", side_effect=head),
                patch.object(runner, "gh_json", side_effect=artifact),
                patch.object(runner, "sync_sources",
                             return_value={"status": "PASS",
                                           "exact_sha_verified": True}) as sync,
                patch.object(runner.operator, "prepare",
                             side_effect=prepared) as prepare,
                patch.object(runner, "verify_artifact",
                             side_effect=verified) as verify,
                patch.object(runner, "recheck_central"),
                patch.object(runner, "PartnerCenterDriver") as browser,
                patch.object(runner, "import_provisioner") as cas,
            ):
                result = runner.preflight_mixed_local(args)
            self.assertEqual(result["status"], "MIXED_LOCAL_PRECHECK_PASS")
            self.assertEqual(result["post_identity_skip_count"], 1)
            self.assertEqual(result["pre_identity_preflight_count"], 3)
            self.assertEqual([p["slug"] for p in result["products"]],
                             list(planner.ORDER[1:]))
            self.assertFalse(result["task_scheduler_registration_allowed"])
            self.assertFalse(result["local_windows_no_llm_pass"])
            self.assertEqual(result["cas"], "NOT_PERFORMED")
            self.assertEqual(sync.call_args.args[0], jobs[1:])
            self.assertEqual(prepare.call_count, 3)
            self.assertEqual(verify.call_count, 3)
            browser.assert_not_called()
            cas.assert_not_called()

    def test_all_post_does_not_touch_sources_or_browser(self):
        ledger, audit = self.prepared(4)
        with TemporaryDirectory() as directory:
            args = SimpleNamespace(
                state_dir=Path(directory), provisioner_root=Path(directory))
            with (
                patch.object(runner, "check_prerequisites", return_value={}),
                patch.object(runner, "fetch_central",
                             return_value=(ledger, "c" * 40, "blob")),
                patch.object(runner, "audit_queue_only", return_value=audit),
                patch.object(runner, "recheck_central"),
                patch.object(runner, "sync_sources") as sync,
                patch.object(runner, "verify_artifact") as artifact,
                patch.object(runner, "PartnerCenterDriver") as browser,
            ):
                result = runner.preflight_mixed_local(args)
            self.assertEqual(result["status"], "MIXED_LOCAL_NO_IDENTITY_WORK")
            self.assertFalse(result["task_scheduler_registration_allowed"])
            sync.assert_not_called()
            artifact.assert_not_called()
            browser.assert_not_called()

    def test_artifact_digest_mismatch_holds_before_local_download(self):
        ledger, audit = self.prepared()
        with TemporaryDirectory() as directory:
            args = SimpleNamespace(
                state_dir=Path(directory), provisioner_root=Path(directory))
            with (
                patch.object(runner, "check_prerequisites", return_value={}),
                patch.object(runner, "fetch_central",
                             return_value=(ledger, "c" * 40, "blob")),
                patch.object(runner, "audit_queue_only", return_value=audit),
                patch.object(runner, "live_branch_head",
                             side_effect=lambda repo, branch: next(
                                 j["source_sha"] for j in
                                 ledger["rotation_cohorts"]["app_jobs"]
                                 if j["source_branch"] == branch)),
                patch.object(runner, "gh_json",
                             return_value={"expired": False, "name": "wrong",
                                           "digest": "sha256:" + "0" * 64}),
                patch.object(runner, "recheck_central"),
                patch.object(runner, "sync_sources") as sync,
                patch.object(runner, "PartnerCenterDriver") as browser,
            ):
                with self.assertRaisesRegex(
                        runner.RunnerHold, "HOLD_ARTIFACT_MISMATCH"):
                    runner.preflight_mixed_local(args)
            sync.assert_not_called()
            browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
