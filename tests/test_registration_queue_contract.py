"""PRE-IDENTITY registration metadata is preserved into scheduler handoff."""
import unittest
from scripts import pre_identity_queue as q
from scripts import local_identity_scheduler as s

SHA = "a" * 40
PROV = "b" * 40
RID = "game-signal-sprint-" + SHA
GAME = s.OWNER + "/AI-Game-Factory"
PROV_REPO = s.OWNER + "/Repository-Provisioner-game"
GAME_BRANCH = "codex/game-signal-sprint-undo-20261027"
PROV_BRANCH = "codex/game-gdk-identity-contract-20261028"
TARGET = "%LOCALAPPDATA%/FactoryIdentityWorker/secure/<request_id>/official-identity.json"


def ledger():
    return {
        "e2e_pass": False, "new_product_allowed": False,
        "active_product": {
            "request_id": RID, "product_type": "GAME", "slug": "signal-sprint",
            "packaging_family": "GDK", "registration_type": "GDK_GAME",
            "source_sha": SHA, "expected_head_sha": SHA,
            "source_repository": GAME, "source_branch": GAME_BRANCH,
            "provisioner_repository": PROV_REPO,
            "provisioner_branch": PROV_BRANCH, "provisioner_head_observed": PROV,
            "factory_exe_artifact_kind": "EXE_QA_UNSIGNED_NOT_MSIX",
            "local_execution_result": {
                "package_kind": "exe", "package_status": "INSPECTED",
                "package_sha256": "c" * 64},
        },
        "other_lanes": {"APP": {"canary_proposal": {
            "slug": "offline-notes-canary", "packaging_family": "MSIX",
            "registration_type": "MSIX_OR_PWA_APP",
            "source_sha": None, "request_id": None}}},
        "user_id_requests": {"items": [{
            "request_id": RID, "status": "USER_IDENTITY_RECEIVED",
            "repo": GAME, "source_branch": GAME_BRANCH, "source_sha": SHA,
            "identity_target": TARGET}]},
    }


def head(repo, branch):
    return {(GAME, GAME_BRANCH): SHA, (PROV_REPO, PROV_BRANCH): PROV}[(repo, branch)]


class QueueRegistrationTests(unittest.TestCase):
    def test_pinned_game_and_deferred_app(self):
        result = q.project(ledger(), head)
        self.assertEqual(result["jobs"][0]["registration_type"], "GDK_GAME")
        self.assertEqual(result["jobs"][0]["partner_center_selection"], "GDK game")
        self.assertEqual(result["deferred"][0]["registration_type"], "MSIX_OR_PWA_APP")
        self.assertEqual(result["deferred"][0]["partner_center_selection"],
                         "MSIX or PWA app")
        self.assertFalse(result["ready_for_cas"])

    def test_mislabeled_game_is_hold(self):
        data = ledger()
        data["active_product"]["registration_type"] = "EXE_OR_MSI_APP"
        with self.assertRaisesRegex(ValueError, "REGISTRATION_TYPE_CONFLICT"):
            q.project(data, head)

    def test_mislabeled_app_is_hold_even_when_not_promoted(self):
        data = ledger()
        data["other_lanes"]["APP"]["canary_proposal"]["registration_type"] = "EXE_OR_MSI_APP"
        with self.assertRaisesRegex(ValueError, "REGISTRATION_TYPE_CONFLICT"):
            q.project(data, head)

    def test_scheduler_rejects_modified_handoff(self):
        data = q.project(ledger(), head)
        data["jobs"][0]["registration_type"] = "MSIX_OR_PWA_GAME"
        data["jobs"][0]["partner_center_selection"] = "MSIX or PWA game"
        with self.assertRaisesRegex(s.Hold, "REGISTRATION_TYPE_CONFLICT"):
            s.validate_jobs(data)


if __name__ == "__main__":
    unittest.main()
