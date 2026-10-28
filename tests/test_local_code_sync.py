import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import local_code_sync as s


class LocalCodeSyncTests(unittest.TestCase):
    def _manifest(self, root, **overrides):
        item = {
            "request_id": "req-1",
            "slug": "offline-notes-canary",
            "repository": "shihuiarenjinba-png/AI-App-Factory",
            "branch": "codex/app-canary-offline-notes-20261027",
            "source_sha": "b83702c8948991cc3bd31745db5df64afaf6010f",
        }
        item.update(overrides)
        path = Path(root) / "jobs.json"
        path.write_text(json.dumps({"schema_version": 1, "jobs": [item]}), encoding="utf-8")
        return path

    def test_rejects_non_allowlisted_repository(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._manifest(d, repository="other-owner/repo")
            with self.assertRaisesRegex(s.SyncHold, "allowlisted"):
                s.load_jobs(path)

    def test_rejects_unsafe_branch(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._manifest(d, branch="codex/../main")
            with self.assertRaisesRegex(s.SyncHold, "unsafe"):
                s.load_jobs(path)

    def test_rejects_duplicate_target(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._manifest(d)
            data = json.loads(path.read_text())
            data["jobs"].append(dict(data["jobs"][0]))
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(s.SyncHold, "duplicate"):
                s.load_jobs(path)

    def test_existing_dirty_snapshot_is_never_reset(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "AI-App-Factory" / "b83702c89489"
            (target / ".git").mkdir(parents=True)
            job = s.load_jobs(self._manifest(d))[0]
            outputs = iter([
                job["source_sha"],
                " M products/offline-notes-canary/main.py",
            ])
            with patch.object(s, "_run", side_effect=lambda *a, **k: next(outputs)):
                with self.assertRaisesRegex(s.SyncHold, "dirty"):
                    s._verify_existing(target, job)


    def test_reused_snapshot_rejects_origin_substring_spoof(self):
        with tempfile.TemporaryDirectory() as d:
            job = s.load_jobs(self._manifest(d))[0]
            target = Path(d) / "AI-App-Factory" / job["source_sha"][:12]
            (target / ".git").mkdir(parents=True)
            spoofed = "https://attacker.invalid/shihuiarenjinba-png/AI-App-Factory.git"
            with patch.object(s, "_run", side_effect=[job["source_sha"], "", spoofed]) as run:
                with self.assertRaisesRegex(s.SyncHold, "origin mismatch"):
                    s._verify_existing(target, job)
            self.assertEqual(run.call_count, 3)

    def test_reused_snapshot_rejects_moved_remote_branch(self):
        with tempfile.TemporaryDirectory() as d:
            job = s.load_jobs(self._manifest(d))[0]
            target = Path(d) / "AI-App-Factory" / job["source_sha"][:12]
            (target / ".git").mkdir(parents=True)
            origin = "https://github.com/" + job["repository"] + ".git"
            ref = "refs/heads/" + job["branch"]
            moved = "a" * 40 + "\t" + ref
            with patch.object(s, "_run", side_effect=[job["source_sha"], "", origin, moved]):
                with self.assertRaisesRegex(s.SyncHold, "REMOTE_HEAD_CONFLICT"):
                    s._verify_existing(target, job)

    def test_reused_snapshot_requires_current_exact_remote_head(self):
        with tempfile.TemporaryDirectory() as d:
            job = s.load_jobs(self._manifest(d))[0]
            target = Path(d) / "AI-App-Factory" / job["source_sha"][:12]
            (target / ".git").mkdir(parents=True)
            origin = "https://github.com/" + job["repository"] + ".git"
            ref = "refs/heads/" + job["branch"]
            exact = job["source_sha"] + "\t" + ref
            with patch.object(s, "_run", side_effect=[job["source_sha"], "", origin, exact]) as run:
                self.assertEqual(s._verify_existing(target, job)["status"], "REUSED_EXACT_SNAPSHOT")
            self.assertEqual(run.call_count, 4)

    def test_reused_snapshot_rejects_git_directory_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            job = s.load_jobs(self._manifest(d))[0]
            target = Path(d) / "AI-App-Factory" / job["source_sha"][:12]
            target.mkdir(parents=True)
            external = Path(d) / "external-git"
            external.mkdir()
            try:
                (target / ".git").symlink_to(external, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(s.SyncHold, "safe managed"):
                s._verify_existing(target, job)


if __name__ == "__main__":
    unittest.main()
