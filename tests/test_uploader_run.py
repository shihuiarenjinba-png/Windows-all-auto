from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.error

from uploader.core import UploadError
from uploader.run import github_download, resolve_job_config


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


if __name__ == "__main__": unittest.main()
