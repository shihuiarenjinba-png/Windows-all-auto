"""Bounded Windows UI Automation actions for an already-started product.

The planner supplies only an action and validated parameters.  This module
never accepts a shell command, executable arguments, or a fallback click.
Every lookup is scoped to one exact process and requires exactly one match.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any


UIA_ACTIONS = {
    "UIA_FIND_WINDOW",
    "UIA_FIND_CONTROL",
    "UIA_INVOKE",
    "UIA_READ_TEXT",
    "UIA_SET_TEXT",
}
CONTROL_TYPES = {
    "Button", "Edit", "Text", "CheckBox", "ComboBox", "ListItem",
    "TabItem", "Document", "Group", "Pane",
}
SHA64 = re.compile(r"^[0-9a-f]{64}$")


class TrustedUIAHold(ValueError):
    pass


def _hold(reason: str) -> None:
    raise TrustedUIAHold("TRUSTED_UIA_HOLD: " + reason)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_uia_params(action: str, params: Any) -> dict[str, str]:
    if action not in UIA_ACTIONS:
        _hold("unknown action")
    if not isinstance(params, dict):
        _hold("params must be an object")
    if action == "UIA_FIND_WINDOW":
        if set(params) != {"title_contains"}:
            _hold("UIA_FIND_WINDOW requires title_contains only")
        title = params.get("title_contains")
        if not isinstance(title, str) or not 1 <= len(title) <= 120:
            _hold("invalid title_contains")
        return {"title_contains": title}

    allowed = {"name", "control_type"}
    if action == "UIA_SET_TEXT":
        allowed.add("value")
    if set(params) - allowed or "name" not in params:
        _hold(action + " requires name and optional control_type")
    name = params.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 120:
        _hold("invalid control name")
    control_type = params.get("control_type")
    if control_type is not None and control_type not in CONTROL_TYPES:
        _hold("unsupported control_type")
    result = {"name": name}
    if control_type is not None:
        result["control_type"] = control_type
    if action == "UIA_SET_TEXT":
        if "value" not in params:
            _hold("UIA_SET_TEXT requires value")
        value = params.get("value")
        if not isinstance(value, str) or len(value) > 4096:
            _hold("invalid UIA_SET_TEXT value")
        if control_type not in {None, "Edit"}:
            _hold("UIA_SET_TEXT control_type must be Edit")
        result["value"] = value
    return result


class TrustedUIAExecutor:
    """Compile and invoke the repository-owned fixed C# UIA helper."""

    def __init__(self, *, source: Path | None = None,
                 build_root: Path | None = None,
                 platform_name: str = os.name,
                 runner: Any = subprocess.run):
        repository = Path(__file__).resolve().parents[1]
        self.source = (source or repository / "scripts" / "trusted_uia_helper.cs").resolve()
        self.build_root = (build_root or repository / ".test-tmp" / "trusted-uia").resolve()
        self.platform_name = platform_name
        self.runner = runner

    def _compile(self) -> Path:
        if self.platform_name != "nt":
            _hold("Windows UI Automation requires Windows")
        if self.source.is_symlink() or not self.source.is_file():
            _hold("trusted helper source is missing or linked")
        source_sha = _sha256_file(self.source)
        output_dir = self.build_root / source_sha
        output = output_dir / "trusted-uia-helper.exe"
        if output.is_file() and not output.is_symlink():
            return output
        output_dir.mkdir(parents=True, exist_ok=True)
        windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
        framework = windows / "Microsoft.NET" / "Framework64" / "v4.0.30319"
        wpf = framework / "WPF"
        compiler = framework / "csc.exe"
        references = [
            wpf / "UIAutomationClient.dll",
            wpf / "UIAutomationTypes.dll",
            wpf / "WindowsBase.dll",
        ]
        if not compiler.is_file() or any(not item.is_file() for item in references):
            _hold("trusted Windows UIA compiler dependencies unavailable")
        command = [
            str(compiler), "/nologo", "/target:exe", "/optimize+",
            "/out:" + str(output),
            *("/reference:" + str(item) for item in references),
            str(self.source),
        ]
        completed = self.runner(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60, check=False,
        )
        if completed.returncode or not output.is_file():
            _hold("trusted UIA helper compilation failed")
        return output

    def execute(self, *, action: str, params: Any, process_id: int,
                artifact_path: Path, expected_sha256: str) -> dict[str, Any]:
        validated = validate_uia_params(action, params)
        artifact = artifact_path.resolve()
        if (artifact_path.is_symlink() or not artifact.is_file() or
                not SHA64.fullmatch(expected_sha256) or
                _sha256_file(artifact) != expected_sha256):
            _hold("artifact binding mismatch")
        if type(process_id) is not int or not 1 <= process_id <= 0x7FFFFFFF:
            _hold("invalid process_id")
        helper = self._compile()
        command = [
            str(helper), "--action", action,
            "--process-id", str(process_id),
            "--artifact", str(artifact),
            "--params-json", json.dumps(
                validated, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ),
        ]
        completed = self.runner(
            command, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, check=False,
        )
        if completed.returncode:
            _hold("UIA helper failed")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise TrustedUIAHold(
                "TRUSTED_UIA_HOLD: UIA helper returned invalid JSON"
            ) from exc
        if (not isinstance(result, dict) or result.get("status") != "UIA_PASS" or
                result.get("action") != action or
                result.get("process_id") != process_id):
            _hold("UIA helper result correlation mismatch")
        return result
