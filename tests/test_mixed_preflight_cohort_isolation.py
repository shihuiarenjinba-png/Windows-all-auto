"""Regression: mixed APP PRE cohort shrinks after each verified Identity return.

These tests are offline; no browser, CAS, Store action or physical Windows PASS.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from scripts import run_local_partner_center_batch as host


SOURCE = "d1108d12f7d1697af30400f97c7db39cba5e6791"
REQUEST = "app-file-integrity-ledger-d1108d12f7d1"
REPO = "shihuiarenjinba-png/AI-App-Factory"
TARGET = "products/file-integrity-ledger/store/approved-identity.json"


def pending(index=2, slug="file-integrity-ledger", sha=SOURCE):
    return {
        "batch_index": index,
        "slug": slug,
        "request_id": REQUEST if index == 2 else "app-" + slug + "-" + sha[:12],
        "source_repository": REPO,
        "source_branch": "codex/" + slug,
        "source_sha": sha,
        "identity_return_target": (
            "products/" + slug + "/store/approved-identity.json"
        ),
    }


class MixedPreflightCohortIsolationTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_dir = Path(self.tmp.name)

    def snapshot(self, cohort, job=None):
        job = job or pending()
        path = (cohort / "sources" / "AI-App-Factory" /
                job["source_sha"][:12])
        path.mkdir(parents=True, exist_ok=True)
        return path

    def test_same_cohort_is_deterministic(self):
        jobs = [pending(), pending(3, "offline-text-diff-desk", "a" * 40)]
        a = host.mixed_preflight_root(self.state_dir, jobs)
        b = host.mixed_preflight_root(self.state_dir, [dict(j) for j in jobs])
        self.assertEqual(a, b)
        self.assertEqual(len(a.name), 24)

    def test_promotion_changes_namespace_without_overwriting_old_manifest(self):
        jobs = [pending(), pending(3, "offline-text-diff-desk", "a" * 40)]
        before = host.mixed_preflight_root(self.state_dir, jobs)
        before.mkdir(parents=True)
        manifest = before / "source-sync-manifest.json"
        manifest.write_text("original immutable cohort", encoding="utf-8")
        after = host.mixed_preflight_root(self.state_dir, jobs[1:])
        self.assertNotEqual(before, after)
        self.assertFalse(after.exists())
        self.assertEqual(manifest.read_text(encoding="utf-8"),
                         "original immutable cohort")

    def test_incomplete_pending_cohort_fails_closed(self):
        bad = pending()
        del bad["identity_return_target"]
        with self.assertRaisesRegex(host.RunnerHold,
                                    "HOLD_MIXED_PREFLIGHT_COHORT_INVALID"):
            host.mixed_preflight_root(self.state_dir, [bad])

    def test_exact_source_inside_cohort_is_accepted(self):
        job = pending()
        cohort = host.mixed_preflight_root(self.state_dir, [job])
        path = self.snapshot(cohort, job)
        self.assertEqual(
            host.validated_mixed_source_path(
                self.state_dir, {"source_snapshot_path": str(path)}, job),
            path,
        )

    def test_external_source_path_is_rejected(self):
        job = pending()
        outside = self.state_dir / "unmanaged" / "AI-App-Factory" / SOURCE[:12]
        outside.mkdir(parents=True)
        with self.assertRaisesRegex(host.RunnerHold,
                                    "HOLD_MIXED_SOURCE_PATH_UNTRUSTED"):
            host.validated_mixed_source_path(
                self.state_dir, {"source_snapshot_path": str(outside)}, job)

    def test_wrong_repo_or_sha_path_is_rejected(self):
        job = pending()
        cohort = host.mixed_preflight_root(self.state_dir, [job])
        path = self.snapshot(cohort, job)
        for changed in (
            {**job, "source_sha": "f" * 40},
            {**job, "source_repository": "other/Another-Factory"},
        ):
            with self.assertRaisesRegex(
                    host.RunnerHold, "HOLD_MIXED_SOURCE_PATH_UNTRUSTED"):
                host.validated_mixed_source_path(
                    self.state_dir, {"source_snapshot_path": str(path)}, changed)

    def test_receipt_path_cannot_be_missing_or_relative(self):
        for raw in (None, "", "mixed-preflight/cohorts/fake"):
            with self.assertRaisesRegex(
                    host.RunnerHold, "HOLD_MIXED_SOURCE_PATH_UNTRUSTED"):
                host.validated_mixed_source_path(
                    self.state_dir, {"source_snapshot_path": raw}, pending())

    def test_independent_rebase_verifier_uses_original_cohort_snapshot(self):
        job = {**pending(), "slug": "file-integrity-ledger",
               "identity_return_commit_sha": "c" * 40}
        cohort = host.mixed_preflight_root(self.state_dir, [job])
        path = self.snapshot(cohort, job)
        receipt = {
            **{key: job[key] for key in (
                "request_id", "slug", "source_sha", "source_repository",
                "source_branch", "identity_return_target")},
            "source_snapshot_path": str(path),
            "queue_job_digest": "original-digest",
            "store_id": "9PGZ445SR5GM",
            "package_family_name": "OkinawaDesktopTools.FileIntegrityLedger_j8yefg9jgfh58",
            "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
        }
        old = {**job, "plan_job_digest": "plan-digest"}
        result = {
            "request_id": REQUEST,
            "source_sha": SOURCE,
            "plan_job_digest": "plan-digest",
            "queue_job_digest": "original-digest",
            "store_id": receipt["store_id"],
            "pfn": receipt["package_family_name"],
            "package_sid": receipt["package_sid"],
            "identity_return_commit_sha": "c" * 40,
        }
        fresh = {**job, "status": "SKIPPED_GITHUB_POST_VERIFIED"}
        ledger = {"rotation_cohorts": {"app_jobs": [job]}}
        driver = SimpleNamespace(verify_current=lambda observation, value: True)
        with patch.object(host.operator, "read_json", return_value=receipt), \
             patch.object(host, "existing_observation", return_value=object()), \
             patch.object(host, "github_result_verified", return_value=True) as verified:
            self.assertTrue(host.verify_mixed_local_return(
                old, result, fresh, ledger, self.state_dir, "b" * 40, driver))
            self.assertEqual(verified.call_args.args[-1], path)

    def test_unmanaged_receipt_path_cannot_authenticate_return(self):
        job = {**pending(), "identity_return_commit_sha": "c" * 40}
        receipt = {
            **{key: job[key] for key in (
                "request_id", "slug", "source_sha", "source_repository",
                "source_branch", "identity_return_target")},
            "source_snapshot_path": str(self.state_dir / "unmanaged"),
            "queue_job_digest": "digest",
            "store_id": "9PGZ445SR5GM",
            "package_family_name": "name_j8yefg9jgfh58",
            "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
        }
        (self.state_dir / "unmanaged").mkdir()
        old = {**job, "plan_job_digest": "plan"}
        result = {
            "request_id": REQUEST, "source_sha": SOURCE,
            "plan_job_digest": "plan", "queue_job_digest": "digest",
            "store_id": receipt["store_id"],
            "pfn": receipt["package_family_name"],
            "package_sid": receipt["package_sid"],
            "identity_return_commit_sha": "c" * 40,
        }
        with patch.object(host.operator, "read_json", return_value=receipt), \
             patch.object(host, "existing_observation", return_value=object()), \
             patch.object(host, "github_result_verified", return_value=True) as verified:
            self.assertFalse(host.verify_mixed_local_return(
                old, result, {**job, "status": "SKIPPED_GITHUB_POST_VERIFIED"},
                {"rotation_cohorts": {"app_jobs": [job]}}, self.state_dir,
                "b" * 40,
                SimpleNamespace(verify_current=lambda *args: True)))
            verified.assert_not_called()
