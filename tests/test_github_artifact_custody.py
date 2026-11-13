"""Offline fail-closed tests of independent artifact API + local byte custody."""
import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from scripts.github_artifact_custody import verify_custody

class CustodyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name) / "actual.msix"
        self.local.write_bytes(b"fixture-not-real-msix")
        self.digest = hashlib.sha256(self.local.read_bytes()).hexdigest()
        self.expected = dict(repository="example/repo", run_id=123, artifact_id=456,
                             source_sha="a"*40, artifact_name="actual-package", msix_sha256=self.digest)
        self.run = dict(head_sha="a"*40, status="completed", conclusion="success")
        self.artifact = dict(id=456, name="actual-package", expired=False,
                             workflow_run=dict(id=123, head_sha="a"*40))
        self.zip = self.archive(self.local.read_bytes())
    def archive(self, data):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("actual.msix", data)
        return buf.getvalue()
    def check(self):
        def get_json(url):
            return self.run if "/runs/" in url else self.artifact
        return verify_custody(self.expected, self.local, get_json, lambda url: self.zip)
    def test_matching_bytes_never_e2e(self):
        result = self.check()
        self.assertEqual(result["status"], "CUSTODY_VERIFIED_ONLY")
        self.assertFalse(result["e2e_pass"])
        self.assertEqual(result["signature"], "NOT_VERIFIED")
    def test_run_head_drift(self):
        self.run["head_sha"] = "b"*40
        self.assertEqual(self.check()["status"], "HOLD")
    def test_run_failed(self):
        self.run["conclusion"] = "failure"
        self.assertEqual(self.check()["status"], "HOLD")
    def test_artifact_wrong_run(self):
        self.artifact["workflow_run"]["id"] = 999
        self.assertEqual(self.check()["status"], "HOLD")
    def test_artifact_expired(self):
        self.artifact["expired"] = True
        self.assertEqual(self.check()["status"], "HOLD")
    def test_wrong_artifact_id(self):
        self.artifact["id"] = 789
        self.assertEqual(self.check()["status"], "HOLD")
    def test_artifact_bytes_mismatch(self):
        self.zip = self.archive(b"different")
        self.assertEqual(self.check()["reason"], "INDEPENDENT_BYTES_MISMATCH")
    def test_local_bytes_mismatch(self):
        self.local.write_bytes(b"changed")
        self.assertEqual(self.check()["reason"], "INDEPENDENT_BYTES_MISMATCH")
    def test_missing_local(self):
        self.local.unlink()
        self.assertEqual(self.check()["status"], "HOLD")
    def test_no_approved_digest(self):
        self.expected["msix_sha256"] = ""
        self.assertEqual(self.check()["status"], "HOLD")
    def test_missing_api(self):
        self.assertEqual(verify_custody(self.expected, self.local, lambda url: {}, lambda url: b"")["status"], "HOLD")
    def test_zip_extra_payload(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("actual.msix", self.local.read_bytes())
            z.writestr("unexpected.txt", "x")
        self.zip = buf.getvalue()
        self.assertEqual(self.check()["status"], "HOLD")

if __name__ == "__main__":
    unittest.main()
