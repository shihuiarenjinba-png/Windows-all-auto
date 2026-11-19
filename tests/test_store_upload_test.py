from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from all_auto.github_artifact_intake import IntakeResult
from all_auto.store_upload_test import (
    StoreUploadLedger, StoreUploadTestHold, classify_automator_report,
    prepare_queue, validate_batch, verify_automator_checkout,
)


AUTOMATOR_SHA = "d3b8ed4ae7762a69d3fe2a90b64aa86ee938259b"
SOURCE_SHA = "a" * 40
ARCHIVE_SHA = "b" * 64
PACKAGE_SHA = "c" * 64
EXE_SHA = "d" * 64


def candidate(request="app-ready-001", store_id="9ABCDEFGHJK"):
    return {
        "request_id": request,
        "product_type": "APP",
        "artifact_source": {
            "repository": "example-owner/example-app",
            "artifact_id": 123,
            "artifact_name": "example-store-candidate",
            "workflow_run_id": 456,
            "source_sha": SOURCE_SHA,
            "archive_sha256": ARCHIVE_SHA,
            "package_name": "Example_1.0.0.0_x64.msix",
            "package_sha256": PACKAGE_SHA,
            "executable_sha256": EXE_SHA,
        },
        "identity": {
            "store_id": store_id,
            "name": "Example.App",
            "publisher": "CN=EXAMPLE",
            "version": "1.0.0.0",
        },
        "readiness": {
            "test_status": "TEST_PASS",
            "evidence_return_e2e_pass": True,
            "product_e2e_pass": True,
            "checker_verdict": "READY_CANDIDATE_NOT_CERTIFIED",
            "official_identity_reverified": True,
            "security_owner_confirmed": True,
            "listing_assets_ready": True,
        },
        "windows_automator_input": {
            "product_type": "app",
            "product_name": "Example",
            "app_summary": "Example app",
            "repository": "example-owner/example-app",
            "package_path": "",
            "images_dir": "",
            "store_product_id": store_id,
            "price_mode": "free",
            "price_value": "",
            "market_preset": "all_markets",
            "commercial_approval_required": False,
            "price_confirmed": True,
            "trial_confirmed": True,
            "commercial_approved_by": "owner",
            "fields": {},
            "trailers": [],
            "hero_art_path": "",
            "security_package_sha256": PACKAGE_SHA,
            "submission_kind": "update",
            "submission_route": "msix_pwa_app",
            "submission_route_source": "upstream",
            "package_type": "msix",
            "package_sha256": PACKAGE_SHA,
            "source_sha": SOURCE_SHA,
            "source_branch": "codex/example-ready",
            "identity_name": "Example.App",
            "identity_publisher": "CN=EXAMPLE",
            "package_version": "1.0.0.0",
            "checker_status": "READY_CANDIDATE_NOT_CERTIFIED",
            "human_local_qa_pass": True,
            "certification_gate": "READY_FOR_UPLOAD_TEST",
            "draft_id": "12",
        },
    }


def batch(*items):
    return {
        "schema_version": "store-upload-test-batch-v1",
        "automator": {
            "repository": "shihuiarenjinba-png/Windows-Automator",
            "branch": "codex/msix-commercial-contract-20261115",
            "commit_sha": AUTOMATOR_SHA,
        },
        "candidates": list(items or (candidate(),)),
    }


class Completed:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class StoreUploadTestTests(unittest.TestCase):
    def test_ready_candidate_validates(self):
        value = validate_batch(batch(candidate()))
        self.assertEqual(len(value["candidates"]), 1)

    def test_product_e2e_false_holds(self):
        item = candidate()
        item["readiness"]["product_e2e_pass"] = False
        with self.assertRaisesRegex(StoreUploadTestHold, "product_e2e_pass"):
            validate_batch(batch(item))

    def test_security_confirmation_must_bind_exact_package(self):
        item = candidate()
        item["windows_automator_input"]["security_package_sha256"] = "e" * 64
        with self.assertRaisesRegex(StoreUploadTestHold, "security confirmation"):
            validate_batch(batch(item))

    def test_local_package_path_is_not_trusted_from_github(self):
        item = candidate()
        item["windows_automator_input"]["package_path"] = r"C:\untrusted\package.msix"
        with self.assertRaisesRegex(StoreUploadTestHold, "package_path"):
            validate_batch(batch(item))

    def test_duplicate_store_id_holds(self):
        with self.assertRaisesRegex(StoreUploadTestHold, "duplicate Store ID"):
            validate_batch(batch(
                candidate("app-ready-001", "9ABCDEFGHJK"),
                candidate("app-ready-002", "9ABCDEFGHJK"),
            ))

    def test_verify_automator_checkout_is_exact_head_and_origin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "store_manager").mkdir()
            (root / "store_manager" / "cli.py").write_text("", encoding="utf-8")
            calls = []

            def runner(command, **_kwargs):
                calls.append(command)
                if command[-2:] == ["rev-parse", "HEAD"]:
                    return Completed(AUTOMATOR_SHA + "\n")
                return Completed(
                    "https://github.com/shihuiarenjinba-png/Windows-Automator.git\n"
                )

            verify_automator_checkout(root, batch(candidate())["automator"], runner=runner)
            self.assertEqual(len(calls), 2)

    def test_prepare_queue_injects_verified_local_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "verified.msix"
            executable = root / "product.exe"
            archive = root / "artifact.zip"
            manifest = root / "manifest.json"
            for path in (package, executable, archive, manifest):
                path.write_bytes(b"x")
            fake = IntakeResult(
                root=root,
                archive_path=archive,
                package_path=package,
                executable_path=executable,
                manifest_path=manifest,
                metadata={
                    "identity": {
                        "name": "Example.App",
                        "publisher": "CN=EXAMPLE",
                        "version": "1.0.0.0",
                    }
                },
            )

            def fetcher(**_kwargs):
                return fake

            workspace = root / "workspace"
            prepared = prepare_queue(batch(candidate()), workspace, fetcher=fetcher)
            self.assertEqual(
                prepared.queue[0]["package_path"], str(package.resolve())
            )
            self.assertEqual(prepared.queue[0]["package_sha256"], PACKAGE_SHA)

    def test_package_identity_drift_holds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("verified.msix", "product.exe", "artifact.zip", "manifest.json"):
                (root / name).write_bytes(b"x")
            fake = IntakeResult(
                root=root,
                archive_path=root / "artifact.zip",
                package_path=root / "verified.msix",
                executable_path=root / "product.exe",
                manifest_path=root / "manifest.json",
                metadata={
                    "identity": {
                        "name": "Wrong.App",
                        "publisher": "CN=EXAMPLE",
                        "version": "1.0.0.0",
                    }
                },
            )
            with self.assertRaisesRegex(StoreUploadTestHold, "Identity mismatch"):
                prepare_queue(
                    batch(candidate()), root / "workspace",
                    fetcher=lambda **_kwargs: fake,
                )


    def test_live_ledger_blocks_duplicate_after_draft_saved(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "upload-ledger.sqlite"
            item = candidate()
            with StoreUploadLedger(path) as ledger:
                ledger.begin_live([item])
                ledger.finish_live([item], {
                    "results": [{"status": "DRAFT_SAVED"}],
                })
                self.assertEqual(ledger.rows()[0]["status"], "DRAFT_SAVED")
                with self.assertRaisesRegex(StoreUploadTestHold, "prior remote outcome"):
                    ledger.begin_live([item])

    def test_live_ledger_marks_lost_result_unknown_and_blocks_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "upload-ledger.sqlite"
            item = candidate()
            with StoreUploadLedger(path) as ledger:
                ledger.begin_live([item])
                ledger.mark_unknown([item])
                self.assertEqual(ledger.rows()[0]["status"], "UNKNOWN")
                with self.assertRaisesRegex(StoreUploadTestHold, "prior remote outcome"):
                    ledger.begin_live([item])

    def test_live_ledger_allows_retry_after_explicit_hold_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "upload-ledger.sqlite"
            item = candidate()
            with StoreUploadLedger(path) as ledger:
                ledger.begin_live([item])
                ledger.finish_live([item], {
                    "results": [{"status": "HOLD"}],
                })
                self.assertEqual(ledger.rows()[0]["status"], "HOLD")
                ledger.begin_live([item])
                self.assertEqual(ledger.rows()[0]["status"], "LIVE_ATTEMPT_STARTED")

    def test_dry_run_requires_every_candidate_done(self):
        report = {
            "schema_version": 2,
            "summary": {"total": 2},
            "results": [
                {"product_name": "A", "status": "DONE", "details": {}},
                {"product_name": "B", "status": "DONE", "details": {}},
            ],
        }
        result = classify_automator_report(report, execution_mode="dry_run")
        self.assertEqual(result["status"], "UPLOAD_TEST_DRY_RUN_PASS")
        self.assertEqual(result["dry_run_done"], 2)

    def test_live_batch_aggregates_draft_saved(self):
        report = {
            "schema_version": 2,
            "summary": {"total": 2},
            "results": [
                {
                    "product_name": "A", "status": "DRAFT_SAVED",
                    "details": {"submitted": False, "certified": False, "published": False},
                },
                {
                    "product_name": "B", "status": "DRAFT_SAVED",
                    "details": {"submitted": False, "certified": False, "published": False},
                },
            ],
        }
        result = classify_automator_report(report, execution_mode="live")
        self.assertEqual(result["status"], "UPLOAD_TEST_DRAFT_SAVED")
        self.assertEqual(result["draft_saved"], 2)
        self.assertFalse(result["store_submission_allowed"])

    def test_unknown_live_result_never_auto_retries(self):
        report = {
            "schema_version": 2,
            "summary": {"total": 1},
            "results": [{"product_name": "A", "status": "UNKNOWN", "details": {}}],
        }
        result = classify_automator_report(report, execution_mode="live")
        self.assertEqual(result["status"], "UPLOAD_TEST_UNKNOWN_HOLD")
        self.assertFalse(result["automatic_retry_unknown"])

    def test_certification_or_publish_true_is_rejected(self):
        report = {
            "schema_version": 2,
            "summary": {"total": 1},
            "results": [{
                "product_name": "A", "status": "DRAFT_SAVED",
                "details": {"submitted": True, "published": False},
            }],
        }
        with self.assertRaisesRegex(StoreUploadTestHold, "prohibited"):
            classify_automator_report(report, execution_mode="live")


if __name__ == "__main__":
    unittest.main()
