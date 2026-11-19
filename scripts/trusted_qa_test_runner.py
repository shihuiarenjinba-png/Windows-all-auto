"""Deterministic implementations for locally trusted QA test IDs.

This module accepts no arbitrary command or argument list from an LLM.  The
supervisor invokes it only through the hash-pinned trusted catalog.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def artifact_hash(path: Path, expected: str) -> int:
    actual = _sha256(path)
    print("ARTIFACT_SHA256=" + actual)
    if actual != expected:
        print("ARTIFACT_HASH_MISMATCH", file=sys.stderr)
        return 2
    print("ARTIFACT_HASH_VERIFIED")
    return 0


def _manifest_binding(artifact: Path) -> dict[str, str] | None:
    for package_root in artifact.parents:
        manifest = package_root / "AppxManifest.xml"
        if not manifest.is_file():
            continue
        try:
            root = ET.parse(manifest).getroot()
        except (OSError, ET.ParseError) as exc:
            raise ValueError("invalid AppxManifest.xml") from exc
        identity = root.find("{*}Identity")
        if identity is None:
            raise ValueError("AppxManifest Identity is missing")
        relative = artifact.relative_to(package_root).as_posix().casefold()
        matches = []
        for application in root.findall(".//{*}Application"):
            executable = str(application.get("Executable", "")).replace("\\", "/")
            if executable.casefold() == relative:
                matches.append(application)
        if len(matches) != 1:
            raise ValueError("artifact is not uniquely bound to an Appx application")
        application_id = matches[0].get("Id", "")
        package_name = identity.get("Name", "")
        version = identity.get("Version", "")
        if (not package_name.replace(".", "").isalnum() or
                not application_id.replace(".", "").isalnum() or
                not version or any(ch not in "0123456789." for ch in version)):
            raise ValueError("Appx identity fields are invalid")
        return {
            "package_root": str(package_root.resolve()),
            "package_name": package_name,
            "version": version,
            "application_id": application_id,
        }
    return None


def _powershell_json(script: str, environment: dict[str, str]) -> object:
    powershell = os.environ.get(
        "WINDIR", r"C:\Windows"
    ) + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
    result = subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30, check=False, env={**os.environ, **environment},
    )
    if result.returncode:
        raise OSError("trusted package query failed with exit " + str(result.returncode))
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise OSError("trusted package query returned invalid JSON") from exc


def _registered_package(binding: dict[str, str]) -> dict[str, str]:
    script = (
        "$ErrorActionPreference='Stop';"
        "$p=@(Get-AppxPackage -Name $env:WAA_PACKAGE_NAME | "
        "Where-Object { $_.InstallLocation -eq $env:WAA_PACKAGE_ROOT });"
        "if($p.Count -ne 1){throw 'package registration mismatch'};"
        "$p[0] | Select-Object PackageFamilyName,InstallLocation,Version,Status | "
        "ConvertTo-Json -Compress"
    )
    value = _powershell_json(script, {
        "WAA_PACKAGE_NAME": binding["package_name"],
        "WAA_PACKAGE_ROOT": binding["package_root"],
    })
    if not isinstance(value, dict):
        raise OSError("trusted package query returned an invalid record")
    required = {"PackageFamilyName", "InstallLocation", "Version", "Status"}
    if set(value) != required:
        raise OSError("trusted package record fields are invalid")
    if (Path(str(value["InstallLocation"])).resolve() !=
            Path(binding["package_root"]).resolve() or
            str(value["Version"]) != binding["version"] or
            value["Status"] not in (0, "Ok")):
        raise OSError("registered package does not match the immutable artifact")
    family = str(value["PackageFamilyName"])
    if not family or any(not (ch.isalnum() or ch in "._") for ch in family):
        raise OSError("registered package family name is invalid")
    return {key: str(item) for key, item in value.items()}


def _process_ids(process_name: str, executable_path: Path) -> set[int]:
    script = (
        "$p=@(Get-Process -Name $env:WAA_PROCESS_NAME -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Path -eq $env:WAA_EXECUTABLE_PATH } | "
        "Select-Object -ExpandProperty Id);"
        "ConvertTo-Json -Compress -InputObject @($p)"
    )
    value = _powershell_json(script, {
        "WAA_PROCESS_NAME": process_name,
        "WAA_EXECUTABLE_PATH": str(executable_path.resolve()),
    })
    if not isinstance(value, list) or any(type(item) is not int for item in value):
        raise OSError("trusted process query returned invalid PIDs")
    return set(value)


def _stop_process(process_id: int) -> None:
    script = (
        "$ErrorActionPreference='Stop';"
        "$p=Get-Process -Id ([int]$env:WAA_PROCESS_ID) -ErrorAction Stop;"
        "$p | Stop-Process -Force -ErrorAction Stop;"
        "$p.WaitForExit()"
    )
    _powershell_json(
        script + "; ConvertTo-Json -Compress -InputObject @()",
        {"WAA_PROCESS_ID": str(process_id)},
    )


def _activate_registered_app(aumid: str) -> int:
    # Fixed COM contract copied from the repository's existing packaged-GUI QA.
    # The AUMID is derived from a verified package registration and manifest;
    # no command, argument, or code is accepted from the planner or product.
    script = r"""
$ErrorActionPreference='Stop'
$interop=@'
using System;
using System.Runtime.InteropServices;
namespace WindowsAllAutoQa {
  [ComImport, Guid("2e941141-7f97-4756-ba1d-9decde894a3d"),
   InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  public interface IApplicationActivationManager {
    [PreserveSig]
    int ActivateApplication(
      [MarshalAs(UnmanagedType.LPWStr)] string appUserModelId,
      [MarshalAs(UnmanagedType.LPWStr)] string arguments,
      uint options,
      out uint processId);
  }
  [ComImport, Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")]
  public class ApplicationActivationManager : IApplicationActivationManager {
    [System.Runtime.CompilerServices.MethodImpl(
      System.Runtime.CompilerServices.MethodImplOptions.InternalCall,
      MethodCodeType=System.Runtime.CompilerServices.MethodCodeType.Runtime),
     PreserveSig]
    public extern int ActivateApplication(
      [MarshalAs(UnmanagedType.LPWStr)] string appUserModelId,
      [MarshalAs(UnmanagedType.LPWStr)] string arguments,
      uint options,
      out uint processId);
  }
}
'@
Add-Type -TypeDefinition $interop -ErrorAction Stop
$manager=[WindowsAllAutoQa.IApplicationActivationManager](New-Object WindowsAllAutoQa.ApplicationActivationManager)
$pidOut=[uint32]0
$hr=$manager.ActivateApplication($env:WAA_AUMID, '', [uint32]2, [ref]$pidOut)
[pscustomobject]@{HResult=[int]$hr;ProcessId=[uint32]$pidOut} | ConvertTo-Json -Compress
"""
    value = _powershell_json(script, {"WAA_AUMID": aumid})
    if (not isinstance(value, dict) or set(value) != {"HResult", "ProcessId"} or
            type(value["HResult"]) is not int or type(value["ProcessId"]) is not int):
        raise OSError("trusted package activation returned an invalid record")
    if value["HResult"] != 0 or value["ProcessId"] <= 0:
        raise OSError(
            "trusted package activation failed with HRESULT " +
            str(value["HResult"])
        )
    return value["ProcessId"]


def _start_registered_package(artifact: Path, binding: dict[str, str],
                              observation_seconds: int) -> int:
    package = _registered_package(binding)
    before = _process_ids(artifact.stem, artifact)
    if before:
        print("PROCESS_START_HOLD: tested product is already running", file=sys.stderr)
        return 3
    aumid = package["PackageFamilyName"] + "!" + binding["application_id"]
    try:
        activated_process_id = _activate_registered_app(aumid)
    except OSError as exc:
        print("PACKAGE_ACTIVATION_FAILED:" + str(exc), file=sys.stderr)
        return 4
    deadline = time.monotonic() + 15
    process_id = None
    while time.monotonic() < deadline:
        current = _process_ids(artifact.stem, artifact) - before
        if activated_process_id in current and len(current) == 1:
            process_id = activated_process_id
            break
        if len(current) > 1:
            for unexpected_id in current:
                _stop_process(unexpected_id)
            print("PROCESS_START_HOLD: multiple product processes appeared", file=sys.stderr)
            return 5
        time.sleep(0.2)
    if process_id is None:
        print("PACKAGE_PROCESS_NOT_OBSERVED", file=sys.stderr)
        return 6
    print("PACKAGE_AUMID_VERIFIED=" + aumid)
    print("PROCESS_STARTED_PID=" + str(process_id))
    print("TARGET_STDOUT=UNAVAILABLE_PACKAGED_GUI")
    print("TARGET_STDERR=UNAVAILABLE_PACKAGED_GUI", file=sys.stderr)
    try:
        time.sleep(observation_seconds)
        if process_id not in _process_ids(artifact.stem, artifact):
            print("PROCESS_EXITED_DURING_OBSERVATION", file=sys.stderr)
            return 7
        print("PROCESS_SURVIVED_OBSERVATION_SECONDS=" + str(observation_seconds))
        return 0
    finally:
        if process_id in _process_ids(artifact.stem, artifact):
            _stop_process(process_id)
            print("PROCESS_TERMINATED_BY_TRUSTED_QA_HARNESS")


def process_start(path: Path, expected: str, *, observation_seconds: int = 5) -> int:
    if _sha256(path) != expected:
        print("ARTIFACT_HASH_MISMATCH", file=sys.stderr)
        return 2
    binding = _manifest_binding(path)
    if binding is not None:
        if os.name != "nt":
            print("PACKAGED_PROCESS_START_REQUIRES_WINDOWS", file=sys.stderr)
            return 3
        return _start_registered_package(path, binding, observation_seconds)
    command = [sys.executable, str(path)] if path.suffix.lower() == ".py" else [str(path)]
    try:
        process = subprocess.Popen(command, cwd=str(path.parent))
    except OSError as exc:
        print("PROCESS_START_FAILED:" + type(exc).__name__, file=sys.stderr)
        return 4
    print("PROCESS_STARTED_PID=" + str(process.pid))
    deadline = time.monotonic() + observation_seconds
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            return code
        time.sleep(0.1)
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    print("PROCESS_SURVIVED_OBSERVATION_SECONDS=" + str(observation_seconds))
    print("PROCESS_TERMINATED_BY_TRUSTED_QA_HARNESS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-id", required=True,
                        choices=("ARTIFACT_HASH", "PROCESS_START"))
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--expected-sha")
    args = parser.parse_args(argv)
    artifact = args.artifact.resolve()
    if not artifact.is_file() or args.artifact.is_symlink():
        raise SystemExit("TRUSTED_TEST_HOLD: artifact is missing or linked")
    if not args.expected_sha:
        raise SystemExit("TRUSTED_TEST_HOLD: expected SHA is required")
    if args.test_id == "ARTIFACT_HASH":
        return artifact_hash(artifact, args.expected_sha)
    return process_start(artifact, args.expected_sha)


if __name__ == "__main__":
    raise SystemExit(main())
