from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from all_auto.trusted_window_capture import (
    TrustedWindowCapture, TrustedWindowCaptureHold,
)


class Completed:
    def __init__(self, *, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TrustedWindowCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "capture.cs"
        self.source.write_text("fixed capture", encoding="utf-8")
        self.artifact = self.root / "product.exe"
        self.artifact.write_bytes(b"exact product")
        self.digest = sha256(self.artifact.read_bytes()).hexdigest()
        self.build = self.root / "build"
        helper_dir = self.build / sha256(self.source.read_bytes()).hexdigest()
        helper_dir.mkdir(parents=True)
        self.helper = helper_dir / "trusted-window-capture.exe"
        self.helper.write_bytes(b"fixed helper")

    def test_capture_is_artifact_process_and_root_bound(self):
        output = self.root / "review" / "window.png"

        def runner(command, **_kwargs):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"png")
            return Completed(stdout=json.dumps({
                "status": "WINDOW_CAPTURE_PASS", "process_id": 123,
                "width": 1000, "height": 700, "output": str(output),
            }))

        result = TrustedWindowCapture(
            source=self.source, build_root=self.build,
            platform_name="nt", runner=runner,
        ).capture(
            process_id=123, artifact_path=self.artifact,
            expected_sha256=self.digest, output_path=output,
            allowed_root=self.root / "review",
        )
        self.assertEqual(result["status"], "WINDOW_CAPTURE_PASS")
        self.assertEqual(result["sha256"], sha256(b"png").hexdigest())

    def test_artifact_drift_and_path_escape_hold(self):
        capture = TrustedWindowCapture(
            source=self.source, build_root=self.build,
            platform_name="nt", runner=lambda *_a, **_k: Completed(),
        )
        with self.assertRaisesRegex(TrustedWindowCaptureHold, "artifact binding"):
            capture.capture(
                process_id=123, artifact_path=self.artifact,
                expected_sha256="0" * 64,
                output_path=self.root / "review" / "x.png",
                allowed_root=self.root / "review",
            )
        with self.assertRaisesRegex(TrustedWindowCaptureHold, "escapes"):
            capture.capture(
                process_id=123, artifact_path=self.artifact,
                expected_sha256=self.digest,
                output_path=self.root / "outside.png",
                allowed_root=self.root / "review",
            )

    def test_non_windows_compile_holds(self):
        with self.assertRaisesRegex(TrustedWindowCaptureHold, "requires Windows"):
            TrustedWindowCapture(
                source=self.source, build_root=self.build,
                platform_name="posix",
            )._compile()


if __name__ == "__main__":
    unittest.main()
