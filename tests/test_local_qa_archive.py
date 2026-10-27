"""Archive remains impossible until both checker and GUI/install receipts bind."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.local_qa_archive import archive_bundle

SOURCE = "a" * 40
REQUEST = "game-sample-0001"
MANIFEST = (b'<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
            b'<Identity Name="Sample.Test" Publisher="CN=Verified" Version="1.0.0.0"/>'
            b'<Applications><Application Id="App" Executable="main.exe"/></Applications></Package>')


class LocalQAArchiveTests(unittest.TestCase):
    def fixture(self, root: Path):
        inbox = root / "inbox"
        bundle = inbox / "GAME" / "sample-game"
        bundle.mkdir(parents=True)
        with zipfile.ZipFile(bundle / "package.msix", "w") as archive:
            archive.writestr("AppxManifest.xml", MANIFEST)
            archive.writestr("AppxBlockMap.xml", b"<BlockMap/>")
            archive.writestr("[Content_Types].xml", b"<Types/>")
            archive.writestr("main.exe", b"MZfixture")
        payload = (bundle / "package.msix").read_bytes()
        sha = hashlib.sha256(payload).hexdigest()
        meta = {"schema_version": 1,
                "source_repository": "https://github.com/shihuiarenjinba-png/AI-Game-Factory",
                "source_sha": SOURCE, "type": "game", "slug": "sample-game",
                "package": "package.msix", "status": "QA_UNSIGNED",
                "package_bytes": len(payload), "package_sha256": sha,
                "identity": {"name": "Sample.Test", "publisher": "CN=Verified",
                             "version": "1.0.0.0"},
                "request_id": REQUEST, "product_type": "GAME",
                "source_factory": "AI-Game-Factory",
                "source_branch": "codex/sample", "expected_head_sha": SOURCE,
                "store_id": "9N12345678",
                "signature_status": "UNSIGNED"}
        (bundle / "handoff.json").write_text(json.dumps(meta), encoding="utf-8")
        expected = {"request_id": REQUEST, "product_type": "GAME",
                    "source_sha": SOURCE, "package_sha256": sha}
        checker = root / "checker.json"
        checker.write_text(json.dumps({"receipt": {**expected,
            "checker_verdict": "NEEDS_REVIEW"}, "checker": {"verdict": "NEEDS_REVIEW"}}))
        gui = root / "gui.json"
        return inbox, bundle, checker, gui, expected

    def test_missing_gui_receipt_never_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox, bundle, checker, gui, _ = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "receipt"):
                archive_bundle(inbox, bundle, checker, gui, root / "archive")
            self.assertTrue(bundle.is_dir())

    def test_mismatched_gui_receipt_never_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox, bundle, checker, gui, expected = self.fixture(root)
            gui.write_text(json.dumps({"schema_version": 1, **expected,
                "package_sha256": "b" * 64, "status": "PASS",
                "install_status": "PASS", "gui_launch_status": "PASS"}))
            with self.assertRaisesRegex(ValueError, "CONFLICT"):
                archive_bundle(inbox, bundle, checker, gui, root / "archive")
            self.assertTrue(bundle.is_dir())

    def test_matching_checker_and_gui_receipts_allow_explicit_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox, bundle, checker, gui, expected = self.fixture(root)
            gui.write_text(json.dumps({"schema_version": 1, **expected,
                "status": "PASS", "install_status": "PASS",
                "gui_launch_status": "PASS"}))
            result = archive_bundle(inbox, bundle, checker, gui, root / "archive")
            self.assertEqual(result["status"], "ARCHIVED_LOCAL_QA_COMPLETE")
            self.assertFalse(result["e2e_pass"])
            self.assertFalse(bundle.exists())
            self.assertTrue(Path(result["archive_path"]).is_dir())


if __name__ == "__main__":
    unittest.main()
