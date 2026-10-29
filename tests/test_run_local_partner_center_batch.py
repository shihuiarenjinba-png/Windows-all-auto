"""Offline runner safety tests; no GitHub, browser, CAS, or Store action."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import run_local_partner_center_batch as runner


SHAS = (
    "8b00bc4e90828c4282463826873aa8dfd2eb93f4",
    "d1108d12f7d1697af30400f97c7db39cba5e6791",
    "a7d37280089893a9ea4b9ac3336020a920e73e0c",
    "16b6a772952ca0988f2ae2f8b5f4db2e59ec5877",
)


def ledger():
    jobs = []
    requests = []
    for index, (slug, sha) in enumerate(zip(runner.EXPECTED_ORDER, SHAS), 1):
        request_id = f"app-{slug}-{sha[:12]}"
        job = {
            "product_type": "APP", "display_name": slug.replace("-", " ").title(),
            "slug": slug, "status": "PRE_IDENTITY_READY", "request_id": request_id,
            "source_repository": "shihuiarenjinba-png/AI-App-Factory",
            "source_branch": f"codex/{slug}", "source_sha": sha,
            "factory_build_head": sha, "expected_exe_sha256": f"{index}" * 64,
            "expected_exe_bytes": 4096, "factory_artifact_id": 1000 + index,
            "factory_artifact_name": f"artifact-{index}",
            "factory_artifact_zip_sha256": f"{index + 4}" * 64,
            "artifact_metadata_verified": True,
            "factory_artifact_expiry_utc": "2099-01-01T00:00:00Z",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "identity_return_target": f"products/{slug}/store/approved-identity.json",
        }
        jobs.append(job)
        requests.append({
            "request_id": request_id, "slug": slug,
            "repo": job["source_repository"], "source_branch": job["source_branch"],
            "source_sha": sha, "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "identity_return_target": job["identity_return_target"],
            "status": "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE",
            "allow_local_product_creation": True,
        })
    return {
        "partner_center_local_operator": {"mode": "LOCAL_OPERATOR_ACTIVE__BATCH"},
        "rotation_cohorts": {"app_jobs": jobs, "three_d_jobs": []},
        "user_id_requests": {"items": requests},
    }


class RunnerTests(unittest.TestCase):
    def test_queue_discovers_exact_four_with_split_provenance(self):
        value = ledger()
        artifacts = {job["factory_artifact_id"]: {
            "expired": False, "name": job["factory_artifact_name"],
            "digest": "sha256:" + job["factory_artifact_zip_sha256"],
        } for job in value["rotation_cohorts"]["app_jobs"]}

        def fake_gh(endpoint, allow_missing=False):
            artifact_id = int(endpoint.rsplit("/", 1)[-1])
            return artifacts[artifact_id]

        with patch.object(runner, "live_branch_head",
                          side_effect=lambda repo, branch: next(
                              job["source_sha"] for job in value["rotation_cohorts"]["app_jobs"]
                              if job["source_branch"] == branch)), \
             patch.object(runner, "gh_json", side_effect=fake_gh):
            spec, jobs = runner.validate_queue(
                value, "a" * 40, "MANUAL_WINDOWS_TERMINAL"
            )
        self.assertEqual(len(jobs), 4)
        self.assertEqual(spec["dispatch_origin"], "CHATGPT_36_MIN_LOOP")
        self.assertEqual(spec["execution_origin"], "MANUAL_WINDOWS_TERMINAL")

    def test_canonical_revision_drift_fails_before_browser(self):
        value = ledger()
        with patch.object(runner, "live_branch_head", return_value="f" * 40):
            with self.assertRaisesRegex(runner.RunnerHold, "REVISION_MISMATCH"):
                runner.validate_queue(value, "a" * 40, "MANUAL_WINDOWS_TERMINAL")

    def test_completed_cas_commit_is_valid_resume_revision(self):
        value = ledger()
        focus = value["rotation_cohorts"]["app_jobs"][0]
        return_head = "c" * 40
        result = {
            "request_id": focus["request_id"],
            "source_sha": focus["source_sha"],
            "identity_return_commit_sha": return_head,
            "github_replay_status": "EXISTING_VERIFIED",
            "store_id": "9P6452C61N7B",
            "identity_name": "OkinawaDesktopTools.FocusSessionDesk",
            "pfn": "OkinawaDesktopTools.FocusSessionDesk_j8yefg9jgfh58",
            "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
            "execution_origin": "MANUAL_WINDOWS_TERMINAL",
        }
        approved = {
            "request_id": focus["request_id"],
            "source_sha": focus["source_sha"],
            "store_id": result["store_id"],
            "name": result["identity_name"],
            "package_family_name": result["pfn"],
            "package_sid": result["package_sid"],
            "dispatch_origin": "CHATGPT_36_MIN_LOOP",
            "execution_origin": "MANUAL_WINDOWS_TERMINAL",
        }
        artifacts = {job["factory_artifact_id"]: {
            "expired": False, "name": job["factory_artifact_name"],
            "digest": "sha256:" + job["factory_artifact_zip_sha256"],
        } for job in value["rotation_cohorts"]["app_jobs"]}

        def fake_head(repo, branch):
            job = next(item for item in value["rotation_cohorts"]["app_jobs"]
                       if item["source_branch"] == branch)
            return return_head if job is focus else job["source_sha"]

        def fake_gh(endpoint, allow_missing=False):
            if "/contents/" in endpoint:
                return {"encoding": "base64", "content": base64.b64encode(
                    json.dumps(approved).encode("utf-8")
                ).decode("ascii")}
            return artifacts[int(endpoint.rsplit("/", 1)[-1])]

        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            (state_dir / "batch-state.json").write_text(json.dumps({
                "central_head_sha": "a" * 40,
                "products": [{
                    "request_id": focus["request_id"],
                    "state": "SUCCESS", "result": result,
                }],
            }), encoding="utf-8")
            with patch.object(runner, "live_branch_head", side_effect=fake_head), \
                 patch.object(runner, "gh_json", side_effect=fake_gh):
                spec, jobs = runner.validate_queue(
                    value, "a" * 40, "MANUAL_WINDOWS_TERMINAL", state_dir
                )

        self.assertEqual(len(jobs), 4)
        self.assertEqual(spec["central_head_sha"], "a" * 40)

    def test_mixed_queue_accepts_only_verified_post_identity_product(self):
        value = ledger()
        focus = value["rotation_cohorts"]["app_jobs"][0]
        focus["status"] = "POST_IDENTITY_READY"
        return_head = "c" * 40
        result = {
            "request_id": focus["request_id"], "source_sha": focus["source_sha"],
            "identity_return_commit_sha": return_head,
            "github_replay_status": "EXISTING_VERIFIED",
            "store_id": "9P6452C61N7B",
            "identity_name": "OkinawaDesktopTools.FocusSessionDesk",
            "pfn": "OkinawaDesktopTools.FocusSessionDesk_j8yefg9jgfh58",
            "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
            "execution_origin": "MANUAL_WINDOWS_TERMINAL",
        }
        approved = {
            "request_id": focus["request_id"], "source_sha": focus["source_sha"],
            "store_id": result["store_id"], "name": result["identity_name"],
            "package_family_name": result["pfn"],
            "package_sid": result["package_sid"],
            "dispatch_origin": "CHATGPT_36_MIN_LOOP",
            "execution_origin": result["execution_origin"],
        }
        artifacts = {job["factory_artifact_id"]: {
            "expired": False, "name": job["factory_artifact_name"],
            "digest": "sha256:" + job["factory_artifact_zip_sha256"],
        } for job in value["rotation_cohorts"]["app_jobs"]}

        def fake_head(repo, branch):
            job = next(x for x in value["rotation_cohorts"]["app_jobs"]
                       if x["source_branch"] == branch)
            return return_head if job is focus else job["source_sha"]

        def fake_gh(endpoint, allow_missing=False):
            if "/contents/" in endpoint:
                return {"encoding": "base64", "content": base64.b64encode(
                    json.dumps(approved).encode("utf-8")
                ).decode("ascii")}
            return artifacts[int(endpoint.rsplit("/", 1)[-1])]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "batch-state.json").write_text(json.dumps({
                "batch_id": "app-batch4-old", "central_head_sha": "a" * 40,
                "products": [{"request_id": focus["request_id"],
                              "state": "SUCCESS", "result": result}],
            }), encoding="utf-8")
            with patch.object(runner, "live_branch_head", side_effect=fake_head), \
                 patch.object(runner, "gh_json", side_effect=fake_gh):
                spec, jobs = runner.validate_queue(
                    value, "b" * 40, "MANUAL_WINDOWS_TERMINAL", root
                )
        self.assertEqual(spec["batch_id"], "app-batch4-old")
        self.assertEqual([job["status"] for job in jobs], [
            "POST_IDENTITY_READY", "PRE_IDENTITY_READY",
            "PRE_IDENTITY_READY", "PRE_IDENTITY_READY",
        ])

    def test_inflight_applied_identity_allows_exact_replay_resume(self):
        value = ledger()
        job = value["rotation_cohorts"]["app_jobs"][1]
        return_head = "d" * 40
        receipt = {
            "request_id": job["request_id"], "slug": job["slug"],
            "source_repository": job["source_repository"],
            "source_branch": job["source_branch"], "source_sha": job["source_sha"],
            "identity_return_target": job["identity_return_target"],
            "store_id": "9PGZ445SR5GM",
            "identity_name": "OkinawaDesktopTools.FileIntegrityLedger",
            "publisher": "CN=46263F21-A700-41DB-8C9B-114C22FB82FC",
            "package_family_name": "OkinawaDesktopTools.FileIntegrityLedger_j8yefg9jgfh58",
            "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
            "execution_origin": "MANUAL_WINDOWS_TERMINAL",
        }
        approved = {
            "request_id": job["request_id"], "source_sha": job["source_sha"],
            "store_id": receipt["store_id"], "name": receipt["identity_name"],
            "publisher": receipt["publisher"],
            "package_family_name": receipt["package_family_name"],
            "package_sid": receipt["package_sid"],
            "dispatch_origin": "CHATGPT_36_MIN_LOOP",
            "execution_origin": receipt["execution_origin"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            product = root / "products" / job["request_id"]
            product.mkdir(parents=True)
            (product / "official-identity.json").write_text(
                json.dumps(receipt), encoding="utf-8"
            )
            (root / "batch-state.json").write_text(json.dumps({
                "products": [{"request_id": job["request_id"],
                              "state": "PROCESSING", "result": None}],
            }), encoding="utf-8")
            with patch.object(runner, "gh_json", return_value={
                "encoding": "base64", "content": base64.b64encode(
                    json.dumps(approved).encode("utf-8")
                ).decode("ascii"),
            }):
                self.assertTrue(runner.completed_identity_return_matches(
                    job, return_head, root, "a" * 40
                ))

    def test_reconcile_updates_only_unfinished_queue_provenance(self):
        value = ledger()
        jobs = value["rotation_cohorts"]["app_jobs"]
        products = []
        for index, job in enumerate(jobs):
            products.append({
                "request_id": job["request_id"], "slug": job["slug"],
                "source_sha": job["source_sha"],
                "identity_return_target": job["identity_return_target"],
                "artifact_id": job["factory_artifact_id"],
                "expected_exe_sha256": job["expected_exe_sha256"],
                "queue_job_digest": "old", "state": "SUCCESS" if index == 0 else "PENDING",
                "result": {"immutable": True} if index == 0 else None,
            })
        state = {"central_head_sha": "a" * 40, "products": products}
        runner._reconcile_existing_state(state, jobs, "b" * 40)
        self.assertEqual(state["central_head_sha"], "b" * 40)
        self.assertEqual(state["products"][0]["queue_job_digest"], "old")
        self.assertEqual(state["products"][0]["result"], {"immutable": True})
        self.assertEqual(
            state["products"][1]["queue_job_digest"],
            runner.operator.canonical_digest(jobs[1]),
        )

    def test_reconciled_operator_job_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = {
                "request_id": "app-sample-aaaaaaaaaaaa", "slug": "sample",
                "product_type": "APP", "display_name": "Sample",
                "source_repository": "owner/repo", "source_branch": "codex/sample",
                "source_sha": "a" * 40,
                "identity_return_target": "products/sample/store/approved-identity.json",
                "batch_id": "batch-old", "batch_index": 2, "batch_total": 4,
                "central_head_sha": "a" * 40,
            }
            runner.write_once(root / "operator-job.json", original)
            updated = {**original, "central_head_sha": "b" * 40}
            path = runner.write_reconciled_operator_job(root, updated)
            self.assertEqual(path.name, "operator-job.bbbbbbbbbbbb.json")
            self.assertEqual(json.loads((root / "operator-job.json").read_text()), original)
            self.assertEqual(json.loads(path.read_text()), updated)

    def test_artifact_and_exe_are_both_hashed(self):
        payload = b"MZ" + b"x" * 4094
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "test-product"
            target.mkdir()
            archive = target / "123.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("bin/product.exe", payload)
                bundle.writestr("provenance.json", "{}")
            job = {
                "slug": "test-product", "factory_artifact_id": 123,
                "factory_artifact_zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "expected_exe_sha256": hashlib.sha256(payload).hexdigest(),
                "expected_exe_bytes": len(payload),
            }
            result = runner.verify_artifact(job, root)
            self.assertEqual(result["exe_sha256"], job["expected_exe_sha256"])
            self.assertTrue(Path(result["exe_path"]).is_file())

    def test_artifact_path_traversal_is_rejected(self):
        payload = b"MZ" + b"x" * 4094
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "test-product"
            target.mkdir()
            archive = target / "123.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../product.exe", payload)
            job = {
                "slug": "test-product", "factory_artifact_id": 123,
                "factory_artifact_zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "expected_exe_sha256": hashlib.sha256(payload).hexdigest(),
                "expected_exe_bytes": len(payload),
            }
            with self.assertRaisesRegex(runner.RunnerHold, "ARTIFACT_UNSAFE"):
                runner.verify_artifact(job, root)

    def test_scheduler_manual_start_marker_is_one_shot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "scheduler-manual-start.marker"
            marker.write_text("manual\n", encoding="utf-8")
            self.assertEqual(
                runner.resolve_execution_origin("WINDOWS_TASK_SCHEDULER", root),
                "WINDOWS_TASK_SCHEDULER_MANUAL_START",
            )
            self.assertFalse(marker.exists())
            self.assertEqual(
                runner.resolve_execution_origin("WINDOWS_TASK_SCHEDULER", root),
                "WINDOWS_TASK_SCHEDULER",
            )

    def test_completed_manual_batch_is_no_work_for_scheduler(self):
        state = {
            "batch_id": "batch-1",
            "central_head_sha": "a" * 40,
            "execution_origin": "MANUAL_WINDOWS_TERMINAL",
            "final_status": "MULTI_PRODUCT_IDENTITY_BATCH_PASS",
        }
        self.assertTrue(runner.validate_existing_state(
            state, {"batch_id": "batch-1"}, "a" * 40,
            "WINDOWS_TASK_SCHEDULER_MANUAL_START",
        ))

    def test_in_progress_manual_batch_cannot_be_taken_over_by_scheduler(self):
        state = {
            "batch_id": "batch-1",
            "central_head_sha": "a" * 40,
            "execution_origin": "MANUAL_WINDOWS_TERMINAL",
            "final_status": "BATCH_DISCOVERED",
        }
        with self.assertRaisesRegex(
                runner.RunnerHold, "BATCH_EXISTING_STATE_CONFLICT"):
            runner.validate_existing_state(
                state, {"batch_id": "batch-1"}, "a" * 40,
                "WINDOWS_TASK_SCHEDULER_MANUAL_START",
            )


if __name__ == "__main__":
    unittest.main()
