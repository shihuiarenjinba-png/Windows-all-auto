"""Offline fail-closed tests; no browser, network, CAS or Store writes."""
import copy
import unittest

from scripts import github_partner_center_handoff as gh
from scripts import local_partner_center_operator as op
from scripts import prism_queue_provenance_audit as provenance

PIN = "15fdcb52e46e35e6de8e87c55af99719c21e09b9"
EXE = "66b26ad96df7458ea917b632a73ac7c88bb058db24dbd11a457fd50435ab7b13"
REQUEST = "3d-prism-route-3d-15fdcb52e46e"


def ledger(allow=False):
    job = {
        "request_id": REQUEST, "slug": "prism-route-3d",
        "source_repository": "shihuiarenjinba-png/3d-game-factory",
        "source_branch": "codex/3d-canary-prism-route-20261028",
        "source_sha": PIN, "registration_type": "MSIX_OR_PWA_GAME",
        "partner_center_selection": "MSIX or PWA game",
        "display_name": "Prism Route 3D",
    }
    return {
        "partner_center_local_operator": {
            "mode": "LOCAL_OPERATOR_ACTIVE__EXISTING_PRODUCT_REUSE_ONLY",
            "allow_local_product_creation": allow,
            "exact_display_name": job["display_name"],
            **{k: v for k, v in job.items() if k != "display_name"},
        },
        "rotation_cohorts": {"three_d_jobs": [{
            **job, "status": "PRE_IDENTITY_READY",
            "expected_exe_sha256": EXE, "factory_build_head": PIN,
        }]},
        "user_id_requests": {"items": [{
            **job, "identity_return_target": gh.IDENTITY_TARGET,
        }]},
    }


def identity(historical):
    return {
        "job_origin": "GITHUB_PRE_IDENTITY_QUEUE",
        "central_repository": gh.CENTRAL_REPOSITORY,
        "central_branch": gh.CENTRAL_BRANCH,
        "central_head_sha": "a" * 40,
        "queue_job_digest": gh.queue_digest(provenance.historical_payload(historical)),
        "source_factory": "3d-game-factory",
        "request_id": REQUEST, "slug": "prism-route-3d",
        "source_repository": "shihuiarenjinba-png/3d-game-factory",
        "source_branch": "codex/3d-canary-prism-route-20261028",
        "source_sha": PIN,
    }


class HistoricalQueueProvenanceTests(unittest.TestCase):
    def test_replay_match_is_not_cas_or_ui_pass(self):
        current = ledger()
        result = provenance.verify(current, copy.deepcopy(current), identity(current))
        self.assertTrue(result["github_queue_digest_replayed"])
        self.assertFalse(result["authenticated_ui_capture_pass"])
        self.assertFalse(result["cas_return_pass"])
        self.assertFalse(result["local_code_sync_pass"])
        self.assertFalse(result["e2e_pass"])

    def test_historical_creation_policy_is_replayed_not_granted(self):
        old = ledger(allow=True)
        result = provenance.verify(ledger(), old, identity(old))
        self.assertTrue(result["historical_creation_allowed"])
        self.assertFalse(result["current_creation_allowed"])
        self.assertFalse(result["cas_return_pass"])

    def test_wrong_digest_is_hold(self):
        old = ledger()
        claim = identity(old)
        claim["queue_job_digest"] = "7" * 64
        with self.assertRaisesRegex(op.OperatorHold, "DIGEST_CONFLICT"):
            provenance.verify(ledger(), old, claim)

    def test_wrong_source_identity_is_hold(self):
        old = ledger()
        claim = identity(old)
        claim["source_sha"] = "f" * 40
        with self.assertRaisesRegex(op.OperatorHold, "IDENTITY_BINDING_CONFLICT"):
            provenance.verify(ledger(), old, claim)

    def test_historical_source_drift_is_hold(self):
        old = ledger()
        old["rotation_cohorts"]["three_d_jobs"][0]["expected_exe_sha256"] = "f" * 64
        claim = identity(ledger())
        with self.assertRaisesRegex(op.OperatorHold, "CURRENT_JOB_CONFLICT"):
            provenance.verify(ledger(), old, claim)

    def test_duplicate_historical_request_is_hold(self):
        old = ledger()
        old["user_id_requests"]["items"].append(copy.deepcopy(old["user_id_requests"]["items"][0]))
        with self.assertRaisesRegex(op.OperatorHold, "NOT_UNIQUE"):
            provenance.verify(ledger(), old, identity(ledger()))

    def test_claimed_central_sha_must_be_exact(self):
        old = ledger()
        claim = identity(old)
        claim["central_head_sha"] = "not-a-sha"
        with self.assertRaisesRegex(op.OperatorHold, "ORIGIN_CLAIM_INVALID"):
            provenance.verify(ledger(), old, claim)

    def test_claimed_repository_must_be_exact(self):
        old = ledger()
        claim = identity(old)
        claim["central_repository"] = "another/Windows-all-auto"
        with self.assertRaisesRegex(op.OperatorHold, "ORIGIN_CLAIM_INVALID"):
            provenance.verify(ledger(), old, claim)

    def test_sensitive_field_rejected(self):
        old = ledger()
        claim = identity(old)
        claim["session_token"] = "must-not-be-here"
        with self.assertRaisesRegex(op.OperatorHold, "UNSAFE_FIELDS"):
            provenance.verify(ledger(), old, claim)

    def test_invalid_historical_target_rejected(self):
        old = ledger()
        old["user_id_requests"]["items"][0]["identity_return_target"] = "products/other/store/approved-identity.json"
        with self.assertRaisesRegex(op.OperatorHold, "TARGET_CONFLICT"):
            provenance.verify(ledger(), old, identity(ledger()))


if __name__ == "__main__":
    unittest.main()
