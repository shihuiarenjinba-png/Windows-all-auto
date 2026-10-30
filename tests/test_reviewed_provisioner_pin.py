"""The local APP CAS code must be an exact reviewed Provisioner checkout.

These tests mock GitHub, git, and Windows. They do not perform Identity
capture, CAS, Partner Center operations, or Store submission.
"""
from unittest import TestCase
from unittest.mock import Mock, patch

from scripts import run_local_partner_center_batch as host


class ReviewedProvisionerPinTests(TestCase):
    def check(self, head, branch, remote_head=None):
        root = Mock()
        root.is_dir.return_value = True

        def git_value(_root, *command):
            if command == ("rev-parse", "HEAD"):
                return head
            if command == ("status", "--porcelain"):
                return ""
            if command == ("branch", "--show-current"):
                return branch
            self.fail("unexpected git command: " + repr(command))

        with patch.object(host.os, "name", "nt"), \
             patch.object(host, "run", return_value="") as commands, \
             patch.object(host, "git_value", side_effect=git_value), \
             patch.object(host, "gh_json", return_value={
                 "object": {"sha": remote_head or head}
             }) as github:
            result = host.check_prerequisites(root)
            return result, commands.call_args_list, github.call_args_list

    def test_exact_reviewed_branch_and_head_are_accepted(self):
        result, commands, github = self.check(
            host.PROVISIONER_REVIEWED_HEAD,
            host.PROVISIONER_REVIEWED_BRANCH,
        )
        self.assertEqual(result["provisioner_head"],
                         host.PROVISIONER_REVIEWED_HEAD)
        self.assertEqual(result["provisioner_branch"],
                         host.PROVISIONER_REVIEWED_BRANCH)
        self.assertTrue(any("merge-base" in str(call) for call in commands))
        self.assertIn(host.PROVISIONER_REVIEWED_BRANCH, str(github))

    def test_descendant_of_reviewed_base_is_not_automatically_trusted(self):
        with self.assertRaisesRegex(host.RunnerHold,
                                    "HOLD_UNREVIEWED_PROVISIONER"):
            self.check("a" * 40, host.PROVISIONER_REVIEWED_BRANCH)

    def test_same_reviewed_sha_on_unreviewed_branch_is_rejected(self):
        with self.assertRaisesRegex(host.RunnerHold,
                                    "HOLD_UNREVIEWED_PROVISIONER"):
            self.check(host.PROVISIONER_REVIEWED_HEAD,
                       "codex/another-untested-provisioner")

    def test_remote_branch_head_drift_is_rejected(self):
        with self.assertRaisesRegex(host.RunnerHold,
                                    "HOLD_UNREVIEWED_PROVISIONER"):
            self.check(host.PROVISIONER_REVIEWED_HEAD,
                       host.PROVISIONER_REVIEWED_BRANCH,
                       remote_head="b" * 40)

    def test_no_non_windows_execution(self):
        root = Mock()
        with patch.object(host.os, "name", "posix"), \
             patch.object(host, "run") as commands:
            with self.assertRaisesRegex(host.RunnerHold,
                                        "HOLD_LOCAL_PREREQUISITE"):
                host.check_prerequisites(root)
            commands.assert_not_called()
