"""Offline tests for locked mixed PRE/POST host-state preparation.

No browser, Partner Center, CAS, Task Scheduler or Store operations.
"""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import json

from scripts import run_local_partner_center_batch as host
from scripts import mixed_batch_resume as resume
from scripts import mixed_resume_rebase as rebase


HEAD = "a" * 40
SOURCE = ("1" * 40, "2" * 40, "3" * 40, "4" * 40)


def fixtures(post=1):
    jobs, products, proof = [], [], []
    for i, slug in enumerate(resume.EXPECTED_ORDER):
        job = {
            "slug": slug,
            "request_id": "app-" + slug + "-" + SOURCE[i][:12],
            "source_repository": "shihuiarenjinba-png/AI-App-Factory",
            "source_branch": "codex/" + slug,
            "source_sha": SOURCE[i],
            "expected_exe_sha256": str(i + 1) * 64,
            "identity_return_target":
                "products/" + slug + "/store/approved-identity.json",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
        }
        jobs.append(job)
        is_post = i < post
        products.append({
            "batch_index": i + 1,
            **{k: job[k] for k in (
                "slug", "request_id", "source_repository", "source_branch",
                "source_sha", "identity_return_target", "registration_type",
                "partner_center_selection")},
            "observed_identity_state":
                "POST_IDENTITY_READY" if is_post else "PRE_IDENTITY_READY",
            "dispatch_action": resume.POST_ACTION if is_post else resume.PRE_ACTION,
            "identity_cas_authorized_by_plan": False,
            "partner_center_creation_authorized_by_plan": False,
        })
        if not is_post:
            proof.append({
                "batch_index": i + 1,
                "slug": slug,
                "request_id": job["request_id"],
                "source_sha": job["source_sha"],
                "source_snapshot_head": job["source_sha"],
                "identity_return_target": job["identity_return_target"],
                "queue_job_digest": "digest-" + slug,
                "exe_sha256": job["expected_exe_sha256"],
                "identity_capture": "NOT_PERFORMED",
                "github_return": "NOT_PERFORMED",
            })
    plan = {
        "status": "MIXED_ROTATION_DISPATCH_PLAN_READY",
        "discovered_count": 4,
        "post_identity_skip_count": post,
        "pre_identity_pending_count": 4 - post,
        "products": products,
        "local_windows_no_llm_pass": False,
        "task_scheduler_registration_allowed": False,
        "store_submission": "NOT_PERFORMED",
        "cas": "NOT_PERFORMED",
    }
    preflight = {
        "status": "MIXED_LOCAL_NO_IDENTITY_WORK" if post == 4
                  else "MIXED_LOCAL_PRECHECK_PASS",
        "central_head_sha": HEAD,
        "products": proof,
    }
    return {"rotation_cohorts": {"app_jobs": jobs}}, plan, preflight


class MixedResumeHostTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.args = SimpleNamespace(
            state_dir=Path(self.temp.name),
            execution_origin="MANUAL_WINDOWS_TERMINAL",
        )

    def run_host(self, *, post=1, mutate=None, drift=False,
                 central_head=HEAD):
        ledger, plan, preflight = fixtures(post)
        preflight["central_head_sha"] = central_head
        if mutate is not None:
            mutate(ledger, plan, preflight)
        heads = {j["source_branch"]: j["source_sha"]
                 for j in ledger["rotation_cohorts"]["app_jobs"]}
        if drift:
            heads["codex/file-integrity-ledger"] = "f" * 40
        with ExitStack() as stack:
            stack.enter_context(patch.object(
                host, "preflight_mixed_local", return_value=preflight))
            stack.enter_context(patch.object(
                host, "fetch_central", return_value=(ledger, central_head, "b" * 40)))
            stack.enter_context(patch.object(
                host, "audit_queue_only", return_value={"status": "MOCK_AUDIT"}))
            stack.enter_context(patch.object(
                host.rotation_plan, "build_dispatch_plan", return_value=plan))
            stack.enter_context(patch.object(
                host, "recheck_central", return_value=None))
            stack.enter_context(patch.object(
                host, "live_branch_head",
                side_effect=lambda repository, branch: heads[branch]))
            stack.enter_context(patch.object(
                host.operator, "canonical_digest",
                side_effect=lambda job: "digest-" + job["slug"]))
            return host.prepare_mixed_resume_state(self.args)

    def test_one_post_three_pre_state_is_persisted_without_ui(self):
        result = self.run_host()
        self.assertEqual(result["status"], "MIXED_RESUME_STATE_PREPARED")
        self.assertEqual(result["post_identity_skip_count"], 1)
        self.assertEqual(result["pre_identity_preflight_count"], 3)
        self.assertFalse(result["local_windows_no_llm_pass"])
        self.assertFalse(result["task_scheduler_registration_allowed"])
        self.assertEqual(result["cas"], "NOT_PERFORMED")
        state = json.loads(Path(result["state_path"]).read_text())
        self.assertEqual([x["status"] for x in state["products"]],
                         ["SKIPPED_GITHUB_POST_VERIFIED"] + ["PENDING"] * 3)
        self.assertIsNone(state["active_request_id"])

    def test_idempotent_replay_does_not_claim_or_rewrite(self):
        first = self.run_host()
        before = Path(first["state_path"]).read_bytes()
        second = self.run_host()
        self.assertEqual(first["state_path"], second["state_path"])
        self.assertEqual(Path(second["state_path"]).read_bytes(), before)

    def test_tampered_preflight_binding_blocks_state_creation(self):
        def tamper(ledger, plan, preflight):
            preflight["products"][0]["exe_sha256"] = "0" * 64
        with self.assertRaisesRegex(host.RunnerHold,
                                    "HOLD_MIXED_RESUME_PREFLIGHT_BINDING"):
            self.run_host(mutate=tamper)
        self.assertFalse((self.args.state_dir /
                          "mixed-resume-state.json").exists())

    def test_central_head_drift_blocks_state_creation(self):
        def tamper(ledger, plan, preflight):
            preflight["central_head_sha"] = "0" * 40
        with self.assertRaisesRegex(host.RunnerHold,
                                    "HOLD_MIXED_RESUME_CENTRAL_DRIFT"):
            self.run_host(mutate=tamper)
        self.assertFalse((self.args.state_dir /
                          "mixed-resume-state.json").exists())

    def test_source_head_drift_blocks_persistence(self):
        with self.assertRaisesRegex(
                host.RunnerHold, "HOLD_CANONICAL_PRODUCT_REVISION_MISMATCH"):
            self.run_host(drift=True)

    def test_persisted_fake_success_requires_independent_evidence(self):
        first = self.run_host()
        path = Path(first["state_path"])
        state = json.loads(path.read_text())
        entry = state["products"][1]
        entry["status"] = "IDENTITY_RETURN_VERIFIED"
        entry["result"] = {
            "request_id": entry["request_id"],
            "source_sha": entry["source_sha"],
            "store_submission": "NOT_PERFORMED",
        }
        path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(
                resume.MixedResumeHold,
                "HOLD_MIXED_RESUME_REPLAY_REQUIRES_INDEPENDENT_EVIDENCE"):
            self.run_host()


    def test_new_central_head_rebases_only_unchanged_pending_jobs(self):
        first = self.run_host()
        self.assertFalse(first["central_rebase_applied"])
        second = self.run_host(central_head="b" * 40)
        self.assertTrue(second["central_rebase_applied"])
        state = json.loads(Path(second["state_path"]).read_text())
        self.assertEqual(state["central_head_sha"], "b" * 40)
        self.assertEqual([x["status"] for x in state["products"]],
                         ["SKIPPED_GITHUB_POST_VERIFIED"] + ["PENDING"] * 3)
        self.assertFalse(second["local_windows_no_llm_pass"])
        self.assertFalse(second["task_scheduler_registration_allowed"])
        self.assertFalse(self.run_host(central_head="b" * 40)[
            "central_rebase_applied"])

    def test_rebase_rejects_unverified_pre_to_post_promotion(self):
        first = self.run_host()
        path = Path(first["state_path"])
        before = path.read_bytes()
        with self.assertRaisesRegex(rebase.RebaseHold,
                                    "HOLD_REBASE_PENDING_CHANGED"):
            self.run_host(post=2, central_head="b" * 40)
        self.assertEqual(path.read_bytes(), before)

    def test_rebase_refuses_locally_claimed_return_without_verifier(self):
        first = self.run_host()
        path = Path(first["state_path"])
        state = json.loads(path.read_text())
        entry = state["products"][1]
        entry["status"] = "IDENTITY_RETURN_VERIFIED"
        entry["result"] = {
            **{key: entry[key] for key in (
                "request_id", "source_sha", "identity_return_target",
                "registration_type", "partner_center_selection",
                "plan_job_digest")},
            "github_return_status": "APPLIED",
            "github_replay_status": "EXISTING_VERIFIED",
            "identity_capture_status":
                "IDENTITY_CAPTURED__AUTHENTICATED_UI__GITHUB_BOUND",
            "identity_return_commit_sha": "c" * 40,
            "store_id": "9PGZ445SR5GM",
            "pfn": "OkinawaDesktopTools.FileIntegrityLedger_j8yefg9jgfh58",
            "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
            "package_version_gate": "HOLD",
            "store_submission": "NOT_PERFORMED",
            "duplicate_creation": 0,
            "cross_product_contamination": 0,
        }
        path.write_text(json.dumps(state), encoding="utf-8")
        before = path.read_bytes()
        with self.assertRaisesRegex(
                rebase.RebaseHold, "HOLD_REBASE_INDEPENDENT_RETURN_EVIDENCE"):
            self.run_host(post=2, central_head="b" * 40)
        self.assertEqual(path.read_bytes(), before)

    def test_rebase_preserves_single_active_pending_job(self):
        first = self.run_host()
        path = Path(first["state_path"])
        state = json.loads(path.read_text())
        state, claimed = resume.claim_next(state)
        self.assertEqual(claimed["batch_index"], 2)
        path.write_text(json.dumps(state), encoding="utf-8")
        second = self.run_host(central_head="b" * 40)
        rebased = json.loads(path.read_text())
        self.assertTrue(second["central_rebase_applied"])
        self.assertEqual(rebased["active_request_id"], claimed["request_id"])
        self.assertEqual(rebased["products"][1]["status"], "ACTIVE")
        self.assertEqual(resume.claim_next(rebased)[1]["request_id"],
                         claimed["request_id"])

    def test_all_post_is_no_work_but_never_scheduler_pass(self):
        result = self.run_host(post=4)
        self.assertEqual(result["pre_identity_preflight_count"], 0)
        self.assertEqual(result["post_identity_skip_count"], 4)
        self.assertEqual(result["status"], "MIXED_RESUME_STATE_PREPARED")
        self.assertFalse(result["multi_product_identity_batch_pass"])
        self.assertEqual(result["store_submission"], "NOT_PERFORMED")


if __name__ == "__main__":
    import unittest
    unittest.main()
