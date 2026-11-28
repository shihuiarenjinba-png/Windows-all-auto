from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
import shutil
from unittest.mock import patch

from all_auto.store_workflow import (
    StoreWorkflowError,
    acquire_registered_package,
    build_store_workflow_report,
    write_store_report_with_fallback,
    write_unique_report,
)
from uploader.store_policy import build_product_decision_batch, load_shared_store_policy
from all_auto.artifact_archive import archive_verified_package


CONFIG_ROOT = Path(__file__).resolve().parents[1] / "uploader" / "config"


def make_exact_test_package(path: Path) -> str:
    manifest = '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="OkinawaDesktopTools.DataContractAuditor" Publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC" Version="1.0.0.0" ProcessorArchitecture="x64" /><Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.22621.0" /></Dependencies></Package>'''
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("AppxManifest.xml", manifest)
        package.writestr("payload.bin", b"synthetic fixed-source package")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StoreWorkflowTests(unittest.TestCase):
    def test_dca_plan_reuses_fixed_binding_and_keeps_writes_out_of_scope(self):
        report = build_store_workflow_report(product="data-contract-auditor", config_root=CONFIG_ROOT)
        self.assertEqual(report["binding"]["product_id"], "9PDL4ZWSB45P")
        self.assertEqual(report["binding"]["submission_id"], "1152921505702212222")
        self.assertEqual(report["mode"], "DRY_RUN")
        self.assertFalse(report["partner_center"]["writes_performed"])
        self.assertEqual(report["write_scope"]["allowed_by_this_run"], [])
        self.assertIn("pricing/market changes", report["write_scope"]["prohibited"])
        self.assertIn("AWAITING_OWNER_INPUT", report["sections"]["pricing_availability"])
        self.assertEqual(report["status"], "INPUTS_REQUIRED")
        self.assertEqual(report["device_family_plan"]["recommended_store_device_families"],
                         ["Windows 10/11 Desktop"])
        self.assertEqual(report["device_family_plan"]["status"], "PENDING_OWNER_APPROVAL")

    def test_dca_profile_sha_conflict_is_reported_and_not_reconciled(self):
        report = build_store_workflow_report(product="data-contract-auditor", config_root=CONFIG_ROOT)
        self.assertEqual(report["source_package_provenance"]["status"], "MISMATCH")
        self.assertEqual(report["source_package_provenance"]["job_expected_sha256"],
                         "e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05")
        self.assertEqual(report["source_package_provenance"]["formal_package_sha256"],
                         "4b373d2bc54ecbd3efa0a77a94005007777e66d641fa3908f523ac69fcd46984")
        self.assertEqual(report["source_package_provenance"]["historical_registration"]["gate_registration_commit"],
                         "2956574fc1a3cf80b60281dfc8e6914cc8084383")
        self.assertEqual(report["source_package_provenance"]["historical_registration"]["product_profile_registration_commit"],
                         "0c73a746bcec9ded702567768d5c04f4240a12a9")
        self.assertEqual(report["source_package_provenance"]["current_artifact_candidate"]["artifact_id"],
                         15005358857)
        self.assertFalse(report["source_package_provenance"]["proposal"]["owner_approval_recorded"])
        self.assertIn("source_package_provenance", {x["key"] for x in report["missing_or_unverified"]})
        self.assertIn("source_package_provenance", {x["key"] for x in report["owner_decisions"]})
        self.assertEqual(len(report["owner_decision_candidates"]), 14)

    def test_shared_sales_policy_separates_cross_product_rules_from_product_candidates(self):
        report = build_store_workflow_report(product="data-contract-auditor", config_root=CONFIG_ROOT)
        self.assertEqual(report["shared_store_policy"]["policy_id"], "windows-store-submission-common")
        self.assertEqual(report["shared_store_policy"]["candidate_defaults"], "NONE")
        self.assertEqual(report["shared_store_policy"]["section_dependencies"],
                         {"store_listings": ["packages"]})
        batch = {item["key"]: item for item in report["owner_decision_batch"]}
        self.assertTrue({"device_families", "category", "price_model", "price", "markets",
                         "languages", "descriptions", "images", "privacy_declarations",
                         "age_rating", "commercial_license", "publication_mode",
                         "automatic_execution_scope"}.issubset(batch))
        self.assertEqual(batch["price"]["value"], None)
        self.assertEqual(batch["price"]["status"], "OWNER_DECISION_REQUIRED")
        self.assertEqual(batch["commercial_license"]["status"], "OWNER_DECISION_REQUIRED")
        self.assertEqual(batch["images"]["status"], "OWNER_DECISION_REQUIRED")

    def test_shared_policy_reuses_only_digest_bound_product_and_section_approval(self):
        profile = {"product_id": "p-1", "submission_id": "s-1",
                   "approved_store_sections": {"properties": {
                       "fields": [{"key": "category", "value": "productivity"}],
                       "approval": {"approved": True, "product_id": "p-1", "submission_id": "s-1",
                                    "sections": ["properties"], "approval_ref": "a-1",
                                    "approved_by": "owner", "approved_at": "2026-11-28",
                                    "approved_values_digest": hashlib.sha256(
                                        json.dumps({"category": "productivity"}, sort_keys=True,
                                                   separators=(",", ":")).encode("utf-8")).hexdigest()}}}}
        policy = load_shared_store_policy()
        approved = {item["key"]: item for item in build_product_decision_batch(policy, profile)}
        self.assertEqual(approved["category"]["status"], "APPROVED_REUSED")
        self.assertEqual(approved["category"]["value"], {"category": "productivity"})
        self.assertEqual(approved["price"]["status"], "EVIDENCE_REQUIRED")

        profile["product_id"] = "other-product"
        mismatched_target = {item["key"]: item for item in build_product_decision_batch(policy, profile)}
        self.assertNotEqual(mismatched_target["category"]["status"], "APPROVED_REUSED")
        self.assertIsNone(mismatched_target["category"]["value"])

        profile["product_id"] = "p-1"
        profile["approved_store_sections"]["properties"]["fields"][0]["value"] = "games"
        changed_value = {item["key"]: item for item in build_product_decision_batch(policy, profile)}
        self.assertNotEqual(changed_value["category"]["status"], "APPROVED_REUSED")

    def test_fixed_dca_binding_cannot_be_changed_in_a_copied_registry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
            config["submission_id"] = "1152921505702212000"
            (root / "data-contract-auditor.job.json").write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(StoreWorkflowError, "fixed DCA binding mismatch"):
                build_store_workflow_report(product="data-contract-auditor", config_root=root)

    def test_write_modes_are_rejected_before_any_partner_center_action(self):
        for mode in ("DRAFT_WRITE", "CERTIFICATION", "PUBLISH"):
            with self.subTest(mode=mode), self.assertRaisesRegex(StoreWorkflowError, "outside this orchestrator"):
                build_store_workflow_report(product="data-contract-auditor", config_root=CONFIG_ROOT, mode=mode)

    def test_missing_package_and_draft_remain_explicitly_unverified(self):
        report = build_store_workflow_report(product="data-contract-auditor", config_root=CONFIG_ROOT)
        self.assertEqual(report["package"]["status"], "PACKAGE_PATH_NOT_PROVIDED")
        self.assertEqual(report["partner_center"]["status"], "NOT_CONNECTED")
        keys = {item["key"] for item in report["missing_or_unverified"]}
        self.assertTrue({"package", "partner_center_draft", "pricing_and_markets",
                         "compliance_and_commercial", "packaged_runtime_qa"}.issubset(keys))

    def test_source_head_or_origin_mismatch_is_not_reconciled_by_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("Data Contract Auditor", encoding="utf-8")
            report = build_store_workflow_report(product="data-contract-auditor", config_root=CONFIG_ROOT,
                                                 source_root=root)
            self.assertEqual(report["source"]["status"], "SOURCE_MISMATCH")
            self.assertFalse(report["source"]["repository_matches"])
            self.assertFalse(report["source"]["head_matches"])

    def test_report_writer_never_overwrites_existing_evidence(self):
        report = build_store_workflow_report(product="data-contract-auditor", config_root=CONFIG_ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            path = write_unique_report(report, Path(temporary))
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                write_unique_report(report, Path(temporary))
            self.assertEqual(path.read_bytes(), original)

    def test_report_writer_falls_back_after_access_denied_without_retrying_primary(self):
        report = {"product_key": "data-contract-auditor", "created_at_utc": "2026-11-28T00:00:00+00:00",
                  "run_id": "fallback-test"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = root / "protected"
            unavailable = root / "missing-app-container"
            fallback = root / "user-writable"
            real_writer = write_unique_report
            calls = []

            def deny_primary(value, destination):
                calls.append(destination)
                if destination == primary:
                    raise PermissionError("simulated protected output directory")
                if destination == unavailable:
                    raise FileNotFoundError("simulated transient app-container path")
                return real_writer(value, destination)

            with patch("all_auto.store_workflow.write_unique_report", side_effect=deny_primary):
                result = write_store_report_with_fallback(report, primary, [unavailable, fallback])
            self.assertEqual(result.parent, fallback)
            self.assertTrue(result.is_file())
            self.assertEqual(calls, [primary, unavailable, fallback])

    def test_registered_source_fetch_is_pinned_hashed_and_cached_once(self):
        config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_source = root / "source.msix"
            digest = make_exact_test_package(package_source)
            config.update({"path": "store-output/DataContractSchemaDrift_1.0.0.0_x64.msix",
                           "expected_sha256": digest, "artifact_id": None,
                           "artifact_name": None, "artifact_run_id": None})
            calls = []

            def downloader(repository, ref, source_path, token, target, *, max_bytes):
                calls.append((repository, ref, source_path, token, max_bytes))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package_source.read_bytes())

            first = acquire_registered_package(config, product="data-contract-auditor",
                                               cache_root=root / "cache", token="mock-token",
                                               downloader=downloader)
            second = acquire_registered_package(config, product="data-contract-auditor",
                                                cache_root=root / "cache", token="mock-token",
                                                downloader=downloader)
            self.assertEqual(first["status"], "PINNED_SOURCE_FETCHED_AND_VERIFIED")
            self.assertEqual(second["status"], "CACHE_HIT_VERIFIED")
            self.assertEqual(first["sha256"], digest)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][:4], (config["repository"], config["ref"], config["path"], "mock-token"))

    def test_product_key_discovers_one_exact_package_in_registered_runtime_root(self):
        config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "runtime" / Path(config["path"]).name
            source.parent.mkdir(parents=True)
            digest = make_exact_test_package(source)
            config["expected_sha256"] = digest
            result = acquire_registered_package(
                config, product="data-contract-auditor", cache_root=root / "cache",
                search_roots=[root / "runtime"],
                downloader=lambda *_args, **_kwargs: self.fail("exact local file should be reused"))
            self.assertEqual(result["status"], "LOCAL_EXACT_FILE_VERIFIED")
            self.assertTrue(Path(result["path"]).samefile(source))
            self.assertEqual(result["sha256"], digest)

    def test_registered_package_is_rehydrated_from_immutable_archive_when_cache_is_empty(self):
        config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            source = root / "source.msix"
            digest = make_exact_test_package(source)
            config.update({"expected_sha256": digest, "artifact_id": None,
                           "artifact_name": None, "artifact_run_id": None,
                           "path": source.name})
            archive_root = root / "durable-package-archive"
            archive_verified_package(config, source, archive_root)
            result = acquire_registered_package(
                config, product="data-contract-auditor", cache_root=root / "cache",
                archive_root=archive_root,
                downloader=lambda *_args, **_kwargs: self.fail("archive must be reused before network"))
            self.assertEqual(result["status"], "LOCAL_ARCHIVE_REHYDRATED_AND_VERIFIED")
            self.assertEqual(result["sha256"], digest)
            self.assertTrue(Path(result["path"]).is_file())
            self.assertTrue(Path(result["archive_path"]).is_file())

    def test_archive_receipt_wrong_submission_cannot_rehydrate_package(self):
        config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            source = root / "source.msix"
            digest = make_exact_test_package(source)
            config.update({"expected_sha256": digest, "artifact_id": None,
                           "artifact_name": None, "artifact_run_id": None,
                           "path": source.name})
            archive_root = root / "durable-package-archive"
            archive_verified_package(config, source, archive_root)
            receipt = next(archive_root.rglob("*.receipt.json"))
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload["submission_id"] = "wrong-draft"
            receipt.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(StoreWorkflowError, "receipt does not match"):
                acquire_registered_package(config, product="data-contract-auditor",
                                           cache_root=root / "cache", archive_root=archive_root,
                                           downloader=lambda *_args, **_kwargs: self.fail("must hold"))

    def test_github_actions_artifact_id_is_pinned_downloaded_and_manifest_verified(self):
        config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.msix"
            expected_sha = make_exact_test_package(source)
            config.update({"path": "store-output/DataContractSchemaDrift_1.0.0.0_x64.msix",
                           "expected_sha256": expected_sha, "artifact_id": 77,
                           "artifact_name": "dca-msix-qa", "artifact_run_id": 88,
                           "source_sha": "a" * 40, "ref": "a" * 40})
            calls = []

            def runner(args, **kwargs):
                calls.append(args)
                if args[1] == "api" and "/actions/artifacts/" in args[2]:
                    data = {"id": 77, "name": "dca-msix-qa", "expired": False,
                            "size_in_bytes": 1234, "digest": "sha256:" + "b" * 64,
                            "workflow_run": {"id": 88}}
                    return SimpleNamespace(returncode=0, stdout=json.dumps(data))
                if args[1] == "api" and "/actions/runs/" in args[2]:
                    return SimpleNamespace(returncode=0, stdout=json.dumps(
                        {"conclusion": "success", "head_sha": "a" * 40, "name": "QA MSIX"}))
                target = Path(args[args.index("--dir") + 1])
                target.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target / Path(config["path"]).name)
                evidence = {
                    "BUILD_EVIDENCE.json": {
                        "store_id": config["product_id"], "source_sha": "a" * 40,
                        "msix_filename": Path(config["path"]).name,
                        "msix_sha256": expected_sha, "msix_version": config["version"]},
                    "MSIX_VERIFICATION.json": {
                        "valid": True, "store_id": config["product_id"],
                        "version": config["version"], "msix": {
                            "filename": Path(config["path"]).name, "sha256": expected_sha}},
                    "STORE_PREFLIGHT.json": {
                        "ready": True, "store_id": config["product_id"],
                        "version_to_build": config["version"]},
                }
                for name, payload in evidence.items():
                    (target / name).write_text(json.dumps(payload), encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="")

            result = acquire_registered_package(config, product="data-contract-auditor",
                                                cache_root=root / "cache", command_runner=runner)
            self.assertEqual(result["status"], "ACTIONS_ARTIFACT_FETCHED_AND_VERIFIED")
            self.assertEqual(result["artifact_id"], 77)
            self.assertEqual(result["run_id"], 88)
            self.assertEqual(result["sha256"], expected_sha)
            self.assertEqual(result["source_sha"], "a" * 40)
            self.assertEqual(len(calls), 3)
            self.assertTrue(Path(result["local_path"]).is_file())

    def test_package_cache_duplicates_fail_closed(self):
        config = json.loads((CONFIG_ROOT / "data-contract-auditor.job.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "cache" / "data-contract-auditor"
            for folder in ("first", "second"):
                target = root / folder / Path(config["path"]).name
                target.parent.mkdir(parents=True)
                target.write_bytes(b"not-used-because-duplicate-candidates-stop-first")
            with self.assertRaisesRegex(StoreWorkflowError, "multiple exact package cache candidates"):
                acquire_registered_package(config, product="data-contract-auditor", cache_root=root.parent,
                                           downloader=lambda *_args, **_kwargs: self.fail("must not download"))


if __name__ == "__main__":
    unittest.main()
