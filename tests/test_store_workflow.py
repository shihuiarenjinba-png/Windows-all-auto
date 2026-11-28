from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
import shutil

from all_auto.store_workflow import (
    StoreWorkflowError,
    acquire_registered_package,
    build_store_workflow_report,
    write_unique_report,
)


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
                return SimpleNamespace(returncode=0, stdout="")

            result = acquire_registered_package(config, product="data-contract-auditor",
                                                cache_root=root / "cache", command_runner=runner)
            self.assertEqual(result["status"], "ACTIONS_ARTIFACT_FETCHED_AND_VERIFIED")
            self.assertEqual(result["artifact_id"], 77)
            self.assertEqual(result["run_id"], 88)
            self.assertEqual(result["sha256"], expected_sha)
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
