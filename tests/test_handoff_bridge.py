import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from all_auto.handoff_bridge import validate_bundle, stage_bundle

SHA="a"*40
XML=b'<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="OkinawaDesktopTools.TestApp" Publisher="CN=ABC" Version="1.0.1.0"/></Package>'

class HandoffBridgeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.source=self.root/"source"
        self.source.mkdir()
        with zipfile.ZipFile(self.source/"package.msix","w") as z:
            z.writestr("AppxManifest.xml",XML)
            z.writestr("app.exe",b"test executable payload")
        blob=(self.source/"package.msix").read_bytes()
        self.info={
          "schema_version":1,"source_repository":"https://github.com/shihuiarenjinba-png/AI-App-Factory",
          "source_sha":SHA,"type":"app","slug":"demo-app",
          "package":"package.msix","status":"QA_UNSIGNED",
          "package_sha256":hashlib.sha256(blob).hexdigest(),"package_bytes":len(blob),
          "identity":{"name":"OkinawaDesktopTools.TestApp","publisher":"CN=ABC","version":"1.0.1.0"}
        }
        self.write_info()

    def write_info(self):
        (self.source/"handoff.json").write_text(json.dumps(self.info),encoding="utf-8")

    def test_genuine_bytes_preserved(self):
        dest=self.root/"queue"
        result=stage_bundle(self.source,dest,SHA)
        self.assertEqual(result["source_sha"],SHA)
        self.assertFalse(result["submit_allowed"])
        items=list(dest.iterdir())
        self.assertEqual(len(items),1)
        self.assertEqual((items[0]/"package.msix").read_bytes(),(self.source/"package.msix").read_bytes())

    def test_idempotent_stage(self):
        dest=self.root/"queue"
        stage_bundle(self.source,dest,SHA)
        stage_bundle(self.source,dest,SHA)
        self.assertEqual(len(list(dest.iterdir())),1)

    def test_identical_msix_from_another_factory_is_not_reused(self):
        dest=self.root/"queue"
        stage_bundle(self.source,dest,SHA)
        original=(next(dest.iterdir())/"handoff.json").read_text(encoding="utf-8")
        # Both Factory lanes can independently produce identical MSIX bytes.
        self.info["source_repository"]="https://github.com/shihuiarenjinba-png/AI-Game-Factory"
        self.info["type"]="game"
        self.write_info()
        with self.assertRaisesRegex(ValueError,"provenance"):
            stage_bundle(self.source,dest,SHA)
        self.assertEqual((next(dest.iterdir())/"handoff.json").read_text(encoding="utf-8"),original)

    def test_identical_msix_from_another_commit_is_not_reused(self):
        dest=self.root/"queue"
        stage_bundle(self.source,dest)
        self.info["source_sha"]="b"*40
        self.write_info()
        with self.assertRaisesRegex(ValueError,"provenance"):
            stage_bundle(self.source,dest)
        self.assertEqual(len(list(dest.iterdir())),1)

    def test_changed_source_sha_rejected(self):
        with self.assertRaisesRegex(ValueError,"provenance"):
            validate_bundle(self.source,"b"*40)

    def test_tampered_package_rejected(self):
        with (self.source/"package.msix").open("ab") as f:f.write(b"mutated")
        with self.assertRaisesRegex(ValueError,"hash mismatch"):
            validate_bundle(self.source,SHA)

    def test_3d_factory_requires_game_type(self):
        self.info["source_repository"]="https://github.com/shihuiarenjinba-png/3d-game-factory"
        self.info["type"]="game"
        self.write_info()
        self.assertEqual(validate_bundle(self.source,SHA)["type"],"game")
        self.info["type"]="app"
        self.write_info()
        with self.assertRaisesRegex(ValueError,"factory / product type"):
            validate_bundle(self.source,SHA)

    def test_wrong_product_type_rejected(self):
        self.info["type"]="game"
        self.write_info()
        with self.assertRaisesRegex(ValueError,"factory / product type"):
            validate_bundle(self.source,SHA)

    def test_wrong_embedded_publisher_rejected(self):
        self.info["identity"]["publisher"]="CN=wrong"
        self.write_info()
        with self.assertRaisesRegex(ValueError,"embedded identity"):
            validate_bundle(self.source,SHA)

    def test_extra_file_rejected(self):
        (self.source/"secret.txt").write_text("not allowed")
        with self.assertRaisesRegex(ValueError,"only handoff"):
            validate_bundle(self.source,SHA)

    def test_bad_zip_rejected(self):
        (self.source/"package.msix").write_bytes(b"not-a-package")
        with self.assertRaisesRegex(ValueError,"readable MSIX"):
            validate_bundle(self.source,SHA)

    def test_no_store_approval_or_guess(self):
        result=validate_bundle(self.source,SHA)
        self.assertIsNone(result["store_id"])
        self.assertFalse(result["security_confirmed"])
        self.assertFalse(result["price_approved"])

    def test_traversal_zip_entry_rejected(self):
        with zipfile.ZipFile(self.source/"package.msix","a") as z:z.writestr("../evil.txt",b"bad")
        with self.assertRaisesRegex(ValueError,"unsafe MSIX ZIP entry"):
            validate_bundle(self.source,SHA)

if __name__=="__main__":unittest.main()
