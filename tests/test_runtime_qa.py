from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from all_auto.runtime_qa import build_runtime_qa_report, run_profiled_source_driver

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT / "uploader" / "config"
PROFILE_ROOT = CONFIG_ROOT / "runtime_qa_profiles"


class RuntimeQaPlanTests(unittest.TestCase):
    def test_profiled_source_driver_collects_receipt_without_claiming_packaged_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            checkout = home / "Desktop" / "portfolio-audit" / "_task_worktrees" / "dca-userdata-output"
            script = checkout / "scripts" / "local_real_device_qa.py"
            script.parent.mkdir(parents=True)
            script.write_text("# synthetic driver fixture\\n", encoding="utf-8")
            profile_root = Path(temporary) / "profiles"
            profile_root.mkdir()
            (profile_root / "data-contract-auditor.json").write_text(json.dumps({
                "source_gui_driver": {
                    "enabled": True, "script": "scripts/local_real_device_qa.py",
                    "source_root_candidates": ["_task_worktrees/dca-userdata-output"]
                }
            }), encoding="utf-8")
            evidence = Path(temporary) / "evidence"

            def fake_run(command, **kwargs):
                target = Path(command[command.index("--evidence-dir") + 1])
                target.mkdir(parents=True)
                (target / "DCA_GUI_QA_RECEIPT.json").write_text(json.dumps({
                    "schema_version": "data-contract-auditor-gui-smoke/1",
                    "execution_type": "SOURCE_GUI_DRIVER_SYNTHETIC_DATA",
                    "status": "PASS", "checks": []
                }), encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("all_auto.runtime_qa.Path.home", return_value=home), \\
                 patch("all_auto.runtime_qa.platform.system", return_value="Windows"), \\
                 patch("all_auto.runtime_qa.subprocess.run", side_effect=fake_run):
                result = run_profiled_source_driver(product="data-contract-auditor",
                    profile_root=profile_root, evidence_root=evidence)
            self.assertEqual(result["status"], "SOURCE_GUI_DRIVER_PASS")
            self.assertFalse(result["packaged_runtime_proven"])
            self.assertFalse(result["visual_dpi_proven"])

    def test_product_key_profile_keeps_server_and_windows_10_11_lanes_distinct(self):
        report = build_runtime_qa_report(product="data-contract-auditor",
            config_root=CONFIG_ROOT, profile_root=PROFILE_ROOT, package=None)
        self.assertEqual(report["status"], "RUNTIME_QA_HOLD_PACKAGE_NOT_VERIFIED")
        self.assertFalse(report["qa_pass"])
        lanes = report["environment_lanes"]
        self.assertIn("windows_server_automation", lanes)
        self.assertIn("windows_10_11_interactive", lanes)
        self.assertNotEqual(lanes["windows_server_automation"]["status"],
                            lanes["windows_10_11_interactive"]["status"])
        self.assertTrue(all(check["status"] == "NOT_RUN" for check in report["checks"]))
        self.assertFalse(report["store_write_performed"])

    def test_exact_package_check_is_bound_to_profile_and_does_not_mark_runtime_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "DataContractSchemaDrift_1.0.0.0_x64.msix"
            package.write_bytes(b"fixture bytes")
            verified = SimpleNamespace(file_name=package.name, sha256="e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05", size=12)
            identity = {"Name": "OkinawaDesktopTools.DataContractAuditor",
                        "Publisher": "CN=46263F21-A700-41DB-8C9B-114C22FB82FC",
                        "Version": "1.0.0.0", "ProcessorArchitecture": "x64"}
            with patch("all_auto.runtime_qa.verify_file", return_value=verified), \
                 patch("all_auto.runtime_qa.read_msix_identity", return_value=identity), \
                 patch("all_auto.runtime_qa.read_msix_manifest_metadata", return_value={
                     "target_device_families": ["Windows.Desktop"], "signature_state": "UNSIGNED"}):
                report = build_runtime_qa_report(product="data-contract-auditor",
                    config_root=CONFIG_ROOT, profile_root=PROFILE_ROOT, package=package)
            self.assertEqual(report["package"]["status"], "EXACT_PACKAGE_SHA_AND_MANIFEST_VERIFIED")
            self.assertEqual(report["status"], "RUNTIME_QA_READY_TO_RUN")
            self.assertFalse(report["qa_pass"])
            self.assertTrue(all(item["status"] == "NOT_RUN" for item in report["checks"]))

    def test_profile_cannot_change_immutable_package_sha(self):
        with tempfile.TemporaryDirectory() as temporary:
            profile_root = Path(temporary)
            profile = json.loads((PROFILE_ROOT / "data-contract-auditor.json").read_text(encoding="utf-8"))
            profile["package"]["sha256"] = "0" * 64
            (profile_root / "data-contract-auditor.json").write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "immutable product package binding"):
                build_runtime_qa_report(product="data-contract-auditor", config_root=CONFIG_ROOT,
                                        profile_root=profile_root, package=None)


if __name__ == "__main__":
    unittest.main()
