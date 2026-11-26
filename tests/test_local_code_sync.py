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
                result = s._verify_existing(target, job)
            self.assertEqual(run.call_count, 4)
            self.assertEqual(result["status"], "REUSED_EXACT_SNAPSHOT")
            self.assertEqual(result["source_repository"], job["repository"])
            self.assertEqual(result["source_branch"], job["branch"])
            self.assertEqual(result["three_sha_tuple"], {
                "source_sha": job["source_sha"],
                "remote_branch_head_sha": job["source_sha"],
                "local_checkout_head_sha": job["source_sha"],
            })
            self.assertTrue(result["exact_three_sha_tuple_verified"])

    def test_new_snapshot_records_exact_three_sha_tuple(self):
        with tempfile.TemporaryDirectory() as d:
            job = s.load_jobs(self._manifest(d))[0]
            root = Path(d) / "FactoryCodeMirror"
            outputs = iter(["", "", job["source_sha"], "", job["source_sha"], ""])
            with patch.object(s, "_run", side_effect=lambda *a, **k: next(outputs)):
                result = s.sync_one(root, job)
            self.assertEqual(result["status"], "DOWNLOADED_EXACT_SNAPSHOT")
            self.assertEqual(result["source_repository"], job["repository"])
            self.assertEqual(result["source_branch"], job["branch"])
            self.assertEqual(result["three_sha_tuple"], {
                "source_sha": job["source_sha"],
                "remote_branch_head_sha": job["source_sha"],
                "local_checkout_head_sha": job["source_sha"],
            })
            self.assertTrue(result["exact_three_sha_tuple_verified"])

    def test_request_id_is_required_for_a_local_sync_target(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._manifest(d, request_id=None)
            with self.assertRaisesRegex(s.SyncHold, "request_id"):
                s.load_jobs(path)

    def test_current_manifest_contains_only_the_two_remote_head_verified_targets(self):
        fixture = Path(__file__).parent / "fixtures" / "local_code_sync_targets_20261126.json"
        jobs = s.load_jobs(fixture)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(
            {(j["slug"], j["source_sha"], j["request_id"]) for j in jobs},
            {
                ("signal-sprint", "1a349faa41663c417c40710140a4d50c79b62b78",
                 "game-signal-sprint-1a349faa41663c417c40710140a4d50c79b62b78"),
                ("prism-route-3d", "b03ce7b16c3f75c04fe20fdda224c45849eeba0d",
                 "3d-prism-route-3d-b03ce7b16c3f"),
            },
        )

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


    def test_target_resolution_keeps_offline_notes_unfixed(self):
        path = Path(__file__).parents[1] / "ops" / "local_code_sync_target_resolution_20261126.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["overall_status"],
                         "HOLD_USER_PC_RECEIPTS_PENDING_AND_OFFLINE_NOTES_SOURCE_NOT_FIXED")
        offline = next(x for x in data["targets"] if x["product"] == "Offline Notes Canary")
        self.assertEqual(offline["status"], "HOLD_SOURCE_NOT_FIXED")
        self.assertIsNone(offline["source_sha"])
        self.assertIsNone(offline["request_id"])
        self.assertEqual(data["resolvable_target_count"], 2)


if __name__ == "__main__":
    unittest.main()
