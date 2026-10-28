"""Pure, offline regression tests: no browser, network, CAS or Store operations."""
import copy
import json
from pathlib import Path
import unittest

from scripts import prism_identity_lineage_audit as audit
from scripts import github_partner_center_handoff as gh
from scripts import local_partner_center_operator as op

PIN = "15fdcb52e46e35e6de8e87c55af99719c21e09b9"
HEAD = "11417b75636ee18816028ffd5221884c4c9a9836"
REQUEST = "3d-prism-route-3d-15fdcb52e46e"
EXE = "66b26ad96df7458ea917b632a73ac7c88bb058db24dbd11a457fd50435ab7b13"


def ledger():
    return {
        "partner_center_local_operator": {
            "mode": "LOCAL_OPERATOR_ACTIVE__EXISTING_PRODUCT_REUSE_ONLY",
            "allow_local_product_creation": False,
            "request_id": REQUEST, "slug": "prism-route-3d",
            "source_repository": "shihuiarenjinba-png/3d-game-factory",
            "source_branch": "codex/3d-canary-prism-route-20261028",
            "source_sha": PIN, "registration_type": "MSIX_OR_PWA_GAME",
            "partner_center_selection": "MSIX or PWA game",
            "exact_display_name": "Prism Route 3D",
        },
        "rotation_cohorts": {"three_d_jobs": [{
            "request_id": REQUEST, "slug": "prism-route-3d",
            "source_repository": "shihuiarenjinba-png/3d-game-factory",
            "source_branch": "codex/3d-canary-prism-route-20261028",
            "source_sha": PIN, "registration_type": "MSIX_OR_PWA_GAME",
            "partner_center_selection": "MSIX or PWA game",
            "display_name": "Prism Route 3D",
            "expected_exe_sha256": EXE,
            "factory_build_head": PIN,
            "observed_pr_head": HEAD,
            "status": "PRE_IDENTITY_READY",
            "identity_return_target": gh.IDENTITY_TARGET,
        }]},
        "user_id_requests": {"items": [{
            "request_id": REQUEST, "slug": "prism-route-3d",
            "source_repository": "shihuiarenjinba-png/3d-game-factory",
            "source_branch": "codex/3d-canary-prism-route-20261028",
            "source_sha": PIN, "registration_type": "MSIX_OR_PWA_GAME",
            "partner_center_selection": "MSIX or PWA game",
            "identity_return_target": gh.IDENTITY_TARGET,
            "allow_local_product_creation": False,
        }]},
    }


def oracle():
    return json.loads((Path(__file__).parent / "fixtures" /
                       "prism_route_3d_manual_reference.json").read_text(encoding="utf-8"))


def identity():
    o = oracle()["identity"]
    return {
        "reviewed": True, "source": "partner_center",
        "request_id": REQUEST,
        "source_repository": "shihuiarenjinba-png/3d-game-factory",
        "source_branch": "codex/3d-canary-prism-route-20261028",
        "source_sha": PIN, "verified_source_sha": PIN,
        "expected_head_sha": PIN, "slug": "prism-route-3d",
        "package_sha256": EXE, "product_type": "GAME_3D",
        "store_id": o["store_id"], "reserved_display_name": o["reserved_display_name"],
        "name": o["identity_name"], "publisher": o["publisher"],
        "publisher_display_name": o["publisher_display_name"],
        "package_family_name": o["package_family_name"],
        "package_sid": o["package_sid"],
    }


def evidence():
    return {"head": HEAD, "remote_head": HEAD, "parent": PIN,
            "changed": [["A", gh.IDENTITY_TARGET]]}


class PrismLineageAuditTests(unittest.TestCase):
    def test_one_file_descendant_is_candidate_not_cas(self):
        result = audit.evaluate(ledger(), oracle(), identity(), evidence())
        self.assertEqual(result["immutable_source_sha"], PIN)
        self.assertEqual(result["observed_return_commit"], HEAD)
        self.assertTrue(result["manual_reference_matches"])
        self.assertFalse(result["cas_return_pass"])
        self.assertFalse(result["identity_capture_pass"])
        self.assertEqual(result["local_code_sync"], "HOLD_REMOTE_HEAD_CONFLICT")

    def test_parent_must_be_pinned_sha(self):
        bad = evidence()
        bad["parent"] = "f" * 40
        with self.assertRaisesRegex(op.OperatorHold, "PARENT_OR_REMOTE"):
            audit.evaluate(ledger(), oracle(), identity(), bad)

    def test_extra_source_change_rejected(self):
        bad = evidence()
        bad["changed"].append(["M", "project.godot"])
        with self.assertRaisesRegex(op.OperatorHold, "UNEXPECTED_FILES"):
            audit.evaluate(ledger(), oracle(), identity(), bad)

    def test_remote_head_conflict_rejected(self):
        bad = evidence()
        bad["remote_head"] = "a" * 40
        with self.assertRaisesRegex(op.OperatorHold, "PARENT_OR_REMOTE"):
            audit.evaluate(ledger(), oracle(), identity(), bad)

    def test_central_head_must_match_observation(self):
        bad = ledger()
        bad["rotation_cohorts"]["three_d_jobs"][0]["observed_pr_head"] = "a" * 40
        with self.assertRaisesRegex(op.OperatorHold, "CENTRAL_OBSERVED_HEAD"):
            audit.evaluate(bad, oracle(), identity(), evidence())

    def test_immutable_source_sha_rejected_if_rewritten(self):
        bad = identity()
        bad["source_sha"] = HEAD
        with self.assertRaisesRegex(op.OperatorHold, "SOURCE_OR_PACKAGE"):
            audit.evaluate(ledger(), oracle(), bad, evidence())

    def test_exe_hash_rejected_if_changed(self):
        bad = identity()
        bad["package_sha256"] = "0" * 64
        with self.assertRaisesRegex(op.OperatorHold, "SOURCE_OR_PACKAGE"):
            audit.evaluate(ledger(), oracle(), bad, evidence())

    def test_manual_reference_mismatch_rejected(self):
        bad = identity()
        bad["store_id"] = "9N0000000000"
        with self.assertRaisesRegex(op.OperatorHold, "MANUAL_REFERENCE_COMMIT"):
            audit.evaluate(ledger(), oracle(), bad, evidence())

    def test_other_product_identity_rejected(self):
        bad = identity()
        bad["request_id"] = "other-product"
        with self.assertRaisesRegex(op.OperatorHold, "SOURCE_OR_PACKAGE"):
            audit.evaluate(ledger(), oracle(), bad, evidence())

    def test_duplicate_json_key_rejected(self):
        with self.assertRaisesRegex(op.OperatorHold, "DUPLICATE_IDENTITY_KEY"):
            json.loads('{"request_id":"a","request_id":"b"}',
                       object_pairs_hook=audit._json_no_duplicates)

    def test_original_head_is_not_return_commit(self):
        bad = evidence()
        bad["head"] = PIN
        bad["remote_head"] = PIN
        with self.assertRaisesRegex(op.OperatorHold, "HEAD_INVALID"):
            audit.evaluate(ledger(), oracle(), identity(), bad)


if __name__ == "__main__":
    unittest.main()
