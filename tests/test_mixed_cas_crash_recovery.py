"""Fail-closed regression for CAS success followed by local power loss.

All evidence is mocked. These tests never contact Partner Center or GitHub,
never apply CAS, and cannot attest to physical Windows execution.
"""
from copy import deepcopy
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from scripts import mixed_batch_resume as resume
from scripts import mixed_resume_rebase as rebase
from scripts import run_local_partner_center_batch as host

OLD = "a" * 40
NEW = "b" * 40
COMMIT = "c" * 40
SOURCE = ("1" * 40, "2" * 40, "3" * 40, "4" * 40)
ORIGIN = "MANUAL_WINDOWS_TERMINAL"


def plan(post=()):
    products = []
    for i, slug in enumerate(resume.EXPECTED_ORDER):
        is_post = slug in post
        products.append({
            "batch_index": i + 1,
            "slug": slug,
            "request_id": "app-" + slug + "-" + SOURCE[i][:12],
            "source_repository": "shihuiarenjinba-png/AI-App-Factory",
            "source_branch": "codex/" + slug,
            "source_sha": SOURCE[i],
            "identity_return_target":
                "products/" + slug + "/store/approved-identity.json",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "observed_identity_state":
                "POST_IDENTITY_READY" if is_post else "PRE_IDENTITY_READY",
            "dispatch_action": resume.POST_ACTION if is_post else resume.PRE_ACTION,
            "identity_cas_authorized_by_plan": False,
            "partner_center_creation_authorized_by_plan": False,
        })
    return {
        "status": "MIXED_ROTATION_DISPATCH_PLAN_READY",
        "discovered_count": 4,
        "post_identity_skip_count": len(post),
        "pre_identity_pending_count": 4 - len(post),
        "local_windows_no_llm_pass": False,
        "task_scheduler_registration_allowed": False,
        "store_submission": "NOT_PERFORMED",
        "cas": "NOT_PERFORMED",
        "products": products,
    }


class CrashRebaseTests(TestCase):
    def setUp(self):
        self.old = resume.initialize(
            plan(), central_head_sha=OLD, execution_origin=ORIGIN,
        )
        self.old, self.claimed = resume.claim_next(self.old)
        self.new_plan = plan({resume.EXPECTED_ORDER[0]})

    def migrate(self, verifier=None):
        return rebase.rebase_after_reconciliation(
            self.old, self.new_plan,
            new_central_head_sha=NEW,
            execution_origin=ORIGIN,
            independent_return_verifier=None,
            independent_active_return_verifier=verifier,
        )

    def test_independently_verified_crash_releases_active_as_post_skip(self):
        seen = []
        def verifier(old, fresh):
            seen.append((old["status"], fresh["status"]))
            return True
        result = self.migrate(verifier)
        self.assertEqual(seen, [("ACTIVE", "SKIPPED_GITHUB_POST_VERIFIED")])
        self.assertEqual(result["products"][0]["status"],
                         "SKIPPED_GITHUB_POST_VERIFIED")
        self.assertIsNone(result["products"][0]["result"])
        self.assertIsNone(result["active_request_id"])
        self.assertEqual(resume.summary(result)["next_resume_index"], 2)
        self.assertFalse(resume.summary(result)["task_scheduler_registration_allowed"])
        self.assertEqual(result["store_submission"], "NOT_PERFORMED")

    def test_missing_independent_evidence_blocks_recovery(self):
        for verifier in (None, lambda old, fresh: False):
            with self.subTest(verifier=verifier):
                with self.assertRaisesRegex(
                        rebase.RebaseHold, "HOLD_REBASE_CRASH_RETURN_EVIDENCE"):
                    self.migrate(verifier)
        self.assertEqual(self.old["products"][0]["status"], "ACTIVE")

    def test_pending_to_post_cannot_use_crash_verifier(self):
        self.old = resume.initialize(
            plan(), central_head_sha=OLD, execution_origin=ORIGIN,
        )
        with self.assertRaisesRegex(rebase.RebaseHold,
                                    "HOLD_REBASE_PENDING_CHANGED"):
            self.migrate(lambda old, fresh: True)

    def test_active_pointer_tampering_is_rejected_before_callback(self):
        self.old["active_request_id"] = "another-request"
        callback = Mock(return_value=True)
        with self.assertRaisesRegex(rebase.RebaseHold,
                                    "HOLD_REBASE_CONCURRENT_ACTIVE"):
            self.migrate(callback)
        callback.assert_not_called()

    def test_active_cannot_become_post_without_exact_binding(self):
        self.new_plan["products"][0]["source_sha"] = "f" * 40
        with self.assertRaisesRegex(rebase.RebaseHold,
                                    "HOLD_REBASE_CROSS_PRODUCT_BINDING"):
            self.migrate(lambda old, fresh: True)

    def test_active_remains_active_when_unrelated_central_head_changes(self):
        result = rebase.rebase_after_reconciliation(
            self.old, plan(), new_central_head_sha=NEW,
            execution_origin=ORIGIN, independent_return_verifier=None,
        )
        self.assertEqual(result["active_request_id"], self.claimed["request_id"])
        self.assertEqual(result["products"][0]["status"], "ACTIVE")


class CrashHostVerifierTests(TestCase):
    def setUp(self):
        self.job = {
            "slug": "offline-text-diff-desk",
            "request_id": "app-offline-text-diff-desk-" + SOURCE[2][:12],
            "source_repository": "shihuiarenjinba-png/AI-App-Factory",
            "source_branch": "codex/offline-text-diff-desk",
            "source_sha": SOURCE[2],
            "identity_return_target":
                "products/offline-text-diff-desk/store/approved-identity.json",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "display_name": "Offline Text Diff Desk",
            "status": "POST_IDENTITY_READY",
            "identity_return_commit_sha": COMMIT,
            "identity_store_id": "9P1234567890",
            "identity_pfn": "OkinawaDesktopTools.TextDiff_j8yefg9jgfh58",
        }
        self.old = {k: self.job[k] for k in (
            "slug", "request_id", "source_sha", "identity_return_target",
            "registration_type", "partner_center_selection")}
        self.old.update({"status": "ACTIVE", "result": None})
        self.fresh = {**self.old, "status": "SKIPPED_GITHUB_POST_VERIFIED"}
        self.ledger = {"rotation_cohorts": {"app_jobs": [self.job]}}
        self.receipt = {
            **{k: self.job[k] for k in (
                "slug", "request_id", "source_repository", "source_branch",
                "source_sha", "identity_return_target", "registration_type",
                "partner_center_selection", "display_name")},
            "queue_job_digest": "e" * 64,
            "store_id": self.job["identity_store_id"],
            "package_family_name": self.job["identity_pfn"],
        }
        self.operator_job = {
            **{k: self.job[k] for k in (
                "slug", "request_id", "source_repository", "source_branch",
                "source_sha", "identity_return_target", "registration_type",
                "partner_center_selection", "display_name")},
            "central_head_sha": OLD,
            "source_snapshot_head": SOURCE[2],
            "queue_job_digest": "e" * 64,
        }
        self.driver = Mock()
        self.driver.verify_current.return_value = True

    def verify(self):
        return host.verify_mixed_crash_return(
            self.old, self.fresh, self.ledger, Path("C:/private-state"),
            NEW, OLD, self.driver,
        )

    def test_exact_ui_and_github_return_required(self):
        with patch.object(host.operator, "read_json",
                          side_effect=[self.receipt, self.operator_job]), \
             patch.object(host, "existing_observation", return_value=object()), \
             patch.object(host, "validated_mixed_source_path",
                          return_value=Path("C:/immutable-source")), \
             patch.object(host, "github_result_verified",
                          return_value=True) as github:
            self.assertTrue(self.verify())
            github.assert_called_once()

    def test_github_failure_blocks_crash_recovery(self):
        with patch.object(host.operator, "read_json",
                          side_effect=[self.receipt, self.operator_job]), \
             patch.object(host, "existing_observation", return_value=object()), \
             patch.object(host, "validated_mixed_source_path",
                          return_value=Path("C:/immutable-source")), \
             patch.object(host, "github_result_verified", return_value=False):
            self.assertFalse(self.verify())

    def test_ui_failure_blocks_crash_recovery(self):
        self.driver.verify_current.return_value = False
        with patch.object(host.operator, "read_json",
                          side_effect=[self.receipt, self.operator_job]), \
             patch.object(host, "existing_observation", return_value=object()), \
             patch.object(host, "github_result_verified") as github:
            self.assertFalse(self.verify())
            github.assert_not_called()

    def test_receipt_collision_and_old_central_head_block(self):
        self.receipt["store_id"] = "9PWRONG"
        with patch.object(host.operator, "read_json",
                          side_effect=[self.receipt, self.operator_job]):
            self.assertFalse(self.verify())
        self.receipt["store_id"] = self.job["identity_store_id"]
        self.operator_job["central_head_sha"] = "f" * 40
        with patch.object(host.operator, "read_json",
                          side_effect=[self.receipt, self.operator_job]):
            self.assertFalse(self.verify())

    def test_unreconciled_central_job_never_recovers(self):
        self.job["status"] = "PRE_IDENTITY_READY"
        self.assertFalse(self.verify())
