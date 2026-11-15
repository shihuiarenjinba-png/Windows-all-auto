"""Regression coverage for the synthetic local GitHub smoke driver."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import local_qa_github_smoke_driver as smoke


class AckTransport:
    def __init__(self, *, repository: str, branch: str, base_ref: str):
        self.repository = repository
        self.branch = branch
        self.base_ref = base_ref

    def put_and_readback(self, envelope_path: Path) -> dict:
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        return {
            "status": "GITHUB_READBACK_VERIFIED",
            "repository": self.repository,
            "branch": self.branch,
            "path": (
                "ops/local-qa-results/"
                f"{envelope['request_id']}/{envelope['source_sha']}/"
                f"{envelope['payload_sha256']}.json"
            ),
            "request_id": envelope["request_id"],
            "source_sha": envelope["source_sha"],
            "payload_sha256": envelope["payload_sha256"],
            "remote_file_sha256": "f" * 64,
        }


class LocalGitHubSmokeDriverTests(unittest.TestCase):
    def test_synthetic_smoke_passes_only_evidence_return_gate(self):
        local_tmp = Path.cwd() / ".test-tmp"
        local_tmp.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=local_tmp) as name:
            root = Path(name) / "state"
            output = io.StringIO()
            with (
                patch.object(smoke, "GitHubContentsTransport", AckTransport),
                redirect_stdout(output),
            ):
                code = smoke.main(
                    [
                        "--state-root",
                        str(root),
                        "--repository",
                        "owner/repo",
                        "--code-branch",
                        "codex/smoke",
                        "--source-sha",
                        "a" * 40,
                        "--evidence-branch",
                        "codex/local-qa-evidence-smoke",
                    ]
                )

            self.assertEqual(code, 0)
            value = json.loads(output.getvalue())
            self.assertEqual(value["status"], "LOCAL_GITHUB_EVIDENCE_SMOKE_DRIVER_PASS")
            self.assertEqual(value["test_status"], "TEST_PASS")
            self.assertTrue(value["synthetic_event_log"])
            self.assertFalse(value["real_windows_event_log_collected"])
            self.assertTrue(value["evidence_return_e2e_pass"])
            self.assertFalse(value["product_e2e_pass"])
            self.assertFalse(value["e2e_pass"])
            self.assertFalse(value["release_ready"])
            self.assertFalse(value["store_submission_allowed"])
            self.assertFalse(value["user_product_approval"])
            self.assertFalse(value["user_price_approval"])

            run_root = root / "runs" / value["run_id"]
            event_text = (run_root / "windows-event-log.xml").read_text(
                encoding="utf-8"
            )
            self.assertIn("WindowsAllAutoSyntheticSmoke", event_text)

            raw_stdout = (run_root / "stdout.log").read_text(encoding="utf-8")
            self.assertIn(smoke.FAKE_SECRET, raw_stdout)

            remote_envelope = (run_root / "github-envelope.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn(smoke.FAKE_SECRET, remote_envelope)
            self.assertIn("[REDACTED]", remote_envelope)

            manifest = json.loads(
                (run_root / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["evidence_return_e2e_pass"])
            self.assertFalse(manifest["product_e2e_pass"])
            self.assertFalse(manifest["e2e_pass"])
            self.assertFalse(manifest["store_submission_allowed"])


if __name__ == "__main__":
    unittest.main()
