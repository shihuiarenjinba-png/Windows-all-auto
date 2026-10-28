"""Contract-only regression tests; no Partner Center/browser/network activity."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import local_partner_center_operator as op

SHA = "15fdcb52e46e35e6de8e87c55af99719c21e09b9"
REQUEST = "3d-prism-route-3d-15fdcb52e46e"
REPO = "shihuiarenjinba-png/3d-game-factory"
BRANCH = "codex/3d-canary-prism-route-20261028"
CENTRAL_HEAD = "4" * 40


def binding():
    return {
        "request_id": REQUEST, "slug": "prism-route-3d",
        "source_repository": REPO, "source_branch": BRANCH,
        "source_sha": SHA, "registration_type": "MSIX_OR_PWA_GAME",
        "partner_center_selection": "MSIX or PWA game",
        "display_name": "Prism Route 3D",
    }


def ledger():
    return {
        "partner_center_local_operator": {
            **binding(), "exact_display_name": "Prism Route 3D",
            "mode": "LOCAL_OPERATOR_ACTIVE__PHYSICAL_UI_NOT_ACCESSED_IN_THIS_RUN",
            "allow_local_product_creation": True,
        },
        "rotation_cohorts": {"three_d_jobs": [
            {**binding(), "status": "PRE_IDENTITY_READY"}
        ]},
    }


def captured():
    return {
        **binding(), "store_id": "9NABCDEF1234",
        "reserved_display_name": "Prism Route 3D",
        "identity_name": "PrismRoute3D",
        "publisher": "CN=ExamplePublisher",
        "publisher_display_name": "Example Publisher",
        "package_family_name": "PrismRoute3D_123456789abcd",
        "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
        "creation_status": "CREATED",
        "overview_exact_match_count": 1,
        "identity_details_observed": True,
    }


class OperatorGateTests(unittest.TestCase):
    def test_prepare_verifies_physical_exact_snapshot_again(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = root / "3d-game-factory" / SHA[:12]
            target.mkdir(parents=True)
            receipt = {"status": "PASS", "exact_sha_verified": True, "products": [{
                "repository": REPO, "branch": BRANCH, "source_sha": SHA,
                "slug": "prism-route-3d", "request_id": REQUEST,
                "status": "REUSED_EXACT_SNAPSHOT", "path": str(target),
            }]}
            with patch.object(op.sync, "_verify_existing", return_value={"status": "REUSED_EXACT_SNAPSHOT"}) as mock:
                result = op.prepare(ledger(), receipt, root, central_head_sha=CENTRAL_HEAD)
            mock.assert_called_once()
            self.assertEqual(result["job_origin"], "GITHUB_PRE_IDENTITY_QUEUE")
            self.assertEqual(result["central_head_sha"], CENTRAL_HEAD)
            self.assertEqual(result["source_snapshot_head"], SHA)
            self.assertEqual(result["identity_return_target"], "products/prism-route-3d/store/approved-identity.json")
            self.assertFalse(result["browser_action_performed"])
            self.assertFalse(result["cas_applied"])

    def test_prepare_rejects_cloud_only_or_missing_receipt(self):
        with self.assertRaisesRegex(op.OperatorHold, "LOCAL_CODE_SYNC_NOT_PASS"):
            op.prepare(ledger(), {"status": "HOLD"}, Path("unused"), central_head_sha=CENTRAL_HEAD)

    def test_prepare_rejects_cross_product_source(self):
        l = ledger()
        l["rotation_cohorts"]["three_d_jobs"][0]["source_sha"] = "a" * 40
        with self.assertRaisesRegex(op.OperatorHold, "CROSS_PRODUCT"):
            op.expected_job(l, "prism-route-3d")

    def test_prepare_rejects_unapproved_creation(self):
        l = ledger()
        l["partner_center_local_operator"]["allow_local_product_creation"] = False
        with self.assertRaisesRegex(op.OperatorHold, "NOT_AUTHORIZED"):
            op.expected_job(l, "prism-route-3d")

    def test_prepare_rejects_gdk_misclassification(self):
        l = ledger()
        l["rotation_cohorts"]["three_d_jobs"][0]["registration_type"] = "GDK_GAME"
        l["partner_center_local_operator"]["registration_type"] = "GDK_GAME"
        with self.assertRaises(op.OperatorHold):
            op.expected_job(l, "prism-route-3d")

    def test_authenticated_ui_capture_is_github_bound_and_version_held(self):
        job = {
            **binding(), "product_type": "GAME_3D",
            "status": "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY",
            "job_origin": "GITHUB_PRE_IDENTITY_QUEUE",
            "central_repository": op.CENTRAL_REPOSITORY,
            "central_branch": op.CENTRAL_BRANCH,
            "central_head_sha": CENTRAL_HEAD,
            "queue_job_digest": "a" * 64,
            "snapshot_path": "C:/safe/snapshot",
            "source_snapshot_head": SHA,
            "identity_return_target": op.IDENTITY_RETURN_TARGET,
        }
        result = op.validate_capture(job, captured(), {k: captured()[k] for k in op.IDENTITY})
        self.assertTrue(result["existing_scheduler_routing_pending"])
        self.assertTrue(result["authenticated_partner_center_pass"])
        self.assertEqual(result["manual_reference_comparison"], "MATCH")
        self.assertEqual(result["package_version_gate"], "HOLD")
        self.assertFalse(result["cas_applied"])

    def test_capture_reference_mismatch_holds(self):
        job = {
            **binding(), "product_type": "GAME_3D",
            "status": "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY",
            "job_origin": "GITHUB_PRE_IDENTITY_QUEUE", "central_repository": op.CENTRAL_REPOSITORY,
            "central_branch": op.CENTRAL_BRANCH, "central_head_sha": CENTRAL_HEAD,
            "queue_job_digest": "a" * 64, "snapshot_path": "C:/safe/snapshot",
            "source_snapshot_head": SHA, "identity_return_target": op.IDENTITY_RETURN_TARGET,
        }
        reference = {k: captured()[k] for k in op.IDENTITY}
        reference["store_id"] = "9DIFFERENT"
        with self.assertRaisesRegex(op.OperatorHold, "HOLD_IDENTITY_CAPTURE_MISMATCH"):
            op.validate_capture(job, captured(), reference)

    def test_capture_rejects_request_mismatch(self):
        c = captured()
        c["request_id"] = "other"
        with self.assertRaisesRegex(op.OperatorHold, "CROSS_PRODUCT"):
            op.validate_capture({**binding(), "status": "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY"}, c)

    def test_capture_rejects_ambiguous_overview(self):
        c = captured()
        c["overview_exact_match_count"] = 2
        with self.assertRaisesRegex(op.OperatorHold, "EVIDENCE_INCOMPLETE"):
            op.validate_capture({**binding(), "status": "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY"}, c)

    def test_capture_rejects_cookie_or_secret_field(self):
        c = captured()
        c["cookie"] = "must never be logged"
        with self.assertRaisesRegex(op.OperatorHold, "POSSIBLE_SECRET"):
            op.validate_capture({**binding(), "status": "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY"}, c)

    def test_capture_rejects_missing_required_field(self):
        c = captured()
        del c["publisher"]
        with self.assertRaisesRegex(op.OperatorHold, "INCOMPLETE"):
            op.validate_capture({**binding(), "status": "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY"}, c)

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "dup.json"
            path.write_text('{"request_id":"first","request_id":"second"}', encoding="utf-8")
            with self.assertRaisesRegex(op.OperatorHold, "DUPLICATE_JSON_KEY"):
                op.read_json(path)

    def test_private_receipt_is_idempotent_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "private.json"
            op.write_private_once(path, {"status": "PASS"})
            op.write_private_once(path, {"status": "PASS"})
            with self.assertRaisesRegex(op.OperatorHold, "NO_OVERWRITE"):
                op.write_private_once(path, {"status": "CHANGED"})


if __name__ == "__main__":
    unittest.main()
