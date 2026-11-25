from __future__ import annotations

import tempfile
import unittest
import contextlib
import io
import json
import hashlib
import zipfile
from pathlib import Path
from unittest.mock import patch
import urllib.error

from uploader.core import UploadError
from uploader.run import github_download, main, resolve_job_config


class Response:
    status = 200
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, size=-1):
        if not self.payload: return b""
        chunk, self.payload = self.payload[:size], self.payload[size:]
        return chunk


class UploaderRunTests(unittest.TestCase):
    def test_github_download_pins_repository_ref_and_path_and_checks_size(self):
        seen = {}
        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            seen["timeout"] = timeout
            return Response(b"msix-payload")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "candidate.msix"
            with patch("uploader.run.urllib.request.urlopen", fake_urlopen):
                github_download("owner/repo", "a" * 40, "artifacts/candidate.msix", "secret-token", target, max_bytes=100)
            self.assertIn("repos/owner/repo/contents/artifacts/candidate.msix?ref=" + "a" * 40, seen["url"])
            self.assertEqual(seen["auth"], "Bearer secret-token")
            self.assertEqual(seen["timeout"], 60)
            self.assertEqual(target.read_bytes(), b"msix-payload")

    def test_github_download_rejects_size_overflow_and_cleans_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "candidate.msix"
            with patch("uploader.run.urllib.request.urlopen", lambda *_a, **_k: Response(b"0123456789")):
                with self.assertRaisesRegex(UploadError, "max_bytes"):
                    github_download("owner/repo", "a" * 40, "candidate.msix", None, target, max_bytes=4)
            self.assertFalse(target.exists())

    def test_config_key_resolves_inside_config_folder(self):
        resolved = resolve_job_config(product_key="data-contract-auditor")
        self.assertEqual(resolved.name, "data-contract-auditor.job.json")
        with self.assertRaisesRegex(UploadError, "lowercase config slug"):
            resolve_job_config(product_key="../outside")

    def test_not_found_and_network_failures_have_stable_codes(self):
        def missing(*_args, **_kwargs):
            raise urllib.error.HTTPError("url", 404, "missing", {}, None)
        with tempfile.TemporaryDirectory() as tmp, patch("uploader.run.urllib.request.urlopen", missing):
            with self.assertRaisesRegex(UploadError, "GitHub download HTTP 404") as caught:
                github_download("owner/repo", "ref", "a.msix", None, Path(tmp) / "a.msix")
            self.assertEqual(caught.exception.code, "FILE_NOT_FOUND")

    def test_failed_download_still_writes_complete_execution_receipt_without_sha_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("sys.argv", ["uploader.run", "--product", "data-contract-auditor", "--workdir", tmp]), \
                 patch("uploader.run.github_download", side_effect=UploadError("FILE_NOT_FOUND", "missing")), \
                 contextlib.redirect_stdout(io.StringIO()):
                code = main()
            self.assertEqual(code, 2)
            receipt = json.loads((Path(tmp) / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["product_id"], "9PDL4ZWSB45P")
            self.assertEqual(receipt["submission_id"], "1152921505702212222")
            self.assertEqual(receipt["package_file_name"], "DataContractSchemaDrift_1.0.0.0_x64.msix")
            self.assertIsNone(receipt["sha256"])
            self.assertIsNone(receipt["partner_center_sha256"])
            self.assertEqual(receipt["result"], "FAILED")
            self.assertEqual(receipt["partner_center_confirmation"], "NOT_CONFIRMED")
            durable = list((Path(tmp) / "durable-ledger" / "receipts").rglob("*.json"))
            self.assertEqual(len(durable), 1)

    def test_unapproved_live_run_stops_before_download_and_writes_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("sys.argv", ["uploader.run", "--product", "data-contract-auditor", "--workdir", tmp, "--execute"]), \
                 patch("uploader.run.github_download") as download, \
                 contextlib.redirect_stdout(io.StringIO()):
                code = main()
            self.assertEqual(code, 2)
            download.assert_not_called()
            receipt = json.loads((Path(tmp) / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["result"], "FAILED")
            self.assertEqual(receipt["details"]["error_code"], "UPLOAD_NOT_APPROVED")
            self.assertIsNone(receipt["sha256"])


    def test_local_package_dry_run_uses_exact_file_and_skips_github_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "ExactCandidate_1.2.3.4_x64.msix"
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr(
                    "AppxManifest.xml",
                    '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
                    <Identity Name="Example.Identity" Publisher="CN=Example" Version="1.2.3.4" ProcessorArchitecture="x64" />
                    </Package>''',
                )
                archive.writestr("payload.bin", b"exact-package-bytes")
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            config = {
                "schema_version": 1,
                "product_name": "Example Product",
                "product_id": "9P1234567890",
                "submission_id": "1152921505700000000",
                "repository": "owner/repo",
                "ref": "a" * 40,
                "path": "store-output/ExactCandidate_1.2.3.4_x64.msix",
                "version": "1.2.3.4",
                "destination": "microsoft_partner_center_existing_draft",
                "submission_route": "msix_pwa_app",
                "identity_name": "Example.Identity",
                "publisher": "CN=Example",
                "architecture": "x64",
                "known_warnings": [],
                "expected_existing_package_names": [],
                "expected_replaced_package_names": [],
                "upload_approved": False,
                "expected_sha256": digest,
                "max_bytes": 1000000,
            }
            config_path = root / "job.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            workdir = root / "work"
            stdout = io.StringIO()
            with patch("sys.argv", [
                "uploader.run", "--config", str(config_path),
                "--package", str(package), "--workdir", str(workdir),
            ]), patch("uploader.run.github_download") as download, contextlib.redirect_stdout(stdout):
                code = main()
            self.assertEqual(code, 0)
            download.assert_not_called()
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "DRY_RUN")
            receipt = json.loads((workdir / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["sha256"], digest)
            self.assertEqual(receipt["package_file_name"], package.name)
            self.assertEqual(receipt["partner_center_confirmation"], "NOT_ATTEMPTED")

    def test_local_package_rejects_a_filename_other_than_the_registered_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "wrong-name.msix"
            package.write_bytes(b"not-read-because-name-must-match")
            config = {
                "schema_version": 1,
                "product_name": "Example Product",
                "product_id": "9P1234567890",
                "submission_id": "1152921505700000000",
                "repository": "owner/repo",
                "ref": "a" * 40,
                "path": "store-output/ExactCandidate_1.2.3.4_x64.msix",
                "version": "1.2.3.4",
                "destination": "microsoft_partner_center_existing_draft",
                "submission_route": "msix_pwa_app",
                "identity_name": "Example.Identity",
                "publisher": "CN=Example",
                "architecture": "x64",
                "known_warnings": [],
                "expected_existing_package_names": [],
                "expected_replaced_package_names": [],
                "upload_approved": False,
                "expected_sha256": "a" * 64,
                "max_bytes": 1000000,
            }
            config_path = root / "job.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            workdir = root / "work"
            with patch("sys.argv", [
                "uploader.run", "--config", str(config_path),
                "--package", str(package), "--workdir", str(workdir),
            ]), contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = main()
            self.assertEqual(code, 2)
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["error_code"], "PACKAGE_FILENAME_MISMATCH")
            self.assertFalse((workdir / "ledger.sqlite3").exists())


if __name__ == "__main__": unittest.main()
