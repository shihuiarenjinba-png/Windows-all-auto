from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from all_auto.trusted_uia import (
    TrustedUIAExecutor, TrustedUIAHold, validate_uia_params,
)


class Completed:
    def __init__(self, *, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TrustedUIATests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "helper.cs"
        self.source.write_text("fixed helper", encoding="utf-8")
        self.artifact = self.root / "product.exe"
        self.artifact.write_bytes(b"exact product")
        self.expected = sha256(self.artifact.read_bytes()).hexdigest()
        self.build = self.root / "build"
        helper_dir = self.build / sha256(self.source.read_bytes()).hexdigest()
        helper_dir.mkdir(parents=True)
        self.helper = helper_dir / "trusted-uia-helper.exe"
        self.helper.write_bytes(b"fixed helper executable")

    def test_parameter_contract_accepts_only_bounded_shapes(self):
        self.assertEqual(
            validate_uia_params("UIA_FIND_WINDOW", {"title_contains": "Folio AI"}),
            {"title_contains": "Folio AI"},
        )
        self.assertEqual(
            validate_uia_params("UIA_SET_TEXT", {
                "name": "記録名", "control_type": "Edit", "value": "synthetic",
            })["value"],
            "synthetic",
        )
        bad = (
            ("UIA_SET_TEXT", {"name": "x", "value": "x" * 4097}),
            ("UIA_SET_TEXT", {"name": "x", "control_type": "Button", "value": "x"}),
            ("UIA_INVOKE", {"name": "x", "command": "powershell"}),
            ("UNKNOWN", {}),
        )
        for action, params in bad:
            with self.subTest(action=action):
                with self.assertRaises(TrustedUIAHold):
                    validate_uia_params(action, params)

    def test_execution_is_process_and_artifact_correlated(self):
        commands = []

        def runner(command, **_kwargs):
            commands.append(command)
            return Completed(stdout=json.dumps({
                "status": "UIA_PASS", "action": "UIA_FIND_CONTROL",
                "process_id": 123, "observed": "検索",
            }))

        result = TrustedUIAExecutor(
            source=self.source, build_root=self.build, runner=runner,
            platform_name="nt",
        ).execute(
            action="UIA_FIND_CONTROL",
            params={"name": "検索", "control_type": "Button"},
            process_id=123, artifact_path=self.artifact,
            expected_sha256=self.expected,
        )
        self.assertEqual(result["observed"], "検索")
        command = commands[0]
        self.assertTrue(Path(command[0]).samefile(self.helper))
        self.assertNotIn("powershell", " ".join(command).lower())
        self.assertIn(str(self.artifact.resolve()), command)

    def test_artifact_drift_and_result_mismatch_hold(self):
        executor = TrustedUIAExecutor(
            source=self.source, build_root=self.build,
            platform_name="nt",
            runner=lambda *_args, **_kwargs: Completed(stdout=json.dumps({
                "status": "UIA_PASS", "action": "UIA_READ_TEXT",
                "process_id": 999,
            })),
        )
        with self.assertRaisesRegex(TrustedUIAHold, "artifact binding"):
            executor.execute(
                action="UIA_READ_TEXT", params={"name": "status"},
                process_id=123, artifact_path=self.artifact,
                expected_sha256="0" * 64,
            )
        with self.assertRaisesRegex(TrustedUIAHold, "correlation"):
            executor.execute(
                action="UIA_READ_TEXT", params={"name": "status"},
                process_id=123, artifact_path=self.artifact,
                expected_sha256=self.expected,
            )

    def test_non_windows_compile_holds(self):
        executor = TrustedUIAExecutor(
            source=self.source, build_root=self.build / "other",
            platform_name="posix",
        )
        with self.assertRaisesRegex(TrustedUIAHold, "requires Windows"):
            executor._compile()


if __name__ == "__main__":
    unittest.main()
