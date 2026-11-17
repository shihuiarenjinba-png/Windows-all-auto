"""Process/artifact-bound target-window screenshot capture.

The capture stays local until a caller explicitly marks it privacy-reviewed
and shareable through EvidenceStore.add_screenshot().
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from typing import Any


class TrustedWindowCaptureHold(ValueError):
    pass


def _hold(reason: str) -> None:
    raise TrustedWindowCaptureHold("TRUSTED_WINDOW_CAPTURE_HOLD: " + reason)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class TrustedWindowCapture:
    def __init__(self, *, source: Path | None = None,
                 build_root: Path | None = None,
                 platform_name: str = os.name,
                 runner: Any = subprocess.run):
        repository = Path(__file__).resolve().parents[1]
        self.source = (
            source or repository / "scripts" / "trusted_window_capture_helper.cs"
        ).resolve()
        self.build_root = (
            build_root or repository / ".test-tmp" / "trusted-window-capture"
        ).resolve()
        self.platform_name = platform_name
        self.runner = runner

    def _compile(self) -> Path:
        if self.platform_name != "nt":
            _hold("Windows window capture requires Windows")
        if self.source.is_symlink() or not self.source.is_file():
            _hold("trusted capture source is missing or linked")
        source_sha = _sha256_file(self.source)
        output_dir = self.build_root / source_sha
        output = output_dir / "trusted-window-capture.exe"
        if output.is_file() and not output.is_symlink():
            return output
        output_dir.mkdir(parents=True, exist_ok=True)
        windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
        framework = windows / "Microsoft.NET" / "Framework64" / "v4.0.30319"
        compiler = framework / "csc.exe"
        drawing = framework / "System.Drawing.dll"
        if not compiler.is_file() or not drawing.is_file():
            _hold("trusted screenshot compiler dependencies unavailable")
        completed = self.runner(
            [str(compiler), "/nologo", "/target:exe", "/optimize+",
             "/reference:" + str(drawing), "/out:" + str(output), str(self.source)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, check=False,
        )
        if completed.returncode or not output.is_file():
            _hold("trusted screenshot helper compilation failed")
        return output

    def capture(self, *, process_id: int, artifact_path: Path,
                expected_sha256: str, output_path: Path,
                allowed_root: Path) -> dict[str, Any]:
        artifact = artifact_path.resolve()
        root = allowed_root.resolve()
        output = output_path.resolve()
        if artifact_path.is_symlink() or not artifact.is_file():
            _hold("artifact missing or linked")
        if _sha256_file(artifact) != expected_sha256:
            _hold("artifact binding mismatch")
        if type(process_id) is not int or not 1 <= process_id <= 0x7FFFFFFF:
            _hold("invalid process_id")
        if output.suffix.lower() != ".png":
            _hold("PNG output required")
        if root == output or root not in output.parents:
            _hold("screenshot path escapes allowed root")
        if output_path.is_symlink() or root.is_symlink():
            _hold("symlink screenshot path is not allowed")
        output.parent.mkdir(parents=True, exist_ok=True)
        helper = self._compile()
        completed = self.runner(
            [str(helper), "--process-id", str(process_id), "--artifact", str(artifact),
             "--output", str(output)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
        if completed.returncode:
            _hold("trusted screenshot helper failed")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise TrustedWindowCaptureHold(
                "TRUSTED_WINDOW_CAPTURE_HOLD: helper returned invalid JSON"
            ) from exc
        if (not isinstance(result, dict) or
                result.get("status") != "WINDOW_CAPTURE_PASS" or
                result.get("process_id") != process_id or
                not output.is_file() or output.stat().st_size <= 0):
            _hold("capture result correlation mismatch")
        result["sha256"] = _sha256_file(output)
        result["output"] = str(output)
        return result
