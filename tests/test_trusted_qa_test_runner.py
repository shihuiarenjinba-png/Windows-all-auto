from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts.trusted_qa_test_runner import _manifest_binding, process_start


class TrustedQATestRunnerTests(unittest.TestCase):
    def setUp(self):
        local_tmp = Path.cwd() / ".test-tmp"
        local_tmp.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=local_tmp)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_python_process_start_accepts_clean_exit(self):
        artifact = self.root / "product.py"
        artifact.write_text("print('PRODUCT_OK')\n", encoding="utf-8")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        self.assertEqual(process_start(artifact, digest, observation_seconds=1), 0)

    def test_manifest_binding_requires_exact_packaged_executable(self):
        artifact = self.root / "VFS" / "Product" / "Product.exe"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"MZ")
        (self.root / "AppxManifest.xml").write_text(
            """<Package xmlns='http://schemas.microsoft.com/appx/manifest/foundation/windows10'>
<Identity Name='Example.Product' Publisher='CN=Example' Version='1.2.3.0'/>
<Applications><Application Id='App' Executable='VFS\\Product\\Product.exe'/></Applications>
</Package>""",
            encoding="utf-8",
        )
        self.assertEqual(_manifest_binding(artifact), {
            "package_root": str(self.root.resolve()),
            "package_name": "Example.Product",
            "version": "1.2.3.0",
            "application_id": "App",
        })

    def test_process_start_rehashes_before_launch(self):
        artifact = self.root / "product.py"
        artifact.write_text("print('NOT_RUN')\n", encoding="utf-8")
        self.assertEqual(process_start(artifact, "0" * 64, observation_seconds=1), 2)


if __name__ == "__main__":
    unittest.main()
