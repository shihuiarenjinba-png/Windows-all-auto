"""Offline safety regression tests for the independent scheduler."""
import hashlib
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from scripts import local_identity_scheduler as s


SHA = "a" * 40
OTHER = "b" * 40
DIGEST = hashlib.sha256(b"safe package").hexdigest()
REPO = s.OWNER + "/-Excel-CSV-Privacy-Cleaner"
BRANCH = s.STORE_REFS["-Excel-CSV-Privacy-Cleaner"]


def store_job(**updates):
    job = {"kind": "STORE_KNOWN_GOOD", "request_id": "store-excel-test-0001",
           "source_sha": SHA, "repository": REPO, "branch": BRANCH}
    job.update(updates)
    return job


def reference():
    data = {"product_repo": "-Excel-CSV-Privacy-Cleaner",
            "existing_msix_builder": "store/build-store-msix.ps1",
            "approved_store_version": None, "package_version_approval": "UNKNOWN",
            "brand_assets_approval": "UNKNOWN"}
    for local, remote in s.IDENTITY_FIELDS.items():
        data[remote] = "value-" + local
    return data


def evidence(job):
    data = {"observation": "LOCAL_OPERATOR_OBSERVED_MATCH",
            "request_id": job["request_id"], "source_sha": job["source_sha"]}
    for local in s.IDENTITY_FIELDS:
        data[local] = "value-" + local
    return data


class SchedulerSafetyTests(unittest.TestCase):
    def test_duplicate_request_id_rejected(self):
        with self.assertRaisesRegex(s.Hold, "DUPLICATE_REQUEST_ID"):
            s.validate_jobs({"jobs": [store_job(), store_job()]})

    def test_bad_branch_rejected(self):
        with self.assertRaisesRegex(s.Hold, "INVALID_JOB_BINDING"):
            s.validate_jobs({"jobs": [store_job(branch="main")]})

    def test_wrong_store_branch_rejected(self):
        with self.assertRaisesRegex(s.Hold, "STORE_REFERENCE_BRANCH_MISMATCH"):
            s.validate_jobs({"jobs": [store_job(branch="codex/wrong")]})

    def test_duplicate_json_key_rejected(self):
        with self.assertRaisesRegex(s.Hold, "DUPLICATE_JSON_KEY"):
            s.decode_json('{"jobs": [], "jobs": []}')

    def test_exclusive_lock_blocks_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock"
            with s.ExclusiveLock(path):
                with self.assertRaisesRegex(s.Hold, "ALREADY_RUNNING"):
                    with s.ExclusiveLock(path):
                        pass
            self.assertFalse(path.exists())

    def test_local_package_hash_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "package.exe"
            path.write_bytes(b"safe package")
            job = store_job(package_path=str(path), package_sha256=DIGEST)
            self.assertEqual(s.inspect_package(job), DIGEST)
            job["package_sha256"] = "0" * 64
            with self.assertRaisesRegex(s.Hold, "PACKAGE_SHA_MISMATCH"):
                s.inspect_package(job)

    def test_evidence_absence_not_authenticated(self):
        self.assertFalse(s.validate_operator_evidence(store_job(), reference()))

    def test_evidence_local_match_is_not_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            job = store_job(evidence_path=str(Path(directory) / "private.json"))
            Path(job["evidence_path"]).write_text(json.dumps(evidence(job)), encoding="utf-8")
            self.assertTrue(s.validate_operator_evidence(job, reference()))

    def test_evidence_rejects_secret_or_url_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            job = store_job(evidence_path=str(Path(directory) / "private.json"))
            data = evidence(job)
            data["session_cookie"] = "must-never-appear"
            Path(job["evidence_path"]).write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(s.Hold, "EVIDENCE_FIELDS_NOT_ALLOWED"):
                s.validate_operator_evidence(job, reference())

    def test_evidence_rejects_identity_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            job = store_job(evidence_path=str(Path(directory) / "private.json"))
            data = evidence(job)
            data["package_sid"] = "wrong"
            Path(job["evidence_path"]).write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(s.Hold, "IDENTITY_REFERENCE_MISMATCH"):
                s.validate_operator_evidence(job, reference())

    def test_version_gate_requires_all_three_approvals(self):
        data = reference()
        self.assertFalse(s.version_gate(data))
        data.update(approved_store_version="1.0.0.0",
                    package_version_approval="APPROVED")
        self.assertFalse(s.version_gate(data))
        data["brand_assets_approval"] = "APPROVED"
        self.assertTrue(s.version_gate(data))

    def test_store_builder_is_repo_specific(self):
        job = store_job()
        with patch.object(s, "remote_json", return_value=(reference(), SHA)), \
             patch.object(s, "gh", return_value={"type": "file"}) as gh, \
             patch.object(s, "inspect_package", return_value=DIGEST), \
             patch.object(s, "validate_operator_evidence", return_value=True):
            result = s.store_job(job, SHA)
        self.assertEqual(result["builder"], "store/build-store-msix.ps1")
        self.assertFalse(result["identity_authentication"])
        self.assertFalse(result["msix_build_allowed"])
        self.assertIn("build-store-msix.ps1", gh.call_args.args[0])

    def test_branch_mismatch_conflicts_before_package(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(s, "head", return_value=OTHER), \
             patch.object(s, "store_job") as handler:
            result = s.process(store_job(), types.SimpleNamespace(), Path(directory))
        self.assertEqual(result["stage"], "CONFLICT")
        handler.assert_not_called()

    def test_persisted_state_binding_prevents_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            s.atomic_json(state_path, {
                "stage": "WAITING_CAS_APPROVAL", "request_id": "store-excel-test-0001",
                "source_sha": OTHER, "repository": REPO, "branch": BRANCH,
                "kind": "STORE_KNOWN_GOOD",
            })
            with self.assertRaisesRegex(s.Hold, "PERSISTED_JOB_BINDING_MISMATCH"):
                s.read_previous(state_path, store_job())

    def test_completed_cas_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            job = store_job()
            path = Path(directory) / (hashlib.sha256(job["request_id"].encode()).hexdigest() + ".json")
            prior = {**job, "stage": "WAITING_FACTORY_MSIX", "e2e_pass": False}
            s.atomic_json(path, prior)
            with patch.object(s, "head") as head:
                result = s.process(job, types.SimpleNamespace(), Path(directory))
            self.assertEqual(result, prior)
            head.assert_not_called()

    def test_one_job_per_run_round_robin(self):
        with tempfile.TemporaryDirectory() as directory:
            jobs_file = Path(directory) / "jobs.json"
            state_dir = Path(directory) / "state"
            jobs = [store_job(), store_job(request_id="store-excel-test-0002")]
            jobs_file.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
            args = types.SimpleNamespace(jobs_file=jobs_file, state_dir=state_dir,
                                         apply_request_id="")
            with patch.object(s, "process", side_effect=lambda j, a, d: {"request_id": j["request_id"]}):
                a = s.run(args)
                b = s.run(args)
                c = s.run(args)
            self.assertEqual([a["request_id"], b["request_id"], c["request_id"]],
                             ["store-excel-test-0001", "store-excel-test-0002",
                              "store-excel-test-0001"])

    def test_game_delegates_only_with_explicit_approval(self):
        job = {"kind": "GAME_SIGNAL_SPRINT", "request_id": "game-signal-sprint-" + SHA,
               "source_sha": SHA, "repository": s.OWNER + "/AI-Game-Factory",
               "branch": "codex/game-signal-sprint-undo-20261027"}
        args = types.SimpleNamespace(apply_request_id="", confirm_request_id="")
        ledger = {"active_product": {
            "request_id": job["request_id"], "source_sha": SHA,
            "source_branch": job["branch"], "source_repository": job["repository"],
            "expected_head_sha": SHA, "local_execution_result": {"package_sha256": DIGEST},
        }}
        with patch.object(s, "head", return_value=SHA), \
             patch.object(s, "remote_json", return_value=(ledger, SHA)), \
             patch.object(s, "inspect_package", return_value=DIGEST), \
             patch.object(s.subprocess, "run") as process:
            with self.assertRaisesRegex(s.Hold, "GAME_WORKER_CHECK_ONLY"):
                s.game_job(job, SHA, args)
            process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
