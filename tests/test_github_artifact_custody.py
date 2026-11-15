"""Offline fail-closed tests of independent artifact API + local byte custody."""
import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from scripts.github_artifact_custody import verify_custody
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_real_msix_transport_failclosed import authorize_transport

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

    def test_custody_to_transport_boundary_fail_closed(self):
        # Synthetic MSIX bytes test the real handoff contract, not Store/GUI readiness.
        source = "d1108d12f7d1697af30400f97c7db39cba5e6791"
        identity = dict(request_id="app-file-integrity-ledger-d1108d12f7d1",
            source_sha=source, verified_source_sha=source, expected_head_sha=source,
            name="OkinawaDesktopTools.FileIntegrityLedger",
            publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC",
            store_id="9PGZ445SR5GM", package_version_gate="PASS",
            signature_status="SIGNED")
        version = "1.2.3.4"  # Synthetic fixture only; NOT an approved product version.
        with zipfile.ZipFile(self.local, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("AppxManifest.xml",
                '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
                '<Identity Name="OkinawaDesktopTools.FileIntegrityLedger" '
                'Publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC" '
                'Version="1.2.3.4"/></Package>')
        digest = hashlib.sha256(self.local.read_bytes()).hexdigest()
        approval = {k: identity[k] for k in ("request_id", "source_sha", "name", "publisher", "store_id")}
        approval.update(package_version=version, approved=True, msix_sha256=digest)
        receipt = dict(approval)
        receipt.update(local_sha256=digest, artifact_kind="REAL_MSIX",
            github_backlog_status="VERIFIED", local_pull_status="VERIFIED",
            run_id=123, artifact_id=456)
        self.expected.update(source_sha=source, msix_sha256=digest)
        self.run["head_sha"] = source
        self.artifact["workflow_run"]["head_sha"] = source
        self.zip = self.archive(self.local.read_bytes())
        custody = self.check()
        self.assertEqual(custody["status"], "CUSTODY_VERIFIED_ONLY")
        result = authorize_transport(identity, approval, self.local, receipt, custody)
        self.assertEqual(result["status"], "TRANSPORT_PREFLIGHT_PASS_ONLY")
        self.assertFalse(result["e2e_pass"])
        self.assertEqual(result["checker"], "NOT_VERIFIED")
        self.assertEqual(result["gui"], "NOT_VERIFIED")
        # Producer-controlled VERIFIED strings cannot replace independent custody.
        self.assertEqual(authorize_transport(identity, approval, self.local, receipt)["status"], "HOLD")
        # A changed downloaded artifact must not yield a usable custody receipt.
        self.zip = self.archive(b"tampered")
        rejected = self.check()
        self.assertEqual(rejected["status"], "HOLD")
        self.assertEqual(authorize_transport(identity, approval, self.local, receipt, rejected)["status"], "HOLD")
        # Even valid custody must not override a missing official version approval.
        self.zip = self.archive(self.local.read_bytes())
        approval["approved"] = False
        self.assertEqual(authorize_transport(identity, approval, self.local, receipt, custody)["reason"],
                         "VERSION_NOT_APPROVED")

if __name__ == "__main__":
    unittest.main()
