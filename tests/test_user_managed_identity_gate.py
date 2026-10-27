"""User-managed Identity handoff: no Partner Center access or CAS in tests."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from scripts import local_identity_scheduler as s

SHA = "a" * 40
DIGEST = "b" * 64
REPO = s.OWNER + "/-Excel-CSV-Privacy-Cleaner"
BRANCH = s.STORE_REFS["-Excel-CSV-Privacy-Cleaner"]


def store_job(path=None):
    return {"kind": "STORE_KNOWN_GOOD", "request_id": "store-excel-test-0001",
            "source_sha": SHA, "repository": REPO, "branch": BRANCH,
            "identity_path": str(path) if path else None}


def known_good():
    result = {"product_repo": "-Excel-CSV-Privacy-Cleaner",
              "existing_msix_builder": "store/build-store-msix.ps1",
              "approved_store_version": None,
              "package_version_approval": "UNKNOWN",
              "brand_assets_approval": "UNKNOWN"}
    for local, remote in s.IDENTITY_FIELDS.items():
        result[remote] = "reference-" + local
    return result


def store_identity(job):
    value = {"request_id": job["request_id"], "source_sha": SHA,
             "source_repository": REPO, "source_branch": BRANCH,
             "product_type": "APP"}
    for local in s.IDENTITY_FIELDS:
        value[local] = "reference-" + local
    return value


def game_job(path):
    return {"kind": "GAME_SIGNAL_SPRINT", "request_id": "game-signal-sprint-" + SHA,
            "source_sha": SHA, "repository": s.OWNER + "/AI-Game-Factory",
            "branch": "codex/game-signal-sprint-undo-20261027",
            "identity_path": str(path)}


def game_identity(job):
    value = {key: "fixture" for key in s.GAME_USER_IDENTITY_REQUIRED}
    value.update(request_id=job["request_id"], source_sha=SHA,
                 product_type="GAME", slug="signal-sprint",
                 official_evidence_url="https://partner.microsoft.com/fixture")
    return value


class UserManagedIdentityTests(unittest.TestCase):
    def test_missing_store_identity_waits(self):
        with tempfile.TemporaryDirectory() as directory:
            job = store_job(Path(directory) / "not-yet-provided.json")
            self.assertIsNone(s.validate_user_identity(job, known_good()))

    def test_store_reference_match_is_validation_not_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user-identity.json"
            job = store_job(path)
            path.write_text(json.dumps(store_identity(job)), encoding="utf-8")
            with patch.object(s, "remote_json", return_value=(known_good(), SHA)), patch.object(s, "gh", return_value={"type": "file"}), patch.object(s, "inspect_package", return_value=DIGEST):
                result = s.store_job(job, SHA)
            self.assertEqual(result["stage"], "IDENTITY_VALIDATED")
            self.assertTrue(result["user_identity_validated"])
            self.assertFalse(result["identity_authentication"])
            self.assertFalse(result["identity_return"])
            self.assertFalse(result["msix_build_allowed"])
            self.assertNotIn(str(path), json.dumps(result))

    def test_store_reference_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user-identity.json"
            job = store_job(path)
            identity = store_identity(job)
            identity["publisher"] = "different"
            path.write_text(json.dumps(identity), encoding="utf-8")
            with self.assertRaisesRegex(s.Hold, "USER_IDENTITY_REFERENCE_MISMATCH"):
                s.validate_user_identity(job, known_good())

    def test_duplicate_key_is_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user-identity.json"
            job = store_job(path)
            path.write_text('{"request_id":"a","request_id":"b"}', encoding="utf-8")
            with self.assertRaisesRegex(s.Hold, "DUPLICATE_JSON_KEY"):
                s.validate_user_identity(job, known_good())

    def test_unexpected_secret_field_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user-identity.json"
            job = store_job(path)
            identity = store_identity(job)
            identity["session_token"] = "must-not-appear-in-receipt"
            path.write_text(json.dumps(identity), encoding="utf-8")
            with self.assertRaisesRegex(s.Hold, "USER_IDENTITY_SCHEMA_MISMATCH"):
                s.validate_user_identity(job, known_good())

    def test_game_missing_file_never_delegates(self):
        with tempfile.TemporaryDirectory() as directory:
            job = game_job(Path(directory) / "official-identity.json")
            args = types.SimpleNamespace(apply_request_id="", confirm_request_id="")
            ledger = {"active_product": {"request_id": job["request_id"],
                      "source_sha": SHA, "source_branch": job["branch"],
                      "source_repository": job["repository"], "expected_head_sha": SHA,
                      "local_execution_result": {"package_sha256": DIGEST}}}
            with patch.object(s, "head", return_value=SHA), patch.object(s, "remote_json", return_value=(ledger, SHA)), patch.object(s, "inspect_package", return_value=DIGEST), patch.object(s.subprocess, "run") as worker:
                with self.assertRaisesRegex(s.Hold, "USER_IDENTITY_FILE_MISSING") as err:
                    s.game_job(job, SHA, args)
                self.assertEqual(err.exception.stage, "WAITING_USER_IDENTITY")
                worker.assert_not_called()

    def test_game_file_validated_still_requires_explicit_cas(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "official-identity.json"
            job = game_job(path)
            path.write_text(json.dumps(game_identity(job)), encoding="utf-8")
            args = types.SimpleNamespace(apply_request_id="", confirm_request_id="")
            ledger = {"active_product": {"request_id": job["request_id"],
                      "source_sha": SHA, "source_branch": job["branch"],
                      "source_repository": job["repository"], "expected_head_sha": SHA,
                      "local_execution_result": {"package_sha256": DIGEST}}}
            with patch.object(s, "head", return_value=SHA), patch.object(s, "remote_json", return_value=(ledger, SHA)), patch.object(s, "inspect_package", return_value=DIGEST), patch.object(s.subprocess, "run") as worker:
                with self.assertRaisesRegex(s.Hold, "EXPLICIT_CAS_APPROVAL_REQUIRED") as err:
                    s.game_job(job, SHA, args)
                self.assertEqual(err.exception.stage, "WAITING_CAS_APPROVAL")
                worker.assert_not_called()

    def test_game_wrong_source_sha_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "official-identity.json"
            job = game_job(path)
            identity = game_identity(job)
            identity["source_sha"] = "c" * 40
            path.write_text(json.dumps(identity), encoding="utf-8")
            with self.assertRaisesRegex(s.Hold, "USER_IDENTITY_BINDING_MISMATCH"):
                s.validate_user_identity(job)


if __name__ == "__main__":
    unittest.main()
