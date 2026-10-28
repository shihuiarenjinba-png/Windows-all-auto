"""Offline runner safety tests; no GitHub, browser, CAS, or Store action."""
import hashlib
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


if __name__ == "__main__":
    unittest.main()
