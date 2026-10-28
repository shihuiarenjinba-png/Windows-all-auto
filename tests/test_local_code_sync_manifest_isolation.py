"""Manifest isolation regression tests for exact-SHA source synchronization."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts import local_code_sync as sync


def job(request_id="app-one-0001", slug="app-one", branch="codex/app-one",
        sha="a" * 40):
    return {
        "request_id": request_id, "slug": slug,
        "repository": "shihuiarenjinba-png/AI-App-Factory",
        "branch": branch, "source_sha": sha,
    }


class ManifestIsolationTests(unittest.TestCase):
    def check(self, items, expected):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "targets.json"
            manifest.write_text(json.dumps({"schema_version": 1, "jobs": items}))
            with self.assertRaisesRegex(sync.SyncHold, expected):
                sync.load_jobs(manifest)

    def test_missing_request(self):
        self.check([job(request_id=None)], "request_id")

    def test_duplicate_request_distinct_product(self):
        self.check([job(), job(slug="app-two", branch="codex/app-two",
                               sha="b" * 40)], "duplicate request_id")

    def test_duplicate_slug_distinct_request(self):
        self.check([job(), job(request_id="app-two-0002",
                               branch="codex/app-two", sha="b" * 40)],
                   "duplicate slug")

    def test_same_branch_different_source(self):
        self.check([job(), job(request_id="app-two-0002", slug="app-two",
                               sha="b" * 40)], "duplicate source branch")

    def test_wrong_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.json"
            path.write_text(json.dumps({"schema_version": 2, "jobs": [job()]}))
            with self.assertRaisesRegex(sync.SyncHold, "schema"):
                sync.load_jobs(path)

    def test_duplicate_json_key(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.json"
            payload = json.dumps({"schema_version": 1, "jobs": [job()]})
            path.write_text(payload.replace('"slug": "app-one"',
                                            '"slug": "app-one", "slug": "app-two"'))
            with self.assertRaisesRegex(sync.SyncHold, "duplicate manifest JSON key"):
                sync.load_jobs(path)

    def test_manifest_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / "targets.json"
            original.write_text(json.dumps({"schema_version": 1, "jobs": [job()]}))
            alias = Path(directory) / "alias.json"
            try:
                alias.symlink_to(original)
            except (OSError, NotImplementedError):
                self.skipTest("symlink privilege unavailable")
            with self.assertRaisesRegex(sync.SyncHold, "linked"):
                sync.load_jobs(alias)

    def test_independent_jobs_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.json"
            path.write_text(json.dumps({"schema_version": 1, "jobs": [
                job(), job(request_id="app-two-0002", slug="app-two",
                           branch="codex/app-two", sha="b" * 40)]}))
            self.assertEqual(len(sync.load_jobs(path)), 2)


if __name__ == "__main__":
    unittest.main()
