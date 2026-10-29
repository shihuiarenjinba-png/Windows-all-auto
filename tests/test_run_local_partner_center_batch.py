"""Offline runner safety tests; no GitHub, browser, CAS, or Store action."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
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
    def test_registration_preflight_is_read_only_and_not_host_attestation(self):
        args = SimpleNamespace(
            provisioner_root=Path("C:/isolated-provisioner"),
            execution_origin="WINDOWS_TASK_SCHEDULER",
        )
        with (
            patch.object(runner, "check_prerequisites", return_value={"provisioner_head": "a" * 40}),
            patch.object(runner, "fetch_central", return_value=({}, "b" * 40, "blob")),
            patch.object(runner, "validate_queue", return_value=({"batch_id": "batch"}, [{}] * 4)),
            patch.object(runner, "recheck_central") as recheck,
            patch.object(runner.batch, "discover", return_value={"discovered_count": 4}),
            patch.object(runner, "sync_sources") as sync,
            patch.object(runner, "verify_artifact") as artifact,
            patch.object(runner, "PartnerCenterDriver") as browser,
        ):
            result = runner.preflight_only(args)
            self.assertEqual(result["status"], "BATCH_PREFLIGHT_READY")
            self.assertEqual(result["discovered_count"], 4)
            self.assertIs(result["execution_trigger_proven"], False)
            self.assertEqual(result["local_execution"], "NOT_PERFORMED")
            self.assertEqual(result["cas"], "NOT_PERFORMED")
            self.assertEqual(result["store_submission"], "NOT_PERFORMED")
            self.assertEqual(recheck.call_count, 2)
            sync.assert_not_called()
            artifact.assert_not_called()
            browser.assert_not_called()

    def test_registration_preflight_expired_artifact_blocks_without_side_effects(self):
        args = SimpleNamespace(
            provisioner_root=Path("C:/isolated-provisioner"),
            execution_origin="WINDOWS_TASK_SCHEDULER",
        )
        with (
            patch.object(runner, "check_prerequisites", return_value={}),
            patch.object(runner, "fetch_central", return_value=({}, "a" * 40, "blob")),
            patch.object(runner, "validate_queue", return_value=({}, [{}] * 4)),
            patch.object(runner, "recheck_central"),
            patch.object(runner.batch, "discover",
                         side_effect=runner.batch.BatchHold("HOLD_ARTIFACT_EXPIRED")),
            patch.object(runner, "sync_sources") as sync,
            patch.object(runner, "PartnerCenterDriver") as browser,
        ):
            with self.assertRaisesRegex(runner.batch.BatchHold, "HOLD_ARTIFACT_EXPIRED"):
                runner.preflight_only(args)
            sync.assert_not_called()
            browser.assert_not_called()

    def test_registration_script_uses_preflight_not_terminal_pass(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" /
                  "register_local_partner_center_batch.ps1").read_text(encoding="utf-8")
        self.assertIn("--preflight-only", script)
        self.assertIn("BATCH_PREFLIGHT_READY", script)
        self.assertIn("SCHEDULED_TASK_ALREADY_EXISTS_NO_OVERWRITE", script)
        self.assertNotIn("TERMINAL_4_OF_4_PASS_REQUIRED", script)
        self.assertIn("scheduled_36_min_trigger_proven = $false", script)

    def test_single_flight_lock_blocks_local_io_before_acquisition(self):
        # A competing runner must not even start source sync / ZIP download.
        # The old ordering performed both operations before state_lock().
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                state_dir=Path(directory),
                provisioner_root=Path(directory),
                execution_origin="MANUAL_WINDOWS_TERMINAL",
            )
            with (
                patch.object(runner, "check_prerequisites", return_value={}),
                patch.object(runner, "fetch_central", return_value=({}, "a" * 40, "blob")),
                patch.object(runner, "validate_queue", return_value=({}, [{}] * 4)),
                patch.object(runner, "recheck_central"),
                patch.object(runner.batch, "discover", return_value={"discovered_count": 4}),
                patch.object(runner.batch, "state_lock",
                             side_effect=runner.batch.BatchHold("BATCH_SINGLE_FLIGHT_LOCKED")),
                patch.object(runner, "sync_sources") as sync,
                patch.object(runner, "verify_artifact") as download,
                patch.object(runner, "PartnerCenterDriver") as browser,
            ):
                with self.assertRaisesRegex(
                        runner.batch.BatchHold, "BATCH_SINGLE_FLIGHT_LOCKED"):
                    runner.run_batch(args)
                sync.assert_not_called()
                download.assert_not_called()
                browser.assert_not_called()

    def test_expired_artifact_holds_before_source_sync_and_artifact_download(self):
        # Cloud preflight must reject stale Factory bytes before touching any
        # local snapshot, artifact ZIP, browser session, or GitHub CAS.
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                state_dir=Path(directory),
                provisioner_root=Path(directory),
                execution_origin="MANUAL_WINDOWS_TERMINAL",
            )
            with (
                patch.object(runner, "check_prerequisites", return_value={}),
                patch.object(runner, "fetch_central", return_value=({}, "a" * 40, "blob")),
                patch.object(runner, "validate_queue", return_value=({}, [])),
                patch.object(runner, "recheck_central"),
                patch.object(runner.batch, "discover",
                             side_effect=runner.batch.BatchHold("HOLD_ARTIFACT_EXPIRED")),
                patch.object(runner, "sync_sources") as sync,
                patch.object(runner, "verify_artifact") as download,
            ):
                with self.assertRaisesRegex(runner.batch.BatchHold, "HOLD_ARTIFACT_EXPIRED"):
                    runner.run_batch(args)
                sync.assert_not_called()
                download.assert_not_called()

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

    def test_forged_completed_manual_batch_is_rejected(self):
        state = {
            "batch_id": "batch-1",
            "central_head_sha": "a" * 40,
            "execution_origin": "MANUAL_WINDOWS_TERMINAL",
            "execution_trigger_proven": True,
            "processed_count": 4,
            "final_status": "MULTI_PRODUCT_IDENTITY_BATCH_PASS",
        }
        with self.assertRaisesRegex(runner.RunnerHold, "SCHEDULE_TRIGGER_NOT_PROVEN"):
            runner.validate_existing_state(
                state, {"batch_id": "batch-1"}, "a" * 40,
                "WINDOWS_TASK_SCHEDULER_MANUAL_START",
            )

    def test_completed_scheduled_batch_requires_host_proof(self):
        state = {
            "batch_id": "batch-1",
            "central_head_sha": "a" * 40,
            "execution_origin": "WINDOWS_TASK_SCHEDULER",
            "execution_trigger_proven": False,
            "processed_count": 4,
            "final_status": "MULTI_PRODUCT_IDENTITY_BATCH_PASS",
        }
        with self.assertRaisesRegex(runner.RunnerHold, "SCHEDULE_TRIGGER_NOT_PROVEN"):
            runner.validate_existing_state(
                state, {"batch_id": "batch-1"}, "a" * 40,
                "WINDOWS_TASK_SCHEDULER",
            )
        state["execution_trigger_proven"] = True
        self.assertTrue(runner.validate_existing_state(
            state, {"batch_id": "batch-1"}, "a" * 40,
            "WINDOWS_TASK_SCHEDULER",
        ))

    def test_terminal_partial_is_not_reclassified_as_success(self):
        state = {
            "batch_id": "batch-1",
            "central_head_sha": "a" * 40,
            "execution_origin": "MANUAL_WINDOWS_TERMINAL",
            "execution_trigger_proven": False,
            "processed_count": 4,
            "success_count": 4,
            "hold_count": 0,
            "final_status": "MULTI_PRODUCT_IDENTITY_BATCH_PARTIAL",
        }
        self.assertTrue(runner.validate_existing_state(
            state, {"batch_id": "batch-1"}, "a" * 40,
            "MANUAL_WINDOWS_TERMINAL",
        ))
        self.assertEqual(state["final_status"], "MULTI_PRODUCT_IDENTITY_BATCH_PARTIAL")

    def test_name_unavailable_advances_one_product_without_identity_cas(self):
        job = {
            "batch_index": 1, "state": "PROCESSING",
            "request_id": "app-example-" + "a" * 12,
            "slug": "example", "source_sha": "a" * 40,
            "identity_return_target": "products/example/store/approved-identity.json",
        }
        state = {
            "batch_id": "batch-1", "active_index": 1,
            "next_resume_index": 1, "products": [job],
            "processed_count": 0, "success_count": 0, "hold_count": 0,
            "batch_total": 4, "discovered_count": 4,
            "execution_trigger_proven": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            product_dir = Path(directory) / "products" / job["request_id"]
            result = runner.complete_name_unavailable(
                state, job, product_dir, "REUSED_EXACT_SNAPSHOT"
            )
            self.assertEqual(result["hold_count"], 1)
            self.assertEqual(result["success_count"], 0)
            self.assertEqual(result["next_resume_index"], 2)
            self.assertEqual(result["active_index"], None)
            self.assertTrue((product_dir / "result.json").is_file())
            self.assertTrue((Path(directory) / "batch-state.json").is_file())
            self.assertEqual(result["products"][0]["result"]["error_code"],
                             "HOLD_NAME_UNAVAILABLE")
            self.assertEqual(result["products"][0]["result"]["source_sync_status"],
                             "REUSED_EXACT_SNAPSHOT")

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
