from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from all_auto.msix_derivative import DerivativeVerificationError, verify_test_signed_derivative


IDENTITY = {"Name": "Example.Product", "Publisher": "CN=Example.Publisher",
            "Version": "1.2.3.0", "ProcessorArchitecture": "x64"}
MANIFEST = ('''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'''
            '''<Identity Name="Example.Product" Publisher="CN=Example.Publisher" '''
            '''Version="1.2.3.0" ProcessorArchitecture="x64" /></Package>''')


def package(path: Path, *, signature: bytes | None = None, payload: bytes = b"payload") -> str:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AppxManifest.xml", MANIFEST)
        archive.writestr("AppxBlockMap.xml", b"blockmap")
        archive.writestr("Assets/logo.png", payload)
        if signature is not None:
            archive.writestr("AppxSignature.p7x", signature)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MsixDerivativeTests(unittest.TestCase):
    def test_signature_only_derivative_passes_and_binds_both_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, derived = root / "source.msix", root / "signed.msix"
            expected = package(source)
            package(derived, signature=b"test certificate signature")
            report = verify_test_signed_derivative(source=source, derived=derived,
                                                   expected_source_sha256=expected,
                                                   expected_identity=IDENTITY)
            self.assertEqual(report["status"], "SIGNATURE_ONLY_DERIVATIVE_VERIFIED")
            self.assertEqual(report["source"]["sha256"], expected)
            self.assertNotEqual(report["derived"]["sha256"], expected)
            self.assertEqual(report["added_members"], ["AppxSignature.p7x"])
            self.assertFalse(report["changed_payload_members"])
            self.assertTrue(report["diagnostic_only"])

    def test_rejects_payload_or_manifest_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, changed = root / "source.msix", root / "changed.msix"
            expected = package(source)
            package(changed, signature=b"signature", payload=b"modified")
            with self.assertRaisesRegex(DerivativeVerificationError, "members changed"):
                verify_test_signed_derivative(source=source, derived=changed,
                                              expected_source_sha256=expected,
                                              expected_identity=IDENTITY)

    def test_rejects_wrong_source_hash_missing_signature_and_extra_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, derived = root / "source.msix", root / "derived.msix"
            expected = package(source)
            package(derived, signature=b"sig")
            with self.assertRaisesRegex(DerivativeVerificationError, "source package SHA"):
                verify_test_signed_derivative(source=source, derived=derived,
                                              expected_source_sha256="0" * 64,
                                              expected_identity=IDENTITY)
            package(derived)
            with self.assertRaisesRegex(DerivativeVerificationError, "no non-empty"):
                verify_test_signed_derivative(source=source, derived=derived,
                                              expected_source_sha256=expected,
                                              expected_identity=IDENTITY)


if __name__ == "__main__":
    unittest.main()
