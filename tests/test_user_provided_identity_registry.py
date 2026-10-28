"""Regression tests for user-provided Store/GDK identity registry."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts import local_identity_scheduler as s

SOURCE_SHA = "c058cbf7fe38e02d929c67d047d717ff74bd522e"
REQUEST_ID = "game-signal-sprint-" + SOURCE_SHA


class UserProvidedIdentityRegistryTests(unittest.TestCase):
    def test_signal_sprint_registry_materializes_exact_gdk_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "official-identity.json"
            job = {
                "kind": "GAME_SIGNAL_SPRINT",
                "request_id": REQUEST_ID,
                "source_sha": SOURCE_SHA,
                "repository": s.OWNER + "/AI-Game-Factory",
                "branch": "codex/game-signal-sprint-undo-20261027",
                "slug": "signal-sprint",
                "identity_path": str(path),
            }
            result = s.validate_user_identity(job)
            self.assertTrue(result.is_file())
            data = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(data["store_id"], "9N21MJM7S57P")
            self.assertEqual(data["name"], "OkinawaDesktopTools.SignalSprint")
            self.assertEqual(data["package_family_name"],
                             "OkinawaDesktopTools.SignalSprint_j8yefg9jgfh58")
            self.assertEqual(data["xbox_title_id"], "68721417")
            self.assertEqual(data["xbox_scid"],
                             "00000000-0000-0000-0000-000068721417")
            self.assertEqual(data["msa_app_id"],
                             "39852fc3-fa46-4bda-88aa-b35385488ced")
            self.assertEqual(data["packaging_family"], "GDK")
            self.assertNotIn("version", data)
            self.assertNotIn("authenticated_account", data)
            self.assertNotIn("official_evidence_url", data)

    def test_first_run_creates_missing_private_request_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secure" / REQUEST_ID / "official-identity.json"
            self.assertFalse(path.parent.exists())
            job = {
                "kind": "GAME_SIGNAL_SPRINT", "request_id": REQUEST_ID,
                "source_sha": SOURCE_SHA,
                "repository": s.OWNER + "/AI-Game-Factory",
                "branch": "codex/game-signal-sprint-undo-20261027",
                "slug": "signal-sprint", "identity_path": str(path),
            }
            self.assertEqual(s.validate_user_identity(job), path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["store_id"],
                             "9N21MJM7S57P")
            # Existing private evidence must be validated, not overwritten.
            original = path.read_bytes()
            self.assertEqual(s.validate_user_identity(job), path)
            self.assertEqual(path.read_bytes(), original)

    def test_existing_identity_rejects_changed_registry_source_binding(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "official-identity.json"
            job = {
                "kind": "GAME_SIGNAL_SPRINT", "request_id": REQUEST_ID,
                "source_sha": SOURCE_SHA,
                "repository": s.OWNER + "/AI-Game-Factory",
                "branch": "codex/game-signal-sprint-undo-20261027",
                "slug": "signal-sprint", "identity_path": str(path),
            }
            s.validate_user_identity(job)
            registry = s.user_provided_registry()
            registry["products"]["signal-sprint"]["source_branch"] = "codex/other-branch"
            altered = Path(directory) / "altered-registry.json"
            altered.write_text(json.dumps(registry), encoding="utf-8")
            with patch.object(s, "IDENTITY_REGISTRY_PATH", altered):
                with self.assertRaises(s.Hold) as error:
                    s.validate_user_identity(job)
            self.assertEqual(error.exception.reason, "USER_IDENTITY_REFERENCE_MISMATCH")

    def test_offline_notes_identity_is_recorded_without_source_binding_yet(self):
        record = s.user_provided_registry()["products"]["offline-notes-canary"]
        self.assertEqual(record["store_id"], "9MZ8ZZTRTS17")
        self.assertEqual(record["identity_name"],
                         "OkinawaDesktopTools.OfflineNotesCanary")
        self.assertEqual(record["packaging_family"], "MSIX")
        self.assertNotIn("source_sha", record)
        self.assertNotIn("request_id", record)


if __name__ == "__main__":
    unittest.main()
