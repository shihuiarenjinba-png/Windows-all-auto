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
                result = op.prepare(ledger(), receipt, root)
            mock.assert_called_once()
            self.assertFalse(result["browser_action_performed"])
            self.assertFalse(result["cas_applied"])

    def test_prepare_rejects_cloud_only_or_missing_receipt(self):
        with self.assertRaisesRegex(op.OperatorHold, "LOCAL_CODE_SYNC_NOT_PASS"):
            op.prepare(ledger(), {"status": "HOLD"}, Path("unused"))

    def test_prepare_rejects_cross_product_source(self):
        l = ledger()
        l["rotation_cohorts"]["three_d_jobs"][0]["source_sha"] = "a" * 40
        with self.assertRaisesRegex(op.OperatorHold, "CROSS_PRODUCT"):
            op.expected_job(l, "prism-route-3d")

    def test_existing_product_can_be_reused_but_never_created_again(self):
        l = ledger()
        l["partner_center_local_operator"]["allow_local_product_creation"] = False
        self.assertEqual(op.expected_job(l, "prism-route-3d")["slug"], "prism-route-3d")
        job = {**binding(), "status": "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY",
               "allow_local_product_creation": False}
        c = captured()
        with self.assertRaisesRegex(op.OperatorHold, "DUPLICATE_PRODUCT_CREATE_FORBIDDEN"):
            op.validate_capture(job, c)
        c["creation_status"] = "REUSED_EXISTING"
        self.assertIn("IDENTITY_CAPTURED", op.validate_capture(job, c)["status"])

    def test_prepare_rejects_gdk_misclassification(self):
        l = ledger()
        l["rotation_cohorts"]["three_d_jobs"][0]["registration_type"] = "GDK_GAME"
        l["partner_center_local_operator"]["registration_type"] = "GDK_GAME"
        with self.assertRaises(op.OperatorHold):
            op.expected_job(l, "prism-route-3d")

    def test_capture_is_local_attestation_not_authenticated_pass(self):
        result = op.validate_capture({
            **binding(), "status": "LOCAL_CODE_SYNC_PASS__PARTNER_CENTER_OPERATOR_READY"
        }, captured())
        self.assertTrue(result["existing_scheduler_routing_pending"])
        self.assertFalse(result["authenticated_partner_center_pass"])
        self.assertFalse(result["cas_applied"])

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
