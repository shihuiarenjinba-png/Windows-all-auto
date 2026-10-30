"""Offline negative regressions: authenticated POST Identity GitHub transport."""
import base64
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts import post_identity_github_readers as readers

REPO = "shihuiarenjinba-png/AI-App-Factory"
BRANCH = "codex/app-cohort-focus-controller-20261028"
SOURCE = "8b00bc4e90828c4282463826873aa8dfd2eb93f4"
RETURN = "8a7139375524830bf823469526837259266172be"
PATH = "products/focus-session-desk/store/approved-identity.json"


def compare_response():
    return {
        "status": "ahead", "ahead_by": 1, "behind_by": 0, "total_commits": 1,
        "base_commit": {"sha": SOURCE}, "merge_base_commit": {"sha": SOURCE},
        "commits": [{"sha": RETURN}],
        "files": [{"filename": PATH, "status": "added"}],
    }


class AuthenticatedPostReaderTests(unittest.TestCase):
    @patch.object(readers, "_gh_json")
    def test_exact_branch_head(self, get):
        get.return_value = {
            "ref": f"refs/heads/{BRANCH}",
            "object": {"type": "commit", "sha": RETURN},
        }
        self.assertEqual(readers.fetch_factory_branch_head(REPO, BRANCH), RETURN)
        self.assertIn("git/ref/heads/", get.call_args.args[0])

    @patch.object(readers, "_gh_json")
    def test_branch_name_and_ref_mismatch_hold(self, get):
        with self.assertRaises(readers.AuthenticatedReadHold):
            readers.fetch_factory_branch_head(REPO, "main")
        with self.assertRaises(readers.AuthenticatedReadHold):
            readers.fetch_factory_branch_head(REPO, "codex/../unsafe")
        get.return_value = {
            "ref": "refs/heads/codex/other",
            "object": {"type": "commit", "sha": RETURN},
        }
        with self.assertRaises(readers.AuthenticatedReadHold):
            readers.fetch_factory_branch_head(REPO, BRANCH)

    @patch.object(readers, "_gh_json")
    def test_immutable_identity_bytes(self, get):
        payload = '{"request_id":"safe"}'
        get.return_value = {
            "type": "file", "path": PATH, "encoding": "base64",
            "size": len(payload), "content": base64.b64encode(payload.encode()).decode(),
        }
        self.assertEqual(readers.fetch_approved_identity(REPO, PATH, RETURN), payload)
        self.assertTrue(get.call_args.args[0].endswith(f"?ref={RETURN}"))

    @patch.object(readers, "_gh_json")
    def test_identity_wrong_path_and_size_hold(self, get):
        payload = b"{}"
        get.return_value = {
            "type": "file", "path": "products/other/store/approved-identity.json",
            "encoding": "base64", "size": 2,
            "content": base64.b64encode(payload).decode(),
        }
        with self.assertRaises(readers.AuthenticatedReadHold):
            readers.fetch_approved_identity(REPO, PATH, RETURN)
        get.return_value["path"] = PATH
        get.return_value["size"] = 3
        with self.assertRaises(readers.AuthenticatedReadHold):
            readers.fetch_approved_identity(REPO, PATH, RETURN)
        with self.assertRaises(readers.AuthenticatedReadHold):
            readers.fetch_approved_identity(REPO, "../secrets", RETURN)

    @patch.object(readers, "_gh_json")
    def test_identity_only_source_descendant(self, get):
        get.return_value = compare_response()
        self.assertTrue(readers.verify_identity_only_ancestry(REPO, SOURCE, RETURN, PATH))

    @patch.object(readers, "_gh_json")
    def test_reject_extra_file_wrong_source_or_merge(self, get):
        for mutation in (
            lambda d: d["files"].append({"filename": "src/extra.py", "status": "modified"}),
            lambda d: d["merge_base_commit"].update(sha="f" * 40),
            lambda d: d.update(ahead_by=2, total_commits=2),
            lambda d: d["files"][0].update(status="modified"),
        ):
            item = compare_response()
            mutation(item)
            get.return_value = item
            with self.assertRaises(readers.AuthenticatedReadHold):
                readers.verify_identity_only_ancestry(REPO, SOURCE, RETURN, PATH)

    @patch.object(readers, "_gh_json")
    def test_reject_cross_repository_or_same_sha(self, get):
        with self.assertRaises(readers.AuthenticatedReadHold):
            readers.verify_identity_only_ancestry("attacker/AI-App-Factory", SOURCE, RETURN, PATH)
        with self.assertRaises(readers.AuthenticatedReadHold):
            readers.verify_identity_only_ancestry(REPO, SOURCE, SOURCE, PATH)
        get.assert_not_called()

    @patch.object(readers.subprocess, "run")
    def test_failed_auth_is_hold_without_secret_leak(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="",
            stderr="gh auth token=very-private HTTP 401",
        )
        with self.assertRaisesRegex(readers.AuthenticatedReadHold,
                                    "^HOLD_POST_GITHUB_READ_UNAVAILABLE$"):
            readers._gh_json("repos/example/example")
        self.assertEqual(run.call_args.kwargs["timeout"], 45)

    @patch.object(readers.subprocess, "run")
    def test_oversized_and_nonobject_response_hold(self, run):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="x" * (readers._MAX_RESPONSE + 1),
            stderr="",
        )
        with self.assertRaises(readers.AuthenticatedReadHold):
            readers._gh_json("repos/example/example")
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps([]), stderr="",
        )
        with self.assertRaises(readers.AuthenticatedReadHold):
            readers._gh_json("repos/example/example")


if __name__ == "__main__":
    unittest.main()
