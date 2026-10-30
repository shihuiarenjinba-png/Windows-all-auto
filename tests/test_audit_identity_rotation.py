"""Read-only mixed PRE/POST queue regression; no network/browser/CAS."""
from pathlib import Path
import tempfile
from datetime import datetime, timezone
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import audit_identity_rotation as audit
from scripts import run_local_partner_center_batch as runner


def fixture():
    jobs, records, approved, artifacts = [], [], {}, {}
    for i, slug in enumerate(audit.ORDER, 1):
        sha = str(i) * 40
        source_branch = f"codex/{slug}"
        request_id = f"app-{slug}-{sha[:12]}"
        target = f"products/{slug}/store/approved-identity.json"
        job = {
            "product_type": "APP", "slug": slug,
            "display_name": slug.replace("-", " ").title(),
            "status": "POST_IDENTITY_READY" if i == 1 else "PRE_IDENTITY_READY",
            "source_repository": "shihuiarenjinba-png/AI-App-Factory",
            "source_branch": source_branch, "source_sha": sha,
            "request_id": request_id, "identity_return_target": target,
            "factory_build_head": sha, "expected_exe_sha256": str(i) * 64,
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "factory_artifact_id": 1000 + i,
            "factory_artifact_name": f"artifact-{i}",
            "factory_artifact_zip_sha256": str(i + 4) * 64,
            "factory_artifact_expiry_utc": "2099-01-01T00:00:00Z",
            "artifact_metadata_verified": True,
        }
        if i == 1:
            job["identity_return_commit_sha"] = "a" * 40
            job["identity_store_id"] = "9P6452C61N7B"
            job["identity_pfn"] = "Publisher.Focus_abcdefghijklm"
            approved[slug] = {
                "reviewed": True, "source": "partner_center",
                "request_id": request_id, "product_type": "APP",
                "source_repository": job["source_repository"],
                "source_branch": source_branch, "source_sha": sha,
                "expected_head_sha": sha,
                "package_sha256": job["expected_exe_sha256"],
                "package_version_gate": "HOLD",
                "store_id": "9P6452C61N7B", "name": "Publisher.Focus",
                "reserved_display_name": job["display_name"],
                "publisher_display_name": "Example Publisher",
                "publisher": "CN=Example",
                "package_family_name": "Publisher.Focus_abcdefghijklm",
                "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
            }
        artifacts[job["factory_artifact_id"]] = {
            "expired": False, "name": job["factory_artifact_name"],
            "expires_at": job["factory_artifact_expiry_utc"],
            "digest": "sha256:" + job["factory_artifact_zip_sha256"],
        }
        jobs.append(job)
        records.append({
            "batch_index": i, "slug": slug, "request_id": request_id,
            "source_repository": job["source_repository"],
            "source_branch": source_branch, "source_sha": sha,
        })
    pipeline = []
    for job in jobs:
        record = {
            "product": job["slug"].replace("-", " ").title(),
            "lane": "APP", "request_id": job["request_id"],
            "source_repository": job["source_repository"],
            "source_branch": job["source_branch"],
            "source_sha": job["source_sha"],
            "identity_return_target": job["identity_return_target"],
            "state": ("POST_IDENTITY_READY" if job["status"] == "POST_IDENTITY_READY"
                      else "WAITING_IDENTITY_CAPTURE_AND_CAS"),
        }
        if job["status"] == "POST_IDENTITY_READY":
            record["identity_store_id"] = job["identity_store_id"]
            record["identity_pfn"] = job["identity_pfn"]
        pipeline.append(record)
    ledger = {
        "rotation_cohorts": {"app_jobs": jobs},
        "multi_product_partner_center_batch_4": {"products": records},
        "post_identity_pipeline": {"products": pipeline},
        "user_id_requests": {"items": [
            {"request_id": job["request_id"], "product_name": job["display_name"],
             "repo": job["source_repository"], "source_branch": job["source_branch"],
             "source_sha": job["source_sha"],
             "identity_return_target": job["identity_return_target"],
             "product_type": job["product_type"], "slug": job["slug"],
             "registration_type": job["registration_type"],
             "partner_center_selection": job["partner_center_selection"]}
            for job in jobs
        ]},
        "registration_router": {"entries": [
            {"product": job["display_name"], "repository": job["source_repository"],
             "registration_type": job["registration_type"],
             "partner_center_selection": job["partner_center_selection"]}
            for job in jobs
        ]},
    }
    return ledger, approved, artifacts


def check(ledger, approved, artifacts, **overrides):
    def fetch_head(repo, branch):
        job = next(j for j in ledger["rotation_cohorts"]["app_jobs"]
                   if j["source_branch"] == branch)
        return overrides.get("head", {}).get(
            job["slug"], job.get("identity_return_commit_sha", job["source_sha"])
        )
    def fetch_approved(repo, path, branch):
        slug = path.split("/")[1]
        value = overrides.get("approved_override", approved).get(slug)
        return json.dumps(value) if isinstance(value, dict) else value
    return audit.audit_rotation(
        ledger, fetch_head=fetch_head, fetch_approved=fetch_approved,
        fetch_ancestry=lambda repo, source, head, target: overrides.get("ancestry", True),
        fetch_artifact=lambda repo, artifact_id: artifacts[artifact_id],
        now_utc=datetime(2026, 10, 29, tzinfo=timezone.utc),
    )


class MixedAuditTests(unittest.TestCase):
    def test_one_post_three_pre_audited_without_local_pass(self):
        ledger, approved, artifacts = fixture()
        result = check(ledger, approved, artifacts)
        self.assertEqual(result["status"], "MIXED_ROTATION_AUDITED")
        self.assertEqual(result["post_identity_github_verified"], 1)
        self.assertEqual(result["pre_identity_github_verified"], 3)
        self.assertFalse(result["local_batch_runner_ready"])
        self.assertFalse(result["local_windows_no_llm_pass"])
        self.assertEqual(result["store_submission"], "NOT_PERFORMED")
        self.assertEqual(result["cas"], "NOT_PERFORMED")

    def test_all_identity_file_reads_use_immutable_observed_heads(self):
        ledger, approved, artifacts = fixture()
        observed = []
        def head(repo, branch):
            job = next(j for j in ledger["rotation_cohorts"]["app_jobs"]
                       if j["source_branch"] == branch)
            return job.get("identity_return_commit_sha", job["source_sha"])
        def approved_at_commit(repo, path, commit_sha):
            slug = path.split("/")[1]
            job = next(j for j in ledger["rotation_cohorts"]["app_jobs"]
                       if j["slug"] == slug)
            self.assertEqual(commit_sha, head(repo, job["source_branch"]))
            self.assertNotEqual(commit_sha, job["source_branch"])
            observed.append((slug, commit_sha))
            return json.dumps(approved[slug]) if slug in approved else None
        result = audit.audit_rotation(
            ledger, fetch_head=head, fetch_approved=approved_at_commit,
            fetch_ancestry=lambda *_: True,
            fetch_artifact=lambda repo, aid: artifacts[aid],
            now_utc=datetime(2026, 10, 29, tzinfo=timezone.utc),
        )
        self.assertEqual(result["discovered_count"], 4)
        self.assertEqual(len(observed), 4)
        self.assertEqual(observed[0][1], "a" * 40)

    def test_post_unrelated_head_holds_before_promotion(self):
        ledger, approved, artifacts = fixture()
        with self.assertRaisesRegex(audit.AuditHold, "HOLD_SOURCE_ANCESTRY_CONFLICT"):
            check(ledger, approved, artifacts, ancestry=False)

    def test_live_compare_requires_exact_merge_base_and_ahead(self):
        repo = "shihuiarenjinba-png/AI-App-Factory"
        source, head = "a" * 40, "b" * 40
        good = {"status": "ahead", "ahead_by": 1, "behind_by": 0,
                "merge_base_commit": {"sha": source},
                "files": [{"filename": "products/focus-session-desk/store/approved-identity.json",
                           "status": "added"}]}
        target = "products/focus-session-desk/store/approved-identity.json"
        with patch.object(runner, "gh_json", return_value=good) as gh:
            self.assertTrue(runner.verify_source_ancestry(repo, source, head, target))
            gh.assert_called_once_with(f"repos/{repo}/compare/{source}...{head}")
        for bad in (
            {**good, "status": "diverged"},
            {**good, "ahead_by": 0},
            {**good, "ahead_by": 2},
            {**good, "behind_by": 1},
            {**good, "merge_base_commit": {"sha": "c" * 40}},
            {**good, "files": []},
            {**good, "files": [{"filename": "README.md", "status": "modified"}]},
            {**good, "files": [{"filename": target, "status": "modified"}]},
            {**good, "files": good["files"] + [
                {"filename": "src/app.py", "status": "modified"}]},
            {**good, "files": [{"filename": "products/other/store/approved-identity.json",
                               "status": "added"}]},
            None,
        ):
            with self.subTest(bad=bad), patch.object(runner, "gh_json", return_value=bad):
                self.assertFalse(runner.verify_source_ancestry(repo, source, head, target))
        with patch.object(runner, "gh_json") as gh:
            self.assertFalse(runner.verify_source_ancestry(repo, source, source, target))
            gh.assert_not_called()

    def test_post_head_drift_holds(self):
        ledger, approved, artifacts = fixture()
        with self.assertRaisesRegex(audit.AuditHold, "RETURN_COMMIT_DRIFT"):
            check(ledger, approved, artifacts, head={"focus-session-desk": "b" * 40})

    def test_post_wrong_product_identity_holds(self):
        ledger, approved, artifacts = fixture()
        approved["focus-session-desk"]["source_sha"] = "f" * 40
        with self.assertRaisesRegex(audit.AuditHold, "IDENTITY_BINDING_CONFLICT"):
            check(ledger, approved, artifacts)

    def test_post_missing_canonical_pfn_holds(self):
        ledger, approved, artifacts = fixture()
        ledger["rotation_cohorts"]["app_jobs"][0].pop("identity_pfn")
        with self.assertRaisesRegex(audit.AuditHold, "CENTRAL_IDENTITY_CONFLICT"):
            check(ledger, approved, artifacts)

    def test_post_canonical_pfn_mismatch_holds(self):
        ledger, approved, artifacts = fixture()
        ledger["rotation_cohorts"]["app_jobs"][0]["identity_pfn"] = (
            "Publisher.Wrong_abcdefghijklm"
        )
        with self.assertRaisesRegex(audit.AuditHold, "CENTRAL_IDENTITY_CONFLICT"):
            check(ledger, approved, artifacts)

    def test_post_missing_approved_file_holds(self):
        ledger, approved, artifacts = fixture()
        approved.clear()
        with self.assertRaisesRegex(audit.AuditHold, "IDENTITY_FILE_INVALID"):
            check(ledger, approved, artifacts)

    def test_duplicate_json_key_holds(self):
        ledger, approved, artifacts = fixture()
        raw = '{"store_id":"A","store_id":"B"}'
        with self.assertRaisesRegex(audit.AuditHold, "DUPLICATE_KEY"):
            check(ledger, approved, artifacts,
                  approved_override={"focus-session-desk": raw})

    def test_pre_identity_file_present_requires_reconciliation(self):
        ledger, approved, artifacts = fixture()
        approved["file-integrity-ledger"] = approved["focus-session-desk"]
        with self.assertRaisesRegex(audit.AuditHold, "LEDGER_STALE"):
            check(ledger, approved, artifacts)

    def test_pre_head_drift_holds(self):
        ledger, approved, artifacts = fixture()
        with self.assertRaisesRegex(audit.AuditHold, "PRE_IDENTITY_HEAD_DRIFT"):
            check(ledger, approved, artifacts,
                  head={"file-integrity-ledger": "f" * 40})

    def test_artifact_expiry_holds(self):
        ledger, approved, artifacts = fixture()
        ledger["rotation_cohorts"]["app_jobs"][1]["factory_artifact_expiry_utc"] = (
            "2026-10-28T00:00:00Z"
        )
        with self.assertRaisesRegex(audit.AuditHold, "ARTIFACT_EXPIRED"):
            check(ledger, approved, artifacts)

    def test_remote_artifact_expiry_missing_holds_before_plan(self):
        ledger, approved, artifacts = fixture()
        artifacts[1002].pop("expires_at")
        with self.assertRaisesRegex(audit.AuditHold, "ARTIFACT_EXPIRY_UNVERIFIED"):
            check(ledger, approved, artifacts)

    def test_remote_artifact_expiry_conflicts_with_queue(self):
        ledger, approved, artifacts = fixture()
        artifacts[1002]["expires_at"] = "2099-01-02T00:00:00Z"
        with self.assertRaisesRegex(audit.AuditHold, "ARTIFACT_EXPIRY_CONFLICT"):
            check(ledger, approved, artifacts)

    def test_remote_artifact_expired_flag_holds(self):
        ledger, approved, artifacts = fixture()
        artifacts[1002]["expired"] = True
        with self.assertRaisesRegex(audit.AuditHold, "ARTIFACT_MISMATCH"):
            check(ledger, approved, artifacts)

    def test_remote_artifact_malformed_timezone_holds(self):
        ledger, approved, artifacts = fixture()
        artifacts[1002]["expires_at"] = "2099-01-01T00:00:00"
        with self.assertRaisesRegex(audit.AuditHold, "ARTIFACT_EXPIRY_UNVERIFIED"):
            check(ledger, approved, artifacts)

    def test_cross_product_duplicate_request_holds(self):
        ledger, approved, artifacts = fixture()
        ledger["rotation_cohorts"]["app_jobs"][1]["request_id"] = (
            ledger["rotation_cohorts"]["app_jobs"][0]["request_id"]
        )
        with self.assertRaisesRegex(audit.AuditHold, "CROSS_LANE_BINDING"):
            check(ledger, approved, artifacts)

    def test_cross_lane_request_collision_holds(self):
        ledger, approved, artifacts = fixture()
        ledger["rotation_cohorts"]["three_d_jobs"] = [{
            "product_type": "GAME_3D", "slug": "prism-route-3d",
            "request_id": ledger["rotation_cohorts"]["app_jobs"][0]["request_id"],
            "identity_return_target": "products/prism-route-3d/store/approved-identity.json",
        }]
        with self.assertRaisesRegex(audit.AuditHold, "CROSS_LANE_BINDING"):
            check(ledger, approved, artifacts)

    def test_post_exe_hash_conflict_rejected_by_shared_reconciler(self):
        ledger, approved, artifacts = fixture()
        approved["focus-session-desk"]["package_sha256"] = "f" * 64
        with self.assertRaisesRegex(audit.AuditHold, "PREIDENTITY_ARTIFACT_CONFLICT"):
            check(ledger, approved, artifacts)

    def test_post_store_id_collision_with_3d_rejected(self):
        ledger, approved, artifacts = fixture()
        ledger["rotation_cohorts"]["three_d_jobs"] = [{
            "product_type": "GAME_3D", "slug": "prism-route-3d",
            "display_name": "Prism Route 3D",
            "request_id": "3d-prism-route-3d-abcdef",
            "identity_return_target": "products/prism-route-3d/store/approved-identity.json",
            "identity_store_id": "9P6452C61N7B",
        }]
        with self.assertRaisesRegex(audit.AuditHold, "CROSS_PRODUCT_IDENTITY"):
            check(ledger, approved, artifacts)

    def test_audit_hold_does_not_create_local_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "must-not-create"
            with patch.object(runner, "audit_queue_only",
                              side_effect=audit.AuditHold("HOLD_PRE_IDENTITY_HEAD_DRIFT")):
                code = runner.main(["--audit-queue", "--state-dir", str(root)])
            self.assertEqual(code, 2)
            self.assertFalse(root.exists())

    def test_audit_entrypoint_never_calls_browser_or_local_cas(self):
        ledger, approved, artifacts = fixture()
        def fake_gh(endpoint, allow_missing=False):
            if "/compare/" in endpoint:
                source, head = endpoint.split("/compare/", 1)[1].split("...", 1)
                self.assertEqual(source, "1" * 40)
                self.assertEqual(head, "a" * 40)
                return {"status": "ahead", "ahead_by": 1, "behind_by": 0,
                        "merge_base_commit": {"sha": source},
                        "files": [{"filename": "products/focus-session-desk/store/approved-identity.json",
                                   "status": "added"}]}
            if "/contents/" in endpoint:
                slug = endpoint.split("/products/")[1].split("/")[0]
                job = next(j for j in ledger["rotation_cohorts"]["app_jobs"]
                           if j["slug"] == slug)
                expected = job.get("identity_return_commit_sha", job["source_sha"])
                self.assertTrue(endpoint.endswith(f"?ref={expected}"))
                item = approved.get(slug)
                if item is None:
                    return None
                import base64
                return {"encoding": "base64",
                        "content": base64.b64encode(
                            json.dumps(item).encode("utf-8")).decode("ascii")}
            artifact_id = int(endpoint.rsplit("/", 1)[-1])
            return artifacts[artifact_id]
        def head(repo, branch):
            job = next(x for x in ledger["rotation_cohorts"]["app_jobs"]
                       if x["source_branch"] == branch)
            return job.get("identity_return_commit_sha", job["source_sha"])
        with (patch.object(runner, "fetch_central",
                           return_value=(ledger, "a" * 40, "blob")),
              patch.object(runner, "live_branch_head", side_effect=head),
              patch.object(runner, "gh_json", side_effect=fake_gh),
              patch.object(runner, "recheck_central"),
              patch.object(runner, "PartnerCenterDriver") as browser,
              patch.object(runner, "import_provisioner") as provisioner,
              patch.object(runner, "sync_sources") as sync):
            result = runner.audit_queue_only(SimpleNamespace())
            self.assertEqual(result["post_identity_github_verified"], 1)
            browser.assert_not_called()
            provisioner.assert_not_called()
            sync.assert_not_called()


if __name__ == "__main__":
    unittest.main()
