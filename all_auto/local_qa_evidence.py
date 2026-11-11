"""Durable, privacy-filtered evidence and GitHub readback gate for local QA.

This module does not decide how a product is fixed and never installs, signs or
submits a package.  It makes one narrow promise: a local test cannot become an
E2E pass until its evidence was durably written, sanitized, returned to GitHub,
downloaded again, and correlated to the exact request and source commit.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Iterable
import uuid


SCHEMA = "local-qa-evidence-v1"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
REQUEST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{3,127}$")
SOURCE_REPOSITORY = re.compile(
    r"^(?:https://github\.com/)?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
GITHUB_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SAFE_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{2,199}$")
MAX_TEXT_BYTES = 10 * 1024 * 1024
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
MAX_ENVELOPE_BYTES = 25 * 1024 * 1024
FACTORY_ROUTES = {
    "APP": "shihuiarenjinba-png/AI-App-Factory",
    "GAME": "shihuiarenjinba-png/AI-Game-Factory",
    "GAME_3D": "shihuiarenjinba-png/3d-game-factory",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for piece in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix="." + path.name + ".",
                                     suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def atomic_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2,
                                  sort_keys=True).encode("utf-8") + b"\n")


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab", buffering=0) as stream:
        stream.write(canonical(value) + b"\n")
        os.fsync(stream.fileno())


def _validate_job(job: dict[str, Any]) -> dict[str, Any]:
    required = ("request_id", "product_type", "source_repository", "source_branch",
                "source_sha", "artifact_sha256", "test_suite_version")
    if not isinstance(job, dict) or any(not isinstance(job.get(k), str) for k in required):
        raise ValueError("LOCAL_QA_HOLD: incomplete evidence job")
    if not REQUEST.fullmatch(job["request_id"]):
        raise ValueError("LOCAL_QA_HOLD: invalid request_id")
    if job["product_type"] not in {"APP", "GAME", "GAME_3D"}:
        raise ValueError("LOCAL_QA_HOLD: invalid product_type")
    if not SOURCE_REPOSITORY.fullmatch(job["source_repository"]):
        raise ValueError("LOCAL_QA_HOLD: invalid source_repository")
    if not SAFE_BRANCH.fullmatch(job["source_branch"]):
        raise ValueError("LOCAL_QA_HOLD: invalid source_branch")
    if not SHA40.fullmatch(job["source_sha"]):
        raise ValueError("LOCAL_QA_HOLD: invalid source_sha")
    if not SHA64.fullmatch(job["artifact_sha256"]):
        raise ValueError("LOCAL_QA_HOLD: invalid artifact_sha256")
    safe = {key: job[key] for key in required}
    for key in ("github_actions_run_id", "github_artifact_id", "slug"):
        if key in job:
            if key.endswith("_id") and type(job[key]) is not int:
                raise ValueError("LOCAL_QA_HOLD: invalid " + key)
            if key == "slug" and not isinstance(job[key], str):
                raise ValueError("LOCAL_QA_HOLD: invalid slug")
            safe[key] = job[key]
    return safe


class Redactor:
    """Conservative text redaction. Binary images require an explicit safe flag."""

    _rules = (
        (re.compile(r"(?i)(authorization\s*:\s*(?:bearer|token)\s+)[^\s\"']+"), r"\1[REDACTED]"),
        (re.compile(r"(?i)\b(gh[opusr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), "[REDACTED_GITHUB_TOKEN]"),
        (re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)\s*[:=]\s*([^\s,;]+)"), r"\1=[REDACTED]"),
        (re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\r\n]+"), r"C:\\Users\\[REDACTED]"),
        (re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
        (re.compile(r"(?i)\b(cookie|set-cookie)\s*:\s*[^\r\n]+"), r"\1: [REDACTED]"),
    )
    _leaks = (
        re.compile(r"(?i)\b(?:gh[opusr]_|github_pat_)[A-Za-z0-9_]{12,}"),
        re.compile(r"(?i)\b(?:password|client[_-]?secret)\s*[:=]\s*(?!\[REDACTED\])\S+"),
        re.compile(r"(?i)authorization\s*:\s*bearer\s+(?!\[REDACTED\])\S+"),
    )

    def text(self, value: str) -> tuple[str, int]:
        count = 0
        for pattern, replacement in self._rules:
            value, changed = pattern.subn(replacement, value)
            count += changed
        return value, count

    def clean(self, value: Any) -> tuple[Any, int]:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            result, total = [], 0
            for item in value:
                cleaned, count = self.clean(item)
                result.append(cleaned)
                total += count
            return result, total
        if isinstance(value, dict):
            result, total = {}, 0
            for key, item in value.items():
                cleaned, count = self.clean(item)
                result[str(key)] = cleaned
                total += count
            return result, total
        return value, 0

    def leak_free(self, value: bytes) -> bool:
        text = value.decode("utf-8", errors="ignore")
        return not any(pattern.search(text) for pattern in self._leaks)


@dataclass(frozen=True)
class RunResult:
    run_id: str
    run_directory: Path
    status: str
    exit_code: int | None
    timed_out: bool
    e2e_pass: bool


class EvidenceStore:
    def __init__(self, root: Path, *, redactor: Redactor | None = None):
        self.root = root.resolve()
        if root.is_symlink():
            raise ValueError("LOCAL_QA_HOLD: evidence root may not be a symlink")
        self.runs = self.root / "runs"
        self.queue = self.root / "retry-queue"
        self.acks = self.root / "github-acks"
        self.jobs = self.root / "job-index"
        self.locks = self.root / "run-locks"
        for folder in (self.root, self.runs, self.queue, self.acks, self.jobs, self.locks):
            folder.mkdir(parents=True, exist_ok=True)
        self.redactor = redactor or Redactor()
        machine = self.root / "machine-id"
        if not machine.exists():
            atomic_write(machine, (uuid.uuid4().hex + "\n").encode("ascii"))
        self.machine_id = machine.read_text(encoding="ascii").strip()

    def _run_path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}", run_id):
            raise ValueError("invalid run_id")
        return self.runs / run_id

    def start(self, job: dict[str, Any], command: list[str], *,
              expected: dict[str, Any], gui_test: bool) -> tuple[str, Path]:
        job = _validate_job(job)
        if not command or not all(isinstance(piece, str) and piece for piece in command):
            raise ValueError("LOCAL_QA_HOLD: empty test command")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fingerprint = sha256_bytes(canonical({"job": job, "command": command,
                                              "nonce": uuid.uuid4().hex}))[:16]
        run_id = stamp + "-" + fingerprint
        request_key = sha256_bytes(job["request_id"].encode("utf-8"))
        job_key = sha256_bytes(canonical({"job": job, "machine_id": self.machine_id}))
        self._register_request(request_key, job)
        lock_path = self.locks / (job_key + ".lock")
        try:
            lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise ValueError("LOCAL_QA_HOLD: identical job is already running") from exc
        try:
            os.write(lock_descriptor, (run_id + "\n").encode("ascii"))
            os.fsync(lock_descriptor)
        finally:
            os.close(lock_descriptor)
        folder = self._run_path(run_id)
        try:
            folder.mkdir(parents=False)
        except BaseException:
            lock_path.unlink(missing_ok=True)
            raise
        state = {
            "schema_version": SCHEMA, "run_id": run_id, "state": "RUNNING",
            "started_at_utc": utc_now(), "finished_at_utc": None,
            "job": job, "command": command, "expected": expected,
            "job_key": job_key,
            "gui_test": bool(gui_test), "e2e_pass": False,
            "github_return": {"status": "NOT_ATTEMPTED", "readback_verified": False},
        }
        try:
            atomic_json(folder / "state.json", state)
            append_jsonl(folder / "journal.jsonl", {"at": utc_now(), "event": "RUN_STARTED"})
        except BaseException:
            lock_path.unlink(missing_ok=True)
            raise
        return run_id, folder

    def _register_request(self, request_key: str, job: dict[str, Any]) -> None:
        path = self.jobs / (request_key + ".json")
        immutable = {key: job[key] for key in (
            "request_id", "product_type", "source_repository", "source_branch",
            "source_sha", "artifact_sha256")}
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            old = json.loads(path.read_text(encoding="utf-8"))
            if old != immutable:
                raise ValueError(
                    "LOCAL_QA_CONFLICT: request_id reused with changed source or artifact")
            return
        try:
            raw = json.dumps(immutable, ensure_ascii=False, sort_keys=True,
                             indent=2).encode("utf-8") + b"\n"
            os.write(descriptor, raw)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(path.parent)

    def record_ui_action(self, run_id: str, *, action: str, target: str,
                         result: str, details: dict[str, Any] | None = None) -> None:
        folder = self._run_path(run_id)
        state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
        if not state.get("gui_test"):
            raise ValueError("UI action supplied for a non-GUI test")
        append_jsonl(folder / "uia-actions.jsonl", {
            "at": utc_now(), "action": action, "target": target,
            "result": result, "details": details or {},
        })

    def add_screenshot(self, run_id: str, source: Path, *, label: str,
                       privacy_reviewed_shareable: bool = False) -> Path:
        folder = self._run_path(run_id)
        if source.is_symlink() or not source.is_file():
            raise ValueError("screenshot missing or linked")
        if not 0 < source.stat().st_size <= MAX_SCREENSHOT_BYTES:
            raise ValueError("screenshot exceeds safe size")
        suffix = source.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("unsupported screenshot format")
        index = sum(1 for _ in (folder / "screenshots").glob("*")) if (folder / "screenshots").exists() else 0
        destination = folder / "screenshots" / f"{index:03d}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as inp:
            atomic_write(destination, inp.read())
        append_jsonl(folder / "screenshot-index.jsonl", {
            "at": utc_now(), "file": destination.name, "label": label,
            "sha256": sha256_file(destination),
            "privacy_reviewed_shareable": bool(privacy_reviewed_shareable),
        })
        return destination

    def _update_state(self, folder: Path, **changes: Any) -> dict[str, Any]:
        state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
        state.update(changes)
        atomic_json(folder / "state.json", state)
        return state

    def recover_interrupted(self) -> list[str]:
        recovered = []
        for state_path in sorted(self.runs.glob("*/state.json")):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if state.get("state") != "RUNNING":
                continue
            folder = state_path.parent
            state.update({"state": "INTERRUPTED_RESTART", "finished_at_utc": utc_now(),
                          "e2e_pass": False, "exit_code": None, "timed_out": False,
                          "failure_reason": "PROCESS_OR_PC_RESTARTED_BEFORE_FINALIZATION"})
            atomic_json(state_path, state)
            append_jsonl(folder / "journal.jsonl", {
                "at": utc_now(), "event": "RECOVERED_INTERRUPTED_RUN"})
            try:
                self._finalize(folder, state, event_log_status="UNAVAILABLE_PROCESS_RESTART",
                               event_log_error="collection did not complete before restart")
            finally:
                self._release_job_lock(state)
            recovered.append(state["run_id"])
        return recovered

    def prune_verified(self, *, retention_days: int = 30,
                       max_total_bytes: int = 5 * 1024 * 1024 * 1024) -> dict[str, int]:
        """Delete only acknowledged, non-queued runs beyond retention/quota."""
        if not 1 <= retention_days <= 3650 or max_total_bytes < 1024 * 1024:
            raise ValueError("invalid evidence retention policy")
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        records = []
        total = 0
        for folder in sorted(self.runs.iterdir()):
            if folder.is_symlink() or not folder.is_dir():
                continue
            size = sum(path.stat().st_size for path in folder.rglob("*")
                       if path.is_file() and not path.is_symlink())
            total += size
            try:
                state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
                finished = datetime.fromisoformat(
                    state["finished_at_utc"].replace("Z", "+00:00"))
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            acknowledged = (self.acks / (folder.name + ".json")).is_file()
            queued = (self.queue / (folder.name + ".json")).exists()
            records.append((finished, folder, size, acknowledged and not queued))
        deleted = 0
        freed = 0
        for finished, folder, size, eligible in sorted(records, key=lambda item: item[0]):
            if not eligible or (finished >= cutoff and total <= max_total_bytes):
                continue
            resolved = folder.resolve()
            if resolved.parent != self.runs:
                raise ValueError("unsafe evidence retention target")
            shutil.rmtree(resolved)
            total -= size
            freed += size
            deleted += 1
        return {"deleted_runs": deleted, "freed_bytes": freed,
                "remaining_bytes": total}

    @staticmethod
    def _drain(pipe: Any, path: Path, observation: dict[str, Any]) -> None:
        written = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb", buffering=0) as output:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                if written < MAX_TEXT_BYTES:
                    accepted = chunk[:MAX_TEXT_BYTES - written]
                    output.write(accepted)
                    written += len(accepted)
                    os.fsync(output.fileno())
                if written >= MAX_TEXT_BYTES and len(chunk):
                    observation["truncated"] = True
            observation["bytes"] = written

    def execute(self, job: dict[str, Any], command: list[str], *, cwd: Path,
                timeout_seconds: int, expected: dict[str, Any] | None = None,
                gui_test: bool = False,
                event_log_collector: Callable[[str, str], str] | None = None,
                poll_seconds: float = 0.2) -> RunResult:
        expected = expected or {"exit_code": 0}
        if not 1 <= timeout_seconds <= 24 * 60 * 60:
            raise ValueError("LOCAL_QA_HOLD: invalid timeout")
        if cwd.is_symlink() or not cwd.is_dir():
            raise ValueError("LOCAL_QA_HOLD: invalid test cwd")
        run_id, folder = self.start(job, command, expected=expected, gui_test=gui_test)
        stdout_observation: dict[str, Any] = {"truncated": False, "bytes": 0}
        stderr_observation: dict[str, Any] = {"truncated": False, "bytes": 0}
        started = utc_now()
        process = None
        exit_code = None
        timed_out = False
        failure_reason = None
        threads: list[threading.Thread] = []
        try:
            process = subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
            append_jsonl(folder / "journal.jsonl", {
                "at": utc_now(), "event": "PROCESS_STARTED", "pid": process.pid})
            threads = [
                threading.Thread(target=self._drain,
                                 args=(process.stdout, folder / "stdout.log", stdout_observation), daemon=True),
                threading.Thread(target=self._drain,
                                 args=(process.stderr, folder / "stderr.log", stderr_observation), daemon=True),
            ]
            for thread in threads:
                thread.start()
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break
                time.sleep(poll_seconds)
            exit_code = process.wait()
        except OSError as exc:
            failure_reason = "PROCESS_START_FAILED:" + type(exc).__name__
            atomic_write(folder / "stdout.log", b"")
            atomic_write(folder / "stderr.log", (str(exc) + "\n").encode("utf-8", errors="replace"))
            stderr_observation = {"truncated": False,
                                  "bytes": (folder / "stderr.log").stat().st_size}
        finally:
            for thread in threads:
                thread.join(timeout=10)
            if process is not None:
                for pipe in (process.stdout, process.stderr):
                    if pipe:
                        pipe.close()
        if timed_out:
            failure_reason = "TEST_TIMEOUT"
        expected_exit = expected.get("exit_code")
        status = "TEST_PASS" if (not timed_out and failure_reason is None and
                                 exit_code == expected_exit) else "TEST_FAIL"
        state = self._update_state(
            folder, state=status, finished_at_utc=utc_now(), exit_code=exit_code,
            timed_out=timed_out, failure_reason=failure_reason,
            stdout=stdout_observation, stderr=stderr_observation,
            actual={"exit_code": exit_code, "timed_out": timed_out,
                    "process_started": process is not None}, e2e_pass=False,
        )
        append_jsonl(folder / "journal.jsonl", {
            "at": utc_now(), "event": "PROCESS_FINISHED", "status": status,
            "exit_code": exit_code, "timed_out": timed_out})
        event_status, event_error = self._collect_event_log(
            folder, started, state["finished_at_utc"], event_log_collector)
        try:
            self._finalize(folder, state, event_log_status=event_status,
                           event_log_error=event_error)
        finally:
            self._release_job_lock(state)
        return RunResult(run_id, folder, status, exit_code, timed_out, False)

    def _collect_event_log(self, folder: Path, started: str, finished: str,
                           collector: Callable[[str, str], str] | None) -> tuple[str, str | None]:
        if collector is None:
            def collector(first: str, _last: str) -> str:
                if os.name != "nt":
                    raise OSError("Windows Event Log unavailable on non-Windows host")
                query = "*[System[TimeCreated[@SystemTime>='" + first + "']]]"
                result = subprocess.run(
                    ["wevtutil", "qe", "Application", "/q:" + query,
                     "/f:RenderedXml", "/c:200", "/rd:true"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=30, check=False)
                if result.returncode:
                    raise OSError("wevtutil exit " + str(result.returncode))
                return result.stdout
        try:
            value = collector(started, finished)
            if not isinstance(value, str):
                raise TypeError("collector did not return text")
            raw = value.encode("utf-8")
            if len(raw) > MAX_TEXT_BYTES:
                raw = raw[:MAX_TEXT_BYTES]
            atomic_write(folder / "windows-event-log.xml", raw)
            return ("CAPTURED" if raw else "EMPTY_VALID"), None
        except (OSError, subprocess.SubprocessError, TypeError) as exc:
            atomic_write(folder / "windows-event-log.unavailable.txt",
                         (type(exc).__name__ + ": " + str(exc)).encode("utf-8", errors="replace"))
            return "UNAVAILABLE", type(exc).__name__

    @staticmethod
    def _jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        result = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    result.append(value)
        return result

    def _finalize(self, folder: Path, state: dict[str, Any], *,
                  event_log_status: str, event_log_error: str | None) -> None:
        gui = bool(state.get("gui_test"))
        ui_actions = self._jsonl(folder / "uia-actions.jsonl")
        screenshots = self._jsonl(folder / "screenshot-index.jsonl")
        shareable_screenshots = [item for item in screenshots
                                 if item.get("privacy_reviewed_shareable") is True]
        stdout_exists = (folder / "stdout.log").is_file()
        stderr_exists = (folder / "stderr.log").is_file()
        collection = {
            "stdout": "CAPTURED" if stdout_exists and (folder / "stdout.log").stat().st_size else "EMPTY_VALID" if stdout_exists else "UNAVAILABLE",
            "stderr": "CAPTURED" if stderr_exists and (folder / "stderr.log").stat().st_size else "EMPTY_VALID" if stderr_exists else "UNAVAILABLE",
            "exit_code": "CAPTURED" if state.get("exit_code") is not None else "UNAVAILABLE",
            "windows_event_log": event_log_status,
            "windows_event_log_error": event_log_error,
            "uia_actions": "CAPTURED" if ui_actions else "UNAVAILABLE" if gui else "NOT_APPLICABLE",
            "screenshots": "CAPTURED" if screenshots else "UNAVAILABLE" if gui else "NOT_APPLICABLE",
            "github_shareable_screenshot": (
                "CAPTURED" if shareable_screenshots else
                "UNAVAILABLE_PRIVACY_REVIEW" if gui else "NOT_APPLICABLE"),
            "expected_and_actual": "CAPTURED" if isinstance(state.get("expected"), dict) and isinstance(state.get("actual"), dict) else "UNAVAILABLE",
        }
        required = ["stdout", "stderr", "exit_code", "windows_event_log", "expected_and_actual"]
        if gui:
            required.extend(("uia_actions", "screenshots", "github_shareable_screenshot"))
        complete = all(collection[name] in {"CAPTURED", "EMPTY_VALID"} for name in required)
        manifest = {
            "schema_version": SCHEMA, "run_id": state["run_id"],
            **state["job"], "started_at_utc": state["started_at_utc"],
            "finished_at_utc": state.get("finished_at_utc"), "status": state["state"],
            "failed_tests": [] if state["state"] == "TEST_PASS" else [{
                "test_id": "LOCAL-COMMAND", "category": "LOCAL_QA",
                "error": state.get("failure_reason") or "unexpected exit code",
                "expected": state.get("expected"), "actual": state.get("actual"),
            }],
            "test_command": state["command"], "exit_code": state.get("exit_code"),
            "timed_out": bool(state.get("timed_out")),
            "expected": state.get("expected"), "actual": state.get("actual"),
            "environment": {
                "machine_id": self.machine_id, "os": platform.system(),
                "os_release": platform.release(), "architecture": platform.machine(),
                "python": platform.python_version(),
            },
            "collection": collection, "collection_complete": complete,
            "local_persistence_verified": False,
            "github_return": {"status": "QUEUED", "readback_verified": False},
            "factory_dispatch": {
                "status": "AGENT_DISPATCH_PENDING",
                "target_repository": FACTORY_ROUTES[state["job"]["product_type"]],
                "reason": "No verified automatic development-agent dispatch contract is configured",
            },
            "e2e_pass": False, "store_submission_allowed": False,
        }
        atomic_json(folder / "manifest.json", manifest)
        persisted = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        manifest["local_persistence_verified"] = persisted == manifest
        atomic_json(folder / "manifest.json", manifest)
        if json.loads((folder / "manifest.json").read_text(encoding="utf-8")) != manifest:
            raise OSError("durable manifest readback mismatch")
        envelope = self._build_envelope(folder, manifest)
        atomic_json(folder / "github-envelope.json", envelope)
        if (folder / "github-envelope.json").stat().st_size > MAX_ENVELOPE_BYTES:
            raise ValueError("LOCAL_QA_HOLD: sanitized evidence envelope exceeds 25 MiB")
        queue_item = {
            "schema_version": SCHEMA, "run_id": state["run_id"],
            "envelope": str((folder / "github-envelope.json").relative_to(self.root)),
            "request_id": state["job"]["request_id"],
            "source_sha": state["job"]["source_sha"],
            "payload_sha256": envelope["payload_sha256"], "attempts": 0,
            "next_attempt_at_utc": utc_now(), "last_error": None,
            "status": "PENDING_GITHUB_RETURN",
        }
        atomic_json(self.queue / (state["run_id"] + ".json"), queue_item)
        append_jsonl(folder / "journal.jsonl", {
            "at": utc_now(), "event": "EVIDENCE_DURABLE_AND_QUEUED",
            "payload_sha256": envelope["payload_sha256"]})
        self._release_job_lock(state)

    def _release_job_lock(self, state: dict[str, Any]) -> None:
        job_key = state.get("job_key")
        if isinstance(job_key, str) and SHA64.fullmatch(job_key):
            (self.locks / (job_key + ".lock")).unlink(missing_ok=True)

    def _build_envelope(self, folder: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        clean_manifest, redactions = self.redactor.clean(manifest)
        files = []
        text_names = ("stdout.log", "stderr.log", "windows-event-log.xml",
                      "windows-event-log.unavailable.txt", "uia-actions.jsonl",
                      "screenshot-index.jsonl", "journal.jsonl")
        for name in text_names:
            path = folder / name
            if not path.is_file():
                continue
            raw = path.read_bytes()[:MAX_TEXT_BYTES]
            cleaned, count = self.redactor.text(raw.decode("utf-8", errors="replace"))
            encoded = cleaned.encode("utf-8")
            redactions += count
            files.append({"path": name, "encoding": "base64",
                          "sha256": sha256_bytes(encoded),
                          "content": base64.b64encode(encoded).decode("ascii")})
        screenshot_index = {entry["file"]: entry for entry in self._jsonl(folder / "screenshot-index.jsonl")}
        for name, entry in sorted(screenshot_index.items()):
            if not entry.get("privacy_reviewed_shareable"):
                continue
            path = folder / "screenshots" / name
            if path.is_file() and sha256_file(path) == entry.get("sha256"):
                raw = path.read_bytes()
                files.append({"path": "screenshots/" + name, "encoding": "base64",
                              "sha256": sha256_bytes(raw),
                              "content": base64.b64encode(raw).decode("ascii")})
        payload = {"manifest": clean_manifest, "files": files,
                   "redaction": {"replacement_count": redactions,
                                  "screenshots_require_explicit_privacy_review": True}}
        raw = canonical(payload)
        if not self.redactor.leak_free(raw):
            raise ValueError("LOCAL_QA_HOLD: secret-like data remains after redaction")
        return {
            "schema_version": SCHEMA, "request_id": manifest["request_id"],
            "source_sha": manifest["source_sha"],
            "payload_sha256": sha256_bytes(raw), "payload": payload,
        }


class GitHubReturnError(RuntimeError):
    pass


class GitHubContentsTransport:
    """Return one sanitized envelope through a dedicated GitHub evidence branch."""

    def __init__(self, *, repository: str, branch: str, base_ref: str,
                 gh_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None):
        if not GITHUB_REPOSITORY.fullmatch(repository) or not SAFE_BRANCH.fullmatch(branch):
            raise ValueError("invalid GitHub evidence target")
        if not SAFE_BRANCH.fullmatch(base_ref):
            raise ValueError("invalid GitHub base ref")
        self.repository = repository
        self.branch = branch
        self.base_ref = base_ref
        self._runner = gh_runner or subprocess.run

    def _call(self, args: list[str], *, body: dict[str, Any] | None = None,
              allow_failure: bool = False) -> tuple[int, dict[str, Any] | None, str]:
        temporary = None
        command = ["gh", "api", *args]
        try:
            if body is not None:
                handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                                     suffix=".json", delete=False)
                temporary = Path(handle.name)
                with handle:
                    json.dump(body, handle, ensure_ascii=False)
                command.extend(("--input", str(temporary)))
            result = self._runner(command, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=90, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitHubReturnError("GitHub transport unavailable: " + type(exc).__name__) from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        if result.returncode and not allow_failure:
            raise GitHubReturnError("GitHub API request failed")
        parsed = None
        if result.stdout.strip():
            try:
                parsed = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise GitHubReturnError("GitHub returned malformed JSON") from exc
        return result.returncode, parsed, result.stderr

    def _ensure_branch(self) -> None:
        code, _, _ = self._call([f"repos/{self.repository}/git/ref/heads/{self.branch}"],
                                allow_failure=True)
        if code == 0:
            return
        _, base, _ = self._call([f"repos/{self.repository}/git/ref/heads/{self.base_ref}"])
        try:
            sha = base["object"]["sha"]  # type: ignore[index]
        except (TypeError, KeyError) as exc:
            raise GitHubReturnError("GitHub base ref response incomplete") from exc
        self._call(["--method", "POST", f"repos/{self.repository}/git/refs"],
                   body={"ref": "refs/heads/" + self.branch, "sha": sha})

    def put_and_readback(self, envelope_path: Path) -> dict[str, Any]:
        raw = envelope_path.read_bytes()
        envelope = json.loads(raw)
        if sha256_bytes(canonical(envelope["payload"])) != envelope.get("payload_sha256"):
            raise GitHubReturnError("local envelope payload hash mismatch")
        self._ensure_branch()
        request = re.sub(r"[^A-Za-z0-9._-]", "_", envelope["request_id"])
        remote_path = (f"ops/local-qa-results/{request}/{envelope['source_sha']}/"
                       f"{envelope['payload_sha256']}.json")
        encoded = base64.b64encode(raw).decode("ascii")
        put_body = {"message": "qa: return sanitized local evidence " + request,
                    "content": encoded, "branch": self.branch}
        code, existing, _ = self._call(
            [f"repos/{self.repository}/contents/{remote_path}?ref={self.branch}"],
            allow_failure=True)
        if code == 0:
            remote_raw = self._decode_content(existing)
        else:
            self._call(["--method", "PUT", f"repos/{self.repository}/contents/{remote_path}"],
                       body=put_body)
            _, fetched, _ = self._call(
                [f"repos/{self.repository}/contents/{remote_path}?ref={self.branch}"])
            remote_raw = self._decode_content(fetched)
        remote = json.loads(remote_raw)
        if (remote.get("request_id") != envelope["request_id"] or
                remote.get("source_sha") != envelope["source_sha"] or
                remote.get("payload_sha256") != envelope["payload_sha256"] or
                sha256_bytes(canonical(remote.get("payload"))) != envelope["payload_sha256"]):
            raise GitHubReturnError("GitHub readback correlation mismatch")
        return {"status": "GITHUB_READBACK_VERIFIED", "repository": self.repository,
                "branch": self.branch, "path": remote_path,
                "request_id": envelope["request_id"],
                "source_sha": envelope["source_sha"],
                "payload_sha256": envelope["payload_sha256"],
                "remote_file_sha256": sha256_bytes(remote_raw)}

    @staticmethod
    def _decode_content(response: dict[str, Any] | None) -> bytes:
        try:
            if response.get("encoding") != "base64":  # type: ignore[union-attr]
                raise ValueError
            return base64.b64decode(response["content"], validate=False)  # type: ignore[index]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise GitHubReturnError("GitHub readback content incomplete") from exc


def process_retry_queue(store: EvidenceStore, transport: Any, *,
                        now: datetime | None = None, max_items: int = 20) -> dict[str, int]:
    """Send due items once. Failures remain durable for the next scheduled run."""
    now = now or datetime.now(timezone.utc)
    lock = store.root / "retry-worker.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {"verified": 0, "failed": 0, "deferred": 0, "locked": 1}
    verified = failed = deferred = 0
    try:
        for item_path in sorted(store.queue.glob("*.json"))[:max_items]:
            item = json.loads(item_path.read_text(encoding="utf-8"))
            due = datetime.fromisoformat(item["next_attempt_at_utc"].replace("Z", "+00:00"))
            if due > now:
                deferred += 1
                continue
            envelope = (store.root / item["envelope"]).resolve()
            if store.root not in envelope.parents or not envelope.is_file():
                item.update({"status": "LOCAL_EVIDENCE_MISSING", "last_error": "envelope missing"})
                atomic_json(item_path, item)
                failed += 1
                continue
            try:
                acknowledgement = transport.put_and_readback(envelope)
                if (acknowledgement.get("request_id") != item["request_id"] or
                        acknowledgement.get("source_sha") != item["source_sha"] or
                        acknowledgement.get("payload_sha256") != item["payload_sha256"] or
                        acknowledgement.get("status") != "GITHUB_READBACK_VERIFIED"):
                    raise GitHubReturnError("transport acknowledgement mismatch")
                atomic_json(store.acks / (item["run_id"] + ".json"), acknowledgement)
                run_folder = store._run_path(item["run_id"])
                state = json.loads((run_folder / "state.json").read_text(encoding="utf-8"))
                manifest = json.loads((run_folder / "manifest.json").read_text(encoding="utf-8"))
                e2e = (state.get("state") == "TEST_PASS" and
                       manifest.get("collection_complete") is True and
                       manifest.get("local_persistence_verified") is True)
                state["github_return"] = acknowledgement
                state["github_return"]["readback_verified"] = True
                state["e2e_pass"] = e2e
                manifest["github_return"] = state["github_return"]
                manifest["e2e_pass"] = e2e
                manifest["store_submission_allowed"] = False
                atomic_json(run_folder / "state.json", state)
                atomic_json(run_folder / "manifest.json", manifest)
                append_jsonl(run_folder / "journal.jsonl", {
                    "at": utc_now(), "event": "GITHUB_READBACK_VERIFIED",
                    "payload_sha256": item["payload_sha256"], "e2e_pass": e2e})
                item_path.unlink()
                verified += 1
            except (GitHubReturnError, OSError, json.JSONDecodeError) as exc:
                attempts = int(item.get("attempts", 0)) + 1
                delay = min(24 * 60, 2 ** min(attempts, 10))
                item.update({"attempts": attempts, "status": "RETRY_PENDING",
                             "last_error": type(exc).__name__,
                             "next_attempt_at_utc": (now + timedelta(minutes=delay)).isoformat(
                                 timespec="seconds").replace("+00:00", "Z")})
                atomic_json(item_path, item)
                failed += 1
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)
    return {"verified": verified, "failed": failed, "deferred": deferred, "locked": 0}
