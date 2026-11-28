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


BASE_CONTENT_TYPES = b'''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml" />
</Types>'''


def package(path: Path, *, signature: bytes | None = None, payload: bytes = b"payload",
            content_types: bytes | None = None) -> str:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AppxManifest.xml", MANIFEST)
        archive.writestr("AppxBlockMap.xml", b"blockmap")
        archive.writestr("Assets/logo.png", payload)
        if content_types is not None:
            archive.writestr("[Content_Types].xml", content_types)
        if signature is not None:
            archive.writestr("AppxSignature.p7x", signature)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signed_package_with_signature_metadata(path: Path) -> None:
    content_types = b'''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
      <Default Extension="xml" ContentType="application/xml" />
      <Default Extension="p7x" ContentType="application/vnd.ms-appx.signature" />
      <Default Extension="cat" ContentType="application/vnd.ms-pkiseccat" />
      <Override PartName="/AppxMetadata/CodeIntegrity.cat" ContentType="application/vnd.ms-appx.codeintegrity" />
    </Types>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AppxManifest.xml", MANIFEST)
        archive.writestr("AppxBlockMap.xml", b"blockmap")
        archive.writestr("Assets/logo.png", b"payload")
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("AppxSignature.p7x", b"test-signature")
        archive.writestr("AppxMetadata/CodeIntegrity.cat", b"test-ci-catalog")


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

    def test_allows_only_signature_metadata_changes_not_payload_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, derived = root / "source.msix", root / "signed.msix"
            expected = package(source, content_types=BASE_CONTENT_TYPES)
            signed_package_with_signature_metadata(derived)
            report = verify_test_signed_derivative(source=source, derived=derived,
                                                   expected_source_sha256=expected,
                                                   expected_identity=IDENTITY)
            self.assertEqual(set(report["added_members"]),
                             {"AppxSignature.p7x", "AppxMetadata/CodeIntegrity.cat"})
            self.assertEqual(report["changed_signature_metadata_members"], ["[Content_Types].xml"])
            self.assertFalse(report["changed_payload_members"])


if __name__ == "__main__":
    unittest.main()
