"""Local byte-level evidence checks; fixtures do not prove physical Windows QA."""
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
import zipfile

from scripts.accounting_human_evidence_reader import read_local_accounting_human_evidence
from scripts.accounting_human_qa_gate import (
    AccountingHumanQAHold, SCENARIO_ASSERTIONS, validate_accounting_human_qa,
)
from tests.test_accounting_human_qa_gate import fixture


def _chunk(kind, payload):
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff))


def _png(color, width=1024, height=768):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = (b"\x00" + bytes((color, 0, 0)) * width) * height
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))


def _msix(*, omit=None, bad_manifest=False, extra=None, stored_asset=False):
    manifest = (
        '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
        '<Identity Name="OkinawaDesktopTools.Test" Publisher="CN=Test" Version="1.0.0.0"/>'
        '</Package>'
    )
    if bad_manifest:
        manifest = "<Package><Identity/></Package>"
    parts = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'),
        "AppxBlockMap.xml": (
            '<BlockMap xmlns="http://schemas.microsoft.com/appx/2010/blockmap"/>'),
        "AppxManifest.xml": manifest,
        "Assets/logo.png": b"fixture",
    }
    if omit:
        del parts[omit]
    if extra:
        parts.update(extra)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = (
                zipfile.ZIP_STORED if stored_asset and name == "Assets/logo.png"
                else zipfile.ZIP_DEFLATED
            )
            archive.writestr(info, value)
    return output.getvalue()


class LocalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "screenshots").mkdir()
        self.job, self.evidence = fixture("jp-bookkeeping-desk")
        self.package = self.root / "package.msix"
        self.checker = self.root / "checker.json"
        self.package.write_bytes(_msix())
        self.checker.write_bytes(b'{"status":"MOCK_ONLY"}')
        self.job["package_sha256"] = hashlib.sha256(self.package.read_bytes()).hexdigest()
        self.job["checker_report_sha256"] = hashlib.sha256(self.checker.read_bytes()).hexdigest()
        self.evidence["package_sha256"] = self.job["package_sha256"]
        self.evidence["checker_report_sha256"] = self.job["checker_report_sha256"]
        for index, key in enumerate(SCENARIO_ASSERTIONS, start=1):
            screenshot = _png(index)
            (self.root / "screenshots" / (key + ".png")).write_bytes(screenshot)
            self.evidence["scenarios"][key]["screenshot_sha256"] = hashlib.sha256(screenshot).hexdigest()
        self._save()

    def _save(self):
        (self.root / "evidence.json").write_text(
            json.dumps(self.evidence), encoding="utf-8")

    def _read(self):
        return read_local_accounting_human_evidence(
            self.job, evidence_root=self.root,
            package_path=self.package, checker_report_path=self.checker)

    def _hold(self, code):
        with self.assertRaisesRegex(AccountingHumanQAHold, code):
            self._read()

    def test_exact_bytes_then_pure_contract_still_not_e2e(self):
        evidence = self._read()
        result = validate_accounting_human_qa(
            self.job, fetch_reviewed_windows_evidence=lambda _: evidence)
        self.assertEqual(result["status"], "HUMAN_USABILITY_EVIDENCE_CONTRACT_VALIDATED")
        self.assertFalse(result["e2e_pass"])

    def test_screenshot_tampering(self):
        path = self.root / "screenshots" / "account_search_rent.png"
        path.write_bytes(path.read_bytes() + b"x")
        self._hold("PNG_INVALID")

    def test_screenshot_hash_mismatch(self):
        self.evidence["scenarios"]["account_search_rent"]["screenshot_sha256"] = "f" * 64
        self._save()
        self._hold("SCREENSHOT_MISMATCH")

    def test_same_screenshot_cannot_cover_five_scenarios(self):
        first = (self.root / "screenshots" / "account_search_rent.png").read_bytes()
        path = self.root / "screenshots" / "equipment_classification.png"
        path.write_bytes(first)
        self.evidence["scenarios"]["equipment_classification"]["screenshot_sha256"] = hashlib.sha256(first).hexdigest()
        self._save()
        self._hold("SCREENSHOT_REUSED")

    def test_wrong_resolution(self):
        key = "account_search_rent"
        png = _png(1, width=800)
        (self.root / "screenshots" / (key + ".png")).write_bytes(png)
        self.evidence["scenarios"][key]["screenshot_sha256"] = hashlib.sha256(png).hexdigest()
        self._save()
        self._hold("RESOLUTION")

    def test_package_and_checker_mismatch(self):
        self.package.write_bytes(b"PK\x03\x04changed")
        self._hold("PACKAGE_MISMATCH")
        self.package.write_bytes(_msix())
        self.checker.write_bytes(b"changed")
        self._hold("CHECKER_MISMATCH")


    def _replace_package(self, data):
        self.package.write_bytes(data)
        self.job["package_sha256"] = hashlib.sha256(data).hexdigest()
        self.evidence["package_sha256"] = self.job["package_sha256"]
        self._save()

    def test_pk_magic_without_zip_cannot_pass(self):
        self._replace_package(b"PK\x03\x04mock-not-signed")
        self._hold("MSIX_INVALID")

    def test_zip_missing_appx_manifest_rejected(self):
        self._replace_package(_msix(omit="AppxManifest.xml"))
        self._hold("MSIX_INVALID")

    def test_zip_invalid_manifest_identity_rejected(self):
        self._replace_package(_msix(bad_manifest=True))
        self._hold("MSIX_INVALID")

    def test_zip_path_traversal_rejected(self):
        self._replace_package(_msix(extra={"../outside.txt": b"bad"}))
        self._hold("MSIX_INVALID")

    def test_zip_case_insensitive_duplicate_rejected(self):
        self._replace_package(_msix(extra={"appxmanifest.xml": b"duplicate"}))
        self._hold("MSIX_INVALID")

    def test_zip_corrupted_non_xml_asset_crc_rejected(self):
        # A correct directory and valid XML cannot hide corrupt payload bytes.
        data = _msix(stored_asset=True)
        self.assertEqual(data.count(b"fixture"), 1)
        self._replace_package(data.replace(b"fixture", b"ficture", 1))
        self._hold("MSIX_INVALID")

    def test_zip_claimed_huge_uncompressed_entry_rejected(self):
        # Tamper with central-directory uncompressed size, no large allocation.
        data = bytearray(_msix())
        position = data.rfind(b"PK\x01\x02")
        self.assertGreater(position, 0)
        struct.pack_into("<I", data, position + 24, 0xffffffff)
        self._replace_package(bytes(data))
        self._hold("MSIX_INVALID")

    def test_valid_msix_container_is_not_signature_or_e2e_pass(self):
        self._replace_package(_msix())
        evidence = self._read()
        result = validate_accounting_human_qa(
            self.job, fetch_reviewed_windows_evidence=lambda _: evidence)
        self.assertFalse(result["e2e_pass"])

    def test_duplicate_json_key_fail_closed(self):
        raw = (self.root / "evidence.json").read_text(encoding="utf-8")
        raw = raw.replace('"slug":', '"slug": "duplicate", "slug":', 1)
        (self.root / "evidence.json").write_text(raw, encoding="utf-8")
        self._hold("DUPLICATE_JSON_KEY")

    def test_symlink_screenshot_rejected(self):
        target = self.root / "screenshots" / "account_search_rent.png"
        link = self.root / "screenshots" / "equipment_classification.png"
        link.unlink()
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Windows symlink privilege unavailable")
        self._hold("SYMLINK")


    def _replace_png(self, png, key="account_search_rent"):
        (self.root / "screenshots" / (key + ".png")).write_bytes(png)
        self.evidence["scenarios"][key]["screenshot_sha256"] = (
            hashlib.sha256(png).hexdigest())
        self._save()

    def test_crc_valid_but_invalid_deflate_rejected(self):
        ihdr = struct.pack(">IIBBBBB", 1024, 768, 8, 2, 0, 0, 0)
        png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
               + _chunk(b"IDAT", b"not-a-zlib-stream")
               + _chunk(b"IEND", b""))
        self._replace_png(png)
        self._hold("PNG_INVALID")

    def test_crc_valid_but_invalid_filter_rejected(self):
        ihdr = struct.pack(">IIBBBBB", 1024, 768, 8, 2, 0, 0, 0)
        raw = (b"\x05" + b"\x00" * (1024 * 3)) * 768
        png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
               + _chunk(b"IDAT", zlib.compress(raw))
               + _chunk(b"IEND", b""))
        self._replace_png(png)
        self._hold("PNG_INVALID")

    def test_crc_valid_decompression_overflow_rejected(self):
        ihdr = struct.pack(">IIBBBBB", 1024, 768, 8, 2, 0, 0, 0)
        raw = b"\x00" * ((1024 * 3 + 1) * 768 + 100)
        png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
               + _chunk(b"IDAT", zlib.compress(raw))
               + _chunk(b"IEND", b""))
        self._replace_png(png)
        self._hold("PNG_INVALID")

    def test_crc_valid_truncated_zlib_rejected(self):
        ihdr = struct.pack(">IIBBBBB", 1024, 768, 8, 2, 0, 0, 0)
        raw = (b"\x00" + b"\x00" * (1024 * 3)) * 768
        compressed = zlib.compress(raw)[:-2]
        png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
               + _chunk(b"IDAT", compressed)
               + _chunk(b"IEND", b""))
        self._replace_png(png)
        self._hold("PNG_INVALID")

    def test_crc_valid_nonconsecutive_idat_rejected(self):
        ihdr = struct.pack(">IIBBBBB", 1024, 768, 8, 2, 0, 0, 0)
        raw = (b"\x00" + b"\x00" * (1024 * 3)) * 768
        compressed = zlib.compress(raw)
        split = len(compressed) // 2
        png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
               + _chunk(b"IDAT", compressed[:split])
               + _chunk(b"tEXt", b"Note\x00safe")
               + _chunk(b"IDAT", compressed[split:])
               + _chunk(b"IEND", b""))
        self._replace_png(png)
        self._hold("PNG_INVALID")

    def test_valid_consecutive_idat_and_ancillary_accepted(self):
        ihdr = struct.pack(">IIBBBBB", 1024, 768, 8, 2, 0, 0, 0)
        raw = (b"\x00" + b"\x02\x00\x00" * 1024) * 768
        compressed = zlib.compress(raw)
        split = len(compressed) // 2
        png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
               + _chunk(b"tEXt", b"Note\x00safe")
               + _chunk(b"IDAT", compressed[:split])
               + _chunk(b"IDAT", compressed[split:])
               + _chunk(b"IEND", b""))
        self._replace_png(png)
        self.assertEqual(self._read()["slug"], self.job["slug"])

    def test_crc_valid_unsupported_indexed_png_rejected(self):
        ihdr = struct.pack(">IIBBBBB", 1024, 768, 8, 3, 0, 0, 0)
        png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
               + _chunk(b"PLTE", b"\x00\x00\x00")
               + _chunk(b"IDAT", zlib.compress(b"\x00" * 1024))
               + _chunk(b"IEND", b""))
        self._replace_png(png)
        self._hold("PNG_INVALID")


if __name__ == "__main__":
    unittest.main()
