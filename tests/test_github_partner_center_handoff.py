"""Offline regression for GitHub-origin Prism Identity reuse; no browser or CAS."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import github_partner_center_handoff as gh
from scripts import local_partner_center_operator as op

SHA = "15fdcb52e46e35e6de8e87c55af99719c21e09b9"
HEAD = "a" * 40
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
            "mode": "LOCAL_OPERATOR_ACTIVE__EXISTING_PRODUCT_REUSE",
            "allow_local_product_creation": False,
        },
        "rotation_cohorts": {"three_d_jobs": [{
            **binding(), "status": "PRE_IDENTITY_READY",
            "expected_exe_sha256": "1" * 64,
            "factory_build_head": SHA,
        }]},
        "user_id_requests": {"items": [{
            **binding(), "identity_return_target": gh.IDENTITY_TARGET,
        }]},
    }


def reference():
    return json.loads(
        (Path(__file__).parent / "fixtures" / "prism_route_3d_manual_reference.json")
        .read_text(encoding="utf-8")
    )


def captured():
    return {
        **binding(), **reference()["identity"],
        "creation_status": "REUSED_EXISTING",
        "overview_exact_match_count": 1,
        "identity_details_observed": True,
    }


class GithubOriginGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.central = self.root / "central"
        (self.central / "ops").mkdir(parents=True)
        self.snaproot = self.root / "snapshots"
        self.snapshot = self.snaproot / "3d-game-factory" / SHA[:12]
        self.snapshot.mkdir(parents=True)
        self.data = ledger()
        self.save()

    def save(self):
        (self.central / "ops" / "active_e2e_handoff.json").write_text(
            json.dumps(self.data), encoding="utf-8"
        )

    def receipt(self):
        return {
            "status": "PASS", "exact_sha_verified": True,
            "products": [{
                "request_id": REQUEST, "slug": "prism-route-3d",
                "repository": REPO, "branch": BRANCH, "source_sha": SHA,
                "status": "REUSED_EXACT_SNAPSHOT", "path": str(self.snapshot),
            }],
        }

    def prepared(self):
        with patch.object(gh, "verify_central", return_value=HEAD), patch.object(
            op.sync, "_verify_existing", return_value={"status": "REUSED_EXACT_SNAPSHOT"}
        ):
            return gh.prepare_github(self.central, self.receipt(), self.snaproot)

    def validated(self, job, capture=None, oracle=None, head=HEAD):
        with patch.object(gh, "verify_central", return_value=head), patch.object(
            op.sync, "_verify_existing", return_value={"status": "REUSED_EXACT_SNAPSHOT"}
        ):
            return gh.validate_github(job, capture or captured(), oracle or reference(),
                                      self.central, self.snaproot)

    def test_queue_digest_is_deterministic_and_binds_identity_target(self):
        payload = gh.queue_payload(self.data)
        self.assertEqual(gh.queue_digest(payload), gh.queue_digest(copy.deepcopy(payload)))
        payload["identity_return_target"] = "products/other/store/approved-identity.json"
        self.assertNotEqual(gh.queue_digest(payload), gh.queue_digest(gh.queue_payload(self.data)))

    def test_queue_rejects_cross_product_request(self):
        self.data["user_id_requests"]["items"][0]["source_sha"] = "b" * 40
        with self.assertRaisesRegex(op.OperatorHold, "CROSS_PRODUCT"):
            gh.queue_payload(self.data)

    def test_queue_refuses_creation_enabled_for_existing_product(self):
        self.data["partner_center_local_operator"]["allow_local_product_creation"] = True
        with self.assertRaisesRegex(op.OperatorHold, "CREATE_MUST_BE_DISABLED"):
            gh.queue_payload(self.data)

    def test_prepare_attests_github_origin_and_exact_snapshot(self):
        job = self.prepared()
        self.assertEqual(job["job_origin"], "GITHUB_PRE_IDENTITY_QUEUE")
        self.assertEqual(job["central_head_sha"], HEAD)
        self.assertEqual(job["source_snapshot_head"], SHA)
        self.assertEqual(job["identity_return_target"], gh.IDENTITY_TARGET)
        self.assertFalse(job["allow_local_product_creation"])
        self.assertFalse(job["browser_action_performed"])

    def test_existing_capture_matches_manual_oracle_but_not_authenticated(self):
        job = self.prepared()
        result = self.validated(job)
        self.assertIn("MANUAL_REFERENCE__AUTOMATED_UI_NOT_VERIFIED", result["status"])
        self.assertFalse(result["authenticated_partner_center_pass"])
        self.assertTrue(result["existing_scheduler_routing_pending"])
        self.assertFalse(result["cas_applied"])
        self.assertEqual(result["queue_job_digest"], job["queue_job_digest"])

    def test_identity_mismatch_fails_closed(self):
        job = self.prepared()
        c = captured()
        c["store_id"] = "9N9999999999"
        with self.assertRaisesRegex(op.OperatorHold, "MANUAL_REFERENCE_IDENTITY_CONFLICT"):
            self.validated(job, c)

    def test_created_again_is_rejected(self):
        job = self.prepared()
        c = captured()
        c["creation_status"] = "CREATED"
        with self.assertRaisesRegex(op.OperatorHold, "DUPLICATE_PRODUCT_CREATE_FORBIDDEN"):
            self.validated(job, c)

    def test_missing_github_origin_is_rejected(self):
        job = self.prepared()
        del job["queue_job_digest"]
        with self.assertRaisesRegex(op.OperatorHold, "GITHUB_QUEUE_PROVENANCE_CONFLICT"):
            self.validated(job)

    def test_central_branch_advance_invalidates_prepared_job(self):
        job = self.prepared()
        with self.assertRaisesRegex(op.OperatorHold, "GITHUB_QUEUE_PROVENANCE_CONFLICT"):
            self.validated(job, head="b" * 40)

    def test_snapshot_path_tampering_is_rejected(self):
        job = self.prepared()
        job["source_snapshot_path"] = str(self.root / "unrelated")
        with self.assertRaisesRegex(op.OperatorHold, "LOCAL_SNAPSHOT_PATH_CONFLICT"):
            self.validated(job)

    def test_capture_rejects_secret_fields(self):
        job = self.prepared()
        c = captured()
        c["cookie"] = "must never be stored"
        with self.assertRaisesRegex(op.OperatorHold, "POSSIBLE_SECRET"):
            self.validated(job, c)

    def test_manual_reference_cannot_be_sole_capture_evidence(self):
        job = self.prepared()
        c = captured()
        c["identity_details_observed"] = False
        with self.assertRaisesRegex(op.OperatorHold, "EVIDENCE_INCOMPLETE"):
            self.validated(job, c)

    def test_verify_central_rejects_dirty_checkout(self):
        (self.central / ".git").mkdir()
        with patch.object(gh.sync, "_run", side_effect=[
            HEAD, "https://github.com/" + gh.CENTRAL_REPOSITORY + ".git",
            " M ops/active_e2e_handoff.json",
            HEAD + "\trefs/heads/" + gh.CENTRAL_BRANCH,
        ]):
            with self.assertRaisesRegex(op.OperatorHold, "ORIGIN_OR_DIRTY_CONFLICT"):
                gh.verify_central(self.central)

    def test_verify_central_rejects_remote_head_drift(self):
        (self.central / ".git").mkdir()
        with patch.object(gh.sync, "_run", side_effect=[
            HEAD, "https://github.com/" + gh.CENTRAL_REPOSITORY + ".git",
            "", "b" * 40 + "\trefs/heads/" + gh.CENTRAL_BRANCH,
        ]):
            with self.assertRaisesRegex(op.OperatorHold, "REMOTE_HEAD_CONFLICT"):
                gh.verify_central(self.central)


if __name__ == "__main__":
    unittest.main()
