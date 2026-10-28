"""Offline contract tests for PRE-IDENTITY queue generation; no real CAS."""
from pathlib import Path
import tempfile
import unittest

from scripts import pre_identity_queue as q
from scripts import local_identity_scheduler as s

SHA = "a" * 40
PROVISIONER_SHA = "b" * 40
EXE = "c" * 64
RID = "game-signal-sprint-" + SHA
GAME = s.OWNER + "/AI-Game-Factory"
PROVISIONER = s.OWNER + "/Repository-Provisioner-game"
BRANCH = "codex/game-signal-sprint-undo-20261027"
PBRANCH = "codex/game-identity-idempotency-20261027"


def fixture():
    return {
        "e2e_pass": False, "new_product_allowed": False,
        "active_product": {
            "request_id": RID, "product_type": "GAME", "slug": "signal-sprint",
            "source_sha": SHA, "expected_head_sha": SHA,
            "source_repository": GAME, "source_branch": BRANCH,
            "provisioner_repository": PROVISIONER,
            "provisioner_branch": PBRANCH, "provisioner_head_observed": PROVISIONER_SHA,
            "factory_exe_artifact_kind": "EXE_QA_UNSIGNED_NOT_MSIX",
            "local_execution_result": {"package_kind": "exe", "package_status": "INSPECTED",
                                       "package_sha256": EXE},
        },
        "other_lanes": {"APP": {"canary_proposal": {
            "slug": "offline-notes-canary", "source_sha": None, "request_id": None}}},
        "user_id_requests": {"items": [{"product_name": "Signal Sprint",
            "request_id": RID, "status": "WAITING_USER_IDENTITY",
            "repo": GAME, "source_branch": BRANCH, "source_sha": SHA,
            "identity_target": "%LOCALAPPDATA%/FactoryIdentityWorker/secure/<request_id>/official-identity.json"}]},
    }


def head_reader(repo, branch):
    return {(GAME, BRANCH): SHA, (PROVISIONER, PBRANCH): PROVISIONER_SHA}[(repo, branch)]


class PreIdentityQueueTests(unittest.TestCase):
    def test_game_job_derived_from_pinned_ledger_without_identity(self):
        result = q.project(fixture(), head_reader)
        self.assertEqual(len(result["jobs"]), 1)
        job = result["jobs"][0]
        self.assertEqual(job["request_id"], RID)
        self.assertEqual(job["source_sha"], SHA)
        self.assertEqual(job["package_sha256"], EXE)
        self.assertEqual(job["provisioner_head_sha"], PROVISIONER_SHA)
        self.assertIsNone(job["package_path"])
        self.assertFalse(result["ready_for_cas"])
        self.assertEqual(result["deferred"][0]["status"], "NOT_YET_REQUIRED")
        # Required field names are safe and needed for USER_ID_REQUEST, but no
        # Store Identity values may leak into a queue that has not received one.
        self.assertIn("store_id", job["required_identity_fields"])
        self.assertNotIn("OkinawaDesktopTools", str(result))
        self.assertNotIn("9N21MJM7S57P", str(result))

    def test_received_game_identity_still_queues_without_cas(self):
        data = fixture()
        data["user_id_requests"]["items"][0]["status"] = "USER_IDENTITY_RECEIVED"
        result = q.project(data, head_reader)
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["jobs"][0]["request_id"], RID)
        self.assertFalse(result["ready_for_cas"])
        self.assertEqual(result["cas"], "DELEGATED_TO_EXISTING_PROVISIONER")

    def test_received_game_identity_with_changed_binding_is_rejected(self):
        data = fixture()
        request = data["user_id_requests"]["items"][0]
        request["status"] = "USER_IDENTITY_RECEIVED"
        request["source_sha"] = "d" * 40
        with self.assertRaisesRegex(q.QueueHold, "USER_ID_REQUEST_BINDING_MISMATCH"):
            q.project(data, head_reader)

    def test_received_promoted_app_identity_queues_without_cas(self):
        data = fixture()
        candidate = data["other_lanes"]["APP"]["canary_proposal"]
        candidate.update({
            "status": "PROMOTED", "source_sha": "d" * 40,
            "request_id": "app-offline-notes-canary-20261028",
            "exe_sha256": "e" * 64,
            "branch": "codex/app-canary-offline-notes-20261027",
        })
        data["user_id_requests"]["items"].append({
            "request_id": candidate["request_id"],
            "status": "USER_IDENTITY_RECEIVED",
            "repo": s.OWNER + "/AI-App-Factory",
            "source_branch": candidate["branch"],
            "source_sha": candidate["source_sha"],
            "identity_target": "%LOCALAPPDATA%/FactoryIdentityWorker/secure/<request_id>/official-identity.json",
        })
        def app_head(repo, branch):
            if repo == s.OWNER + "/AI-App-Factory":
                return candidate["source_sha"]
            return head_reader(repo, branch)
        result = q.project(data, app_head)
        self.assertEqual(len(result["jobs"]), 2)
        self.assertEqual(result["jobs"][1]["kind"], "APP_CANARY")
        self.assertFalse(result["ready_for_cas"])

    def test_changed_factory_head_is_conflict(self):
        def moved(repo, branch):
            return "d" * 40 if repo == GAME else PROVISIONER_SHA
        with self.assertRaisesRegex(q.QueueHold, "GAME_SOURCE_HEAD_CONFLICT"):
            q.project(fixture(), moved)

    def test_changed_provisioner_head_is_conflict(self):
        def moved(repo, branch):
            return SHA if repo == GAME else "d" * 40
        with self.assertRaisesRegex(q.QueueHold, "GAME_PROVISIONER_HEAD_CONFLICT"):
            q.project(fixture(), moved)

    def test_missing_exe_digest_does_not_queue(self):
        data = fixture()
        data["active_product"]["local_execution_result"]["package_sha256"] = None
        with self.assertRaisesRegex(q.QueueHold, "GAME_EXE_PROVENANCE_NOT_READY"):
            q.project(data, head_reader)

    def test_request_id_collision_or_missing_identity_request_rejected(self):
        data = fixture()
        data["user_id_requests"]["items"].append(data["user_id_requests"]["items"][0].copy())
        with self.assertRaisesRegex(q.QueueHold, "USER_ID_REQUEST_NOT_CORRELATED"):
            q.project(data, head_reader)

    def test_game_identity_request_cannot_target_another_source(self):
        for key, value in (("repo", s.OWNER + "/AI-App-Factory"),
                           ("source_branch", "codex/another-source"),
                           ("source_sha", "d" * 40),
                           ("identity_target", "C:/untrusted/identity.json")):
            with self.subTest(key=key):
                data = fixture()
                data["user_id_requests"]["items"][0][key] = value
                with self.assertRaisesRegex(q.QueueHold, "USER_ID_REQUEST_BINDING_MISMATCH"):
                    q.project(data, head_reader)

    def test_promoted_app_requires_matching_identity_request(self):
        data = fixture()
        candidate = data["other_lanes"]["APP"]["canary_proposal"]
        candidate.update({
            "status": "PROMOTED", "source_sha": "d" * 40,
            "request_id": "app-offline-notes-canary-20261028",
            "exe_sha256": "e" * 64,
            "branch": "codex/app-canary-offline-notes-20261027",
        })
        def app_head(repo, branch):
            if repo == s.OWNER + "/AI-App-Factory":
                return candidate["source_sha"]
            return head_reader(repo, branch)
        with self.assertRaisesRegex(q.QueueHold, "APP_USER_ID_REQUEST_NOT_CORRELATED"):
            q.project(data, app_head)
        data["user_id_requests"]["items"].append({
            "request_id": candidate["request_id"], "status": "WAITING_USER_IDENTITY",
            "repo": s.OWNER + "/AI-App-Factory",
            "source_branch": candidate["branch"], "source_sha": candidate["source_sha"],
            "identity_target": "%LOCALAPPDATA%/FactoryIdentityWorker/secure/<request_id>/official-identity.json",
        })
        result = q.project(data, app_head)
        self.assertEqual(len(result["jobs"]), 2)
        self.assertEqual(result["jobs"][1]["kind"], "APP_CANARY")
        data["user_id_requests"]["items"][1]["source_sha"] = "f" * 40
        with self.assertRaisesRegex(q.QueueHold, "APP_USER_ID_REQUEST_BINDING_MISMATCH"):
            q.project(data, app_head)

    def test_unsafe_e2e_flag_rejected(self):
        data = fixture()
        data["new_product_allowed"] = True
        with self.assertRaisesRegex(q.QueueHold, "CENTRAL_LEDGER_SAFETY_GATE"):
            q.project(data, head_reader)

    def test_no_existing_local_queue_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "jobs.json"
            target.write_text("operator-unpushed-data", encoding="utf-8")
            with self.assertRaisesRegex(q.QueueHold, "OUTPUT_EXISTS_NO_OVERWRITE"):
                q.write_new_private_file(target, {"jobs": []})
            self.assertEqual(target.read_text(encoding="utf-8"), "operator-unpushed-data")

    def test_new_private_queue_file_created(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "jobs.json"
            q.write_new_private_file(target, q.project(fixture(), head_reader))
            self.assertEqual(target.exists(), True)
            self.assertIn(RID, target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
