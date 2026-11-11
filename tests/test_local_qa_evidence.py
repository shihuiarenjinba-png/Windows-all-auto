"""Failure-injection coverage for durable local QA evidence and GitHub return."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from all_auto.local_qa_evidence import (
    EvidenceStore, GitHubContentsTransport, GitHubReturnError,
    atomic_json, atomic_write, process_retry_queue,
)


SOURCE = "a" * 40
ARTIFACT = "b" * 64


class AckTransport:
    def put_and_readback(self, path):
        envelope = json.loads(path.read_text(encoding="utf-8"))
        return {"status": "GITHUB_READBACK_VERIFIED",
                "request_id": envelope["request_id"],
                "source_sha": envelope["source_sha"],
                "payload_sha256": envelope["payload_sha256"],
                "path": "ops/local-qa-results/evidence.json"}


class FailingTransport:
    def put_and_readback(self, path):
        raise GitHubReturnError("offline")


class MismatchTransport:
    def put_and_readback(self, path):
        envelope = json.loads(path.read_text(encoding="utf-8"))
        return {"status": "GITHUB_READBACK_VERIFIED",
                "request_id": envelope["request_id"],
                "source_sha": "f" * 40,
                "payload_sha256": envelope["payload_sha256"]}


class DurableEvidenceTests(unittest.TestCase):
    def setUp(self):
        local_tmp = Path.cwd() / ".test-tmp"
        local_tmp.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=local_tmp)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = EvidenceStore(self.root / "state")
        self.job = {
            "request_id": "app-local-qa-0001", "product_type": "APP",
            "source_repository": "owner/product", "source_branch": "codex/product",
            "source_sha": SOURCE, "artifact_sha256": ARTIFACT,
            "test_suite_version": "evidence-v1", "github_actions_run_id": 123,
            "github_artifact_id": 456,
        }

    @staticmethod
    def events(_start, _finish):
        return "<Events><Event>application record</Event></Events>"

    def command(self, source):
        return [os.fspath(Path(os.sys.executable)), "-c", source]

    def manifest(self, result):
        return json.loads((result.run_directory / "manifest.json").read_text(encoding="utf-8"))

    def test_normal_exit_is_not_e2e_until_github_readback(self):
        result = self.store.execute(
            self.job, self.command("print('ok')"), cwd=self.root,
            timeout_seconds=5, event_log_collector=self.events)
        before = self.manifest(result)
        self.assertEqual(before["status"], "TEST_PASS")
        self.assertTrue(before["collection_complete"])
        self.assertFalse(before["e2e_pass"])
        outcome = process_retry_queue(self.store, AckTransport())
        self.assertEqual(outcome["verified"], 1)
        after = self.manifest(result)
        self.assertTrue(after["github_return"]["readback_verified"])
        self.assertTrue(after["e2e_pass"])
        self.assertEqual(after["factory_dispatch"]["status"], "AGENT_DISPATCH_PENDING")
        self.assertEqual((result.run_directory / "stdout.log").read_text().strip(), "ok")

    def test_nonzero_exit_preserves_stdout_stderr_expectation_and_actual(self):
        result = self.store.execute(
            self.job, self.command("import sys; print('before crash'); print('boom', file=sys.stderr); sys.exit(7)"),
            cwd=self.root, timeout_seconds=5, event_log_collector=self.events)
        process_retry_queue(self.store, AckTransport())
        report = self.manifest(result)
        self.assertEqual(report["status"], "TEST_FAIL")
        self.assertEqual(report["exit_code"], 7)
        self.assertEqual(report["expected"]["exit_code"], 0)
        self.assertEqual(report["actual"]["exit_code"], 7)
        self.assertIn("before crash", (result.run_directory / "stdout.log").read_text())
        self.assertIn("boom", (result.run_directory / "stderr.log").read_text())
        self.assertFalse(report["e2e_pass"])

    def test_process_start_failure_is_durable_and_marks_exit_code_unavailable(self):
        result = self.store.execute(
            self.job, [os.fspath(self.root / "missing-program.exe")], cwd=self.root,
            timeout_seconds=5, event_log_collector=self.events)
        report = self.manifest(result)
        self.assertEqual(report["status"], "TEST_FAIL")
        self.assertEqual(report["collection"]["exit_code"], "UNAVAILABLE")
        self.assertIn("PROCESS_START_FAILED", report["failed_tests"][0]["error"])
        self.assertTrue((result.run_directory / "stderr.log").is_file())
        self.assertTrue(list(self.store.queue.glob("*.json")))

    def test_timeout_terminates_and_returns_failure_evidence(self):
        result = self.store.execute(
            self.job, self.command("import time; print('started', flush=True); time.sleep(30)"),
            cwd=self.root, timeout_seconds=1, event_log_collector=self.events,
            poll_seconds=0.02)
        report = self.manifest(result)
        self.assertTrue(report["timed_out"])
        self.assertEqual(report["failed_tests"][0]["error"], "TEST_TIMEOUT")
        self.assertIn("started", (result.run_directory / "stdout.log").read_text())
        self.assertFalse(report["e2e_pass"])

    def test_secret_and_personal_data_are_redacted_before_queueing(self):
        secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
        source = ("print('Authorization: Bearer " + secret + "'); "
                  "print('person@example.com'); print(r'C:\\\\Users\\\\Alice\\\\private.txt')")
        result = self.store.execute(
            self.job, self.command(source), cwd=self.root, timeout_seconds=5,
            event_log_collector=self.events)
        raw_local = (result.run_directory / "stdout.log").read_text()
        envelope = (result.run_directory / "github-envelope.json").read_text()
        self.assertIn(secret, raw_local)
        self.assertNotIn(secret, envelope)
        self.assertNotIn("person@example.com", envelope)
        self.assertIn("REDACTED", envelope)

    def test_network_failure_remains_in_durable_retry_queue(self):
        result = self.store.execute(
            self.job, self.command("print('ok')"), cwd=self.root, timeout_seconds=5,
            event_log_collector=self.events)
        outcome = process_retry_queue(self.store, FailingTransport())
        self.assertEqual(outcome["failed"], 1)
        queued = json.loads(next(self.store.queue.glob("*.json")).read_text())
        self.assertEqual(queued["attempts"], 1)
        self.assertEqual(queued["status"], "RETRY_PENDING")
        self.assertFalse(self.manifest(result)["e2e_pass"])

    def test_readback_source_mismatch_never_passes(self):
        result = self.store.execute(
            self.job, self.command("print('ok')"), cwd=self.root, timeout_seconds=5,
            event_log_collector=self.events)
        outcome = process_retry_queue(self.store, MismatchTransport())
        self.assertEqual(outcome["failed"], 1)
        self.assertFalse(self.manifest(result)["e2e_pass"])

    def test_same_request_with_changed_source_is_rejected(self):
        first = self.store.execute(
            self.job, self.command("print('first')"), cwd=self.root,
            timeout_seconds=5, event_log_collector=self.events)
        changed = dict(self.job)
        changed["source_sha"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "CONFLICT"):
            self.store.execute(
                changed, self.command("print('wrong source')"), cwd=self.root,
                timeout_seconds=5, event_log_collector=self.events)
        self.assertFalse(self.manifest(first)["e2e_pass"])

    def test_identical_job_cannot_run_concurrently_but_recovers_after_restart(self):
        run_id, _folder = self.store.start(
            self.job, self.command("print('one')"), expected={"exit_code": 0},
            gui_test=False)
        with self.assertRaisesRegex(ValueError, "already running"):
            self.store.start(
                self.job, self.command("print('two')"), expected={"exit_code": 0},
                gui_test=False)
        self.store.recover_interrupted()
        rerun_id, rerun_folder = self.store.start(
            self.job, self.command("print('retry')"), expected={"exit_code": 0},
            gui_test=False)
        self.assertNotEqual(run_id, rerun_id)
        state = json.loads((rerun_folder / "state.json").read_text())
        state.update({"state": "TEST_FAIL", "finished_at_utc": "2026-11-12T00:00:01Z",
                      "exit_code": 1, "timed_out": False,
                      "failure_reason": "test cleanup",
                      "actual": {"exit_code": 1, "timed_out": False,
                                 "process_started": False}})
        atomic_write(rerun_folder / "stdout.log", b"")
        atomic_write(rerun_folder / "stderr.log", b"cleanup")
        self.store._finalize(rerun_folder, state, event_log_status="EMPTY_VALID",
                             event_log_error=None)

    def test_pc_restart_recovery_keeps_partial_logs_and_queues_evidence(self):
        run_id, folder = self.store.start(
            self.job, self.command("print('never finalized')"), expected={"exit_code": 0},
            gui_test=False)
        atomic_write(folder / "stdout.log", b"persisted before restart\n")
        recovered_store = EvidenceStore(self.root / "state")
        self.assertEqual(recovered_store.recover_interrupted(), [run_id])
        state = json.loads((folder / "state.json").read_text())
        report = json.loads((folder / "manifest.json").read_text())
        self.assertEqual(state["state"], "INTERRUPTED_RESTART")
        self.assertEqual(report["collection"]["exit_code"], "UNAVAILABLE")
        self.assertEqual((folder / "stdout.log").read_text().strip(), "persisted before restart")
        self.assertTrue((recovered_store.queue / (run_id + ".json")).is_file())
        self.assertFalse(report["e2e_pass"])

    def test_event_log_collection_failure_blocks_e2e_pass(self):
        def denied(_start, _finish):
            raise OSError("access denied")
        result = self.store.execute(
            self.job, self.command("print('ok')"), cwd=self.root, timeout_seconds=5,
            event_log_collector=denied)
        process_retry_queue(self.store, AckTransport())
        report = self.manifest(result)
        self.assertEqual(report["collection"]["windows_event_log"], "UNAVAILABLE")
        self.assertFalse(report["collection_complete"])
        self.assertFalse(report["e2e_pass"])

    def test_gui_requires_uia_and_privacy_reviewed_screenshot(self):
        result = self.store.execute(
            self.job, self.command("print('gui placeholder')"), cwd=self.root,
            timeout_seconds=5, gui_test=True, event_log_collector=self.events)
        process_retry_queue(self.store, AckTransport())
        report = self.manifest(result)
        self.assertEqual(report["collection"]["uia_actions"], "UNAVAILABLE")
        self.assertEqual(report["collection"]["screenshots"], "UNAVAILABLE")
        self.assertFalse(report["e2e_pass"])

    def test_retention_never_removes_pending_evidence(self):
        pending = self.store.execute(
            self.job, self.command("print('pending')"), cwd=self.root,
            timeout_seconds=5, event_log_collector=self.events)
        outcome = self.store.prune_verified(retention_days=1, max_total_bytes=1024 * 1024)
        self.assertEqual(outcome["deleted_runs"], 0)
        self.assertTrue(pending.run_directory.is_dir())

    def test_retention_removes_only_old_acknowledged_run(self):
        result = self.store.execute(
            self.job, self.command("print('acknowledged')"), cwd=self.root,
            timeout_seconds=5, event_log_collector=self.events)
        process_retry_queue(self.store, AckTransport())
        state_path = result.run_directory / "state.json"
        state = json.loads(state_path.read_text())
        state["finished_at_utc"] = "2020-01-01T00:00:00Z"
        atomic_json(state_path, state)
        outcome = self.store.prune_verified(retention_days=1,
                                            max_total_bytes=1024 * 1024)
        self.assertEqual(outcome["deleted_runs"], 1)
        self.assertFalse(result.run_directory.exists())

    def test_complete_gui_evidence_can_pass_only_after_readback(self):
        run_id, folder = self.store.start(
            self.job, ["trusted-gui-driver"], expected={"exit_code": 0}, gui_test=True)
        self.store.record_ui_action(run_id, action="Invoke", target="SaveButton",
                                    result="PASS", details={"actual": "file saved"})
        picture = self.root / "safe.png"
        atomic_write(picture, b"\x89PNG\r\n\x1a\nprivacy-reviewed-test-fixture")
        self.store.add_screenshot(run_id, picture, label="saved state",
                                  privacy_reviewed_shareable=True)
        atomic_write(folder / "stdout.log", b"GUI driver completed\n")
        atomic_write(folder / "stderr.log", b"")
        state = json.loads((folder / "state.json").read_text())
        state.update({"state": "TEST_PASS", "finished_at_utc": "2026-11-12T00:00:01Z",
                      "exit_code": 0, "timed_out": False, "failure_reason": None,
                      "actual": {"exit_code": 0, "timed_out": False,
                                 "process_started": True}})
        atomic_json(folder / "state.json", state)
        atomic_write(folder / "windows-event-log.xml", b"<Events/>")
        self.store._finalize(folder, state, event_log_status="CAPTURED", event_log_error=None)
        before = json.loads((folder / "manifest.json").read_text())
        self.assertTrue(before["collection_complete"])
        self.assertFalse(before["e2e_pass"])
        process_retry_queue(self.store, AckTransport())
        after = json.loads((folder / "manifest.json").read_text())
        self.assertTrue(after["e2e_pass"])
        envelope = json.loads((folder / "github-envelope.json").read_text())
        self.assertIn("screenshots/000.png", {x["path"] for x in envelope["payload"]["files"]})


class GitHubContentsTransportTests(unittest.TestCase):
    def setUp(self):
        local_tmp = Path.cwd() / ".test-tmp"
        local_tmp.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=local_tmp)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        payload = {"manifest": {"status": "TEST_FAIL"}, "files": [], "redaction": {}}
        from all_auto.local_qa_evidence import canonical, sha256_bytes
        self.envelope = {"schema_version": "local-qa-evidence-v1",
                         "request_id": "app-request-0001", "source_sha": SOURCE,
                         "payload_sha256": sha256_bytes(canonical(payload)), "payload": payload}
        self.path = self.root / "envelope.json"
        atomic_json(self.path, self.envelope)
        self.remote_content = None

    def runner(self, command, **_kwargs):
        route = next((x for x in command if isinstance(x, str) and x.startswith("repos/")), "")
        method = command[command.index("--method") + 1] if "--method" in command else "GET"
        if "/git/ref/heads/" in route:
            return subprocess.CompletedProcess(command, 0,
                json.dumps({"object": {"sha": "c" * 40}}), "")
        if "/contents/" in route and method == "GET":
            if self.remote_content is None:
                return subprocess.CompletedProcess(command, 1, "", "not found")
            return subprocess.CompletedProcess(command, 0,
                json.dumps({"encoding": "base64", "content": self.remote_content}), "")
        if "/contents/" in route and method == "PUT":
            request_path = Path(command[command.index("--input") + 1])
            body = json.loads(request_path.read_text(encoding="utf-8"))
            self.remote_content = body["content"]
            return subprocess.CompletedProcess(command, 0, json.dumps({"commit": {"sha": "d" * 40}}), "")
        raise AssertionError(command)

    def test_put_then_readback_verifies_request_source_and_payload_hash(self):
        transport = GitHubContentsTransport(
            repository="owner/repo", branch="codex/local-evidence",
            base_ref="main", gh_runner=self.runner)
        ack = transport.put_and_readback(self.path)
        self.assertEqual(ack["status"], "GITHUB_READBACK_VERIFIED")
        self.assertEqual(ack["source_sha"], SOURCE)
        self.assertEqual(ack["payload_sha256"], self.envelope["payload_sha256"])

    def test_tampered_readback_is_rejected(self):
        bad = dict(self.envelope)
        bad["source_sha"] = "f" * 40
        self.remote_content = base64.b64encode(json.dumps(bad).encode()).decode()
        transport = GitHubContentsTransport(
            repository="owner/repo", branch="codex/local-evidence",
            base_ref="main", gh_runner=self.runner)
        with self.assertRaisesRegex(GitHubReturnError, "correlation mismatch"):
            transport.put_and_readback(self.path)


if __name__ == "__main__":
    unittest.main()
