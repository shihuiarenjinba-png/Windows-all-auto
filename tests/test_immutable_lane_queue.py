import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from all_auto.handoff_bridge import stage_bundle, validate_bundle
from all_auto.lane_queue import relative_package_path, validate_immutable

SHA = "a" * 40
HEAD = "b" * 40
XML = b'<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="Demo.App" Publisher="CN=ABC" Version="1.0.0.0"/><Applications><Application Id="App" Executable="app.exe"/></Applications></Package>'


class ImmutableLaneTransportTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.source = self.root / "source"
        self.source.mkdir()
        with zipfile.ZipFile(self.source / "package.msix", "w") as z:
            z.writestr("AppxManifest.xml", XML)
            z.writestr("AppxBlockMap.xml", b"<BlockMap/>")
            z.writestr("[Content_Types].xml", b"<Types/>")
            z.writestr("app.exe", b"runnable payload fixture")
        data = (self.source / "package.msix").read_bytes()
        self.base = {
            "schema_version": 1,
            "source_repository": "https://github.com/shihuiarenjinba-png/AI-Game-Factory",
            "source_sha": SHA, "expected_head_sha": SHA,
            "type": "game", "product_type": "GAME",
            "source_factory": "AI-Game-Factory",
            "source_branch": "codex/game-signal-sprint-undo-20261027",
            "request_id": "game-qa-0001", "slug": "signal-sprint",
            "store_id": "9NTEST123456", "package": "package.msix",
            "status": "QA_UNSIGNED",
            "package_sha256": hashlib.sha256(data).hexdigest(),
            "package_bytes": len(data),
            "identity": {"name": "Demo.App", "publisher": "CN=ABC", "version": "1.0.0.0"}
        }
        self.write()

    def write(self):
        (self.source / "handoff.json").write_text(json.dumps(self.base), encoding="utf-8")

    def test_game_real_byte_transport_into_separate_queue(self):
        result = stage_bundle(self.source, self.root / "queue", SHA)
        self.assertEqual(result["request_id"], "game-qa-0001")
        self.assertEqual(result["contract_status"], "IMMUTABLE_QA_ONLY")
        dest = self.root / "queue" / relative_package_path(result)
        self.assertEqual((dest / "package.msix").read_bytes(), (self.source / "package.msix").read_bytes())
        self.assertFalse(result["submit_allowed"])

    def test_same_request_changed_sha_is_conflict(self):
        stage_bundle(self.source, self.root / "queue", SHA)
        self.base["source_sha"] = "c" * 40
        self.base["expected_head_sha"] = "c" * 40
        self.write()
        with self.assertRaisesRegex(ValueError, "HANDOFF_CONFLICT"):
            stage_bundle(self.source, self.root / "queue", "c" * 40)

    def test_source_branch_and_factory_mismatch_fail_closed(self):
        for key, value in (("source_branch", "main"), ("source_factory", "AI-App-Factory"),
                           ("product_type", "APP"), ("expected_head_sha", HEAD)):
            with self.subTest(key=key):
                original = self.base[key]
                self.base[key] = value
                self.write()
                with self.assertRaises(ValueError):
                    validate_bundle(self.source, SHA)
                self.base[key] = original
        self.write()

    def test_app_identity_return_run_sha_and_exe_bound(self):
        self.base.update(type="app", product_type="APP", source_factory="AI-App-Factory",
                         source_repository="https://github.com/shihuiarenjinba-png/AI-App-Factory",
                         factory_head_sha=HEAD, source_branch="codex/app-pinned-exe-msix-handoff-20261027",
                         display_name="Demo", prebuilt_exe_sha256=hashlib.sha256(b"runnable payload fixture").hexdigest())
        self.write()
        result = stage_bundle(self.source, self.root / "queue", HEAD)
        self.assertEqual(result["source_sha"], SHA)
        self.assertEqual(result["factory_head_sha"], HEAD)
        self.assertTrue((self.root / "queue" / "APP" / (self.base["slug"] + "-" + self.base["package_sha256"][:12])).is_dir())
        with self.assertRaisesRegex(ValueError, "Actions head SHA"):
            validate_bundle(self.source, SHA)

    def test_game_identity_return_build_head_preserves_original_source_sha(self):
        self.base["factory_head_sha"] = HEAD
        self.write()
        result = stage_bundle(self.source, self.root / "queue", HEAD)
        self.assertEqual(result["source_sha"], SHA)
        self.assertEqual(result["factory_head_sha"], HEAD)
        self.assertEqual(result["product_type"], "GAME")
        with self.assertRaisesRegex(ValueError, "Actions head SHA"):
            validate_bundle(self.source, SHA)

    def test_missing_request_id_does_not_silently_downgrade(self):
        del self.base["request_id"]
        self.write()
        with self.assertRaisesRegex(ValueError, "immutable"):
            validate_bundle(self.source, SHA)


if __name__ == "__main__":
    unittest.main()
