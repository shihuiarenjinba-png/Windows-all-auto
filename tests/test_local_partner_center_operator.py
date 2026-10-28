"""Contract-only regression tests; no Partner Center/browser/network activity."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import local_partner_center_operator as op

SHA = "8b00bc4e90828c4282463826873aa8dfd2eb93f4"
REQUEST = "app-focus-session-desk-8b00bc4e9082"
SLUG = "focus-session-desk"
REPO = "shihuiarenjinba-png/AI-App-Factory"
BRANCH = "codex/app-cohort-focus-controller-20261028"
TARGET = f"products/{SLUG}/store/approved-identity.json"


def binding():
    return {
        "request_id": REQUEST, "product_type": "APP", "slug": SLUG,
        "display_name": "Focus Session Desk", "source_repository": REPO,
        "source_branch": BRANCH, "source_sha": SHA,
        "registration_type": "MSIX_OR_PWA_APP",
        "partner_center_selection": "MSIX or PWA app",
        "identity_return_target": TARGET,
    }


def ledger():
    source = {key: value for key, value in binding().items()
              if key != "identity_return_target"}
    return {
        "partner_center_local_operator": {"mode": "LOCAL_OPERATOR_ACTIVE__BATCH"},
        "rotation_cohorts": {"app_jobs": [{**source, "status": "PRE_IDENTITY_READY"}],
                             "three_d_jobs": []},
        "user_id_requests": {"items": [{
            "request_id": REQUEST, "slug": SLUG, "repo": REPO,
            "source_branch": BRANCH, "source_sha": SHA,
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "identity_return_target": TARGET,
            "status": "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE",
            "allow_local_product_creation": True,
        }]},
    }


def captured():
    return {
        **binding(), "store_id": "9NABCDEF1234",
        "reserved_display_name": "Focus Session Desk",
        "identity_name": "OkinawaDesktopTools.FocusSessionDesk",
        "publisher": "CN=ExamplePublisher",
        "publisher_display_name": "Example Publisher",
        "package_family_name": "OkinawaDesktopTools.FocusSessionDesk_123456789abcd",
        "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
        "creation_status": "CREATED", "overview_exact_match_count": 1,
        "identity_details_observed": True,
    }


def ready_job(**extra):
    return {
        **binding(), "status": "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY",
        "job_origin": "GITHUB_PRE_IDENTITY_QUEUE",
        "central_repository": "shihuiarenjinba-png/Windows-all-auto",
        "central_branch": "codex/e2e-belt-connection-20261027",
        "central_head_sha": "a" * 40, "queue_job_digest": "b" * 64,
        "snapshot_path": "C:/safe/focus", "source_snapshot_head": SHA,
        "allow_local_product_creation": True, **extra,
    }


class OperatorGateTests(unittest.TestCase):
    def test_prepare_verifies_physical_exact_snapshot_again(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / "AI-App-Factory" / SHA[:12]
            target.mkdir(parents=True)
            receipt = {"status": "PASS", "exact_sha_verified": True, "products": [{
                "repository": REPO, "branch": BRANCH, "source_sha": SHA, "slug": SLUG,
                "request_id": REQUEST, "status": "REUSED_EXACT_SNAPSHOT", "path": str(target),
            }]}
            with patch.object(op.sync, "_verify_existing", return_value={"status": "REUSED_EXACT_SNAPSHOT"}):
                result = op.prepare(ledger(), receipt, root, SLUG,
                                    central_repository="shihuiarenjinba-png/Windows-all-auto",
                                    central_branch="codex/e2e-belt-connection-20261027",
                                    central_head_sha="a" * 40)
            self.assertEqual(result["product_type"], "APP")
            self.assertEqual(result["identity_return_target"], TARGET)
            self.assertFalse(result["browser_action_performed"])

    def test_product_values_are_read_from_job_not_prism_constants(self):
        job = op.expected_job(ledger(), SLUG)
        self.assertEqual(job["display_name"], "Focus Session Desk")
        self.assertEqual(job["registration_type"], "MSIX_OR_PWA_APP")

    def test_cross_product_request_binding_rejected(self):
        value = ledger()
        value["user_id_requests"]["items"][0]["source_sha"] = "f" * 40
        with self.assertRaisesRegex(op.OperatorHold, "REQUEST_BINDING"):
            op.expected_job(value, SLUG)

    def test_wrong_return_target_rejected(self):
        value = ledger()
        value["user_id_requests"]["items"][0]["identity_return_target"] = "products/wrong/store/approved-identity.json"
        with self.assertRaises(op.OperatorHold):
            op.expected_job(value, SLUG)

    def test_wrong_registration_family_rejected(self):
        value = ledger()
        value["rotation_cohorts"]["app_jobs"][0]["registration_type"] = "MSIX_OR_PWA_GAME"
        value["rotation_cohorts"]["app_jobs"][0]["partner_center_selection"] = "MSIX or PWA game"
        with self.assertRaisesRegex(op.OperatorHold, "APP_JOB_ROUTING_CONFLICT"):
            op.expected_job(value, SLUG)

    def test_capture_produces_versionless_github_bound_receipt(self):
        result = op.validate_capture(ready_job(batch_id="batch", batch_index=1,
                                               batch_total=4, trigger_origin="SCHEDULED_36_MIN_LOOP",
                                               automation_id="6adf4b1e7654819193b997fb4fb83c85"), captured())
        self.assertTrue(result["authenticated_partner_center_pass"])
        self.assertEqual(result["package_version_gate"], "HOLD")
        self.assertNotIn("version", result)
        self.assertEqual(result["batch_index"], 1)

    def test_capture_rejects_identity_from_another_product(self):
        value = captured()
        value["request_id"] = "app-file-integrity-ledger-d1108d12f7d1"
        with self.assertRaisesRegex(op.OperatorHold, "CROSS_PRODUCT"):
            op.validate_capture(ready_job(), value)

    def test_capture_rejects_ambiguous_overview(self):
        value = captured()
        value["overview_exact_match_count"] = 2
        with self.assertRaisesRegex(op.OperatorHold, "EVIDENCE_INCOMPLETE"):
            op.validate_capture(ready_job(), value)

    def test_capture_rejects_cookie_or_secret_field(self):
        value = captured()
        value["cookie"] = "must never be logged"
        with self.assertRaisesRegex(op.OperatorHold, "POSSIBLE_SECRET"):
            op.validate_capture(ready_job(), value)

    def test_reuse_only_job_cannot_claim_created(self):
        with self.assertRaisesRegex(op.OperatorHold, "DUPLICATE_PRODUCT_CREATE_FORBIDDEN"):
            op.validate_capture(ready_job(allow_local_product_creation=False), captured())

    def test_private_receipt_is_idempotent_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "private.json"
            op.write_private_once(path, {"status": "PASS"})
            op.write_private_once(path, {"status": "PASS"})
            with self.assertRaisesRegex(op.OperatorHold, "NO_OVERWRITE"):
                op.write_private_once(path, {"status": "CHANGED"})


if __name__ == "__main__":
    unittest.main()
