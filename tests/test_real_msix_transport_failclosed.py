"""Fail-closed transport boundary: no synthetic package may become a local QA receipt."""
import hashlib
import json
import re
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

SHA = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
NS = "{http://schemas.microsoft.com/appx/manifest/foundation/windows10}"

def authorize_transport(identity, approval, package_path, receipt):
    """Return a bounded preflight receipt; never assert GUI/checker success."""
    def hold(reason):
        return {"status": "HOLD", "reason": reason}
    if not isinstance(identity, dict) or not isinstance(approval, dict) or not isinstance(receipt, dict):
        return hold("INVALID_EVIDENCE")
    source = identity.get("source_sha")
    if not isinstance(source, str) or not SHA.fullmatch(source):
        return hold("SOURCE_INVALID")
    if identity.get("verified_source_sha") != source or identity.get("expected_head_sha") != source:
        return hold("SOURCE_DRIFT")
    if identity.get("package_version_gate") != "PASS":
        return hold("VERSION_GATE_NOT_PASS")
    if identity.get("signature_status") == "PRE_IDENTITY_EXE_NOT_MSIX":
        return hold("EXE_NOT_MSIX")
    for key in ("request_id", "source_sha", "name", "publisher", "store_id"):
        if not identity.get(key) or approval.get(key) != identity[key] or receipt.get(key) != identity[key]:
            return hold("PROVENANCE_MISMATCH_" + key)
    version = approval.get("package_version")
    if approval.get("approved") is not True or not isinstance(version, str) or not VERSION.fullmatch(version):
        return hold("VERSION_NOT_APPROVED")
    if receipt.get("package_version") != version:
        return hold("RECEIPT_VERSION_MISMATCH")
    p = Path(package_path)
    if p.suffix.lower() != ".msix" or not p.is_file():
        return hold("REAL_MSIX_MISSING")
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    if approval.get("msix_sha256") != digest or receipt.get("msix_sha256") != digest:
        return hold("PACKAGE_DIGEST_MISMATCH")
    if receipt.get("artifact_kind") != "REAL_MSIX" or receipt.get("github_backlog_status") != "VERIFIED":
        return hold("BACKLOG_NOT_VERIFIED")
    if receipt.get("local_pull_status") != "VERIFIED" or receipt.get("local_sha256") != digest:
        return hold("LOCAL_BYTES_NOT_VERIFIED")
    try:
        with zipfile.ZipFile(p) as z:
            members = z.namelist()
            if len(members) != len(set(members)) or z.testzip() is not None:
                return hold("PACKAGE_CORRUPT")
            if "AppxManifest.xml" not in members or "[Content_Types].xml" not in members:
                return hold("PACKAGE_STRUCTURE_INVALID")
            if z.getinfo("AppxManifest.xml").file_size > 1024 * 1024:
                return hold("MANIFEST_OVERSIZED")
            node = ET.fromstring(z.read("AppxManifest.xml")).find(NS + "Identity")
            if node is None or any(node.get(field) != value for field, value in
                                   (("Name", identity["name"]), ("Publisher", identity["publisher"]), ("Version", version))):
                return hold("MANIFEST_IDENTITY_MISMATCH")
    except (OSError, ValueError, zipfile.BadZipFile, ET.ParseError, RuntimeError):
        return hold("INVALID_MSIX")
    return {"status": "TRANSPORT_PREFLIGHT_PASS_ONLY", "msix_sha256": digest,
            "checker": "NOT_VERIFIED", "gui": "NOT_VERIFIED", "e2e_pass": False}

class TransportRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "package.msix"
        self.identity = dict(request_id="app-file-integrity-ledger-d1108d12f7d1",
            source_sha="d1108d12f7d1697af30400f97c7db39cba5e6791",
            verified_source_sha="d1108d12f7d1697af30400f97c7db39cba5e6791",
            expected_head_sha="d1108d12f7d1697af30400f97c7db39cba5e6791",
            name="OkinawaDesktopTools.FileIntegrityLedger",
            publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC",
            store_id="9PGZ445SR5GM", package_version_gate="PASS", signature_status="SIGNED")
        self.approval = {k:self.identity[k] for k in ("request_id","source_sha","name","publisher","store_id")}
        self.approval.update(package_version="1.2.3.4", approved=True)
        with zipfile.ZipFile(self.path, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("AppxManifest.xml", '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="OkinawaDesktopTools.FileIntegrityLedger" Publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC" Version="1.2.3.4"/></Package>')
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.approval["msix_sha256"] = digest
        self.receipt = {k:self.identity[k] for k in ("request_id","source_sha","name","publisher","store_id")}
        self.receipt.update(package_version="1.2.3.4", msix_sha256=digest, local_sha256=digest,
            artifact_kind="REAL_MSIX", github_backlog_status="VERIFIED", local_pull_status="VERIFIED")
    def check(self):
        return authorize_transport(self.identity, self.approval, self.path, self.receipt)
    def test_mock_only_preflight_never_e2e(self):
        self.assertEqual(self.check()["status"], "TRANSPORT_PREFLIGHT_PASS_ONLY")
        self.assertFalse(self.check()["e2e_pass"])
    def test_actual_identity_hold(self):
        self.identity["package_version_gate"] = "HOLD"
        self.identity["signature_status"] = "PRE_IDENTITY_EXE_NOT_MSIX"
        self.assertEqual(self.check()["status"], "HOLD")
    def test_malformed_version_rejected(self):
        self.approval["package_version"] = "1.2.3.x"
        self.receipt["package_version"] = "1.2.3.x"
        self.assertEqual(self.check()["reason"], "VERSION_NOT_APPROVED")
    def test_no_version(self):
        del self.approval["package_version"]
        self.assertEqual(self.check()["status"], "HOLD")
    def test_source_drift(self):
        self.identity["verified_source_sha"] = "0"*40
        self.assertEqual(self.check()["status"], "HOLD")
    def test_request_mismatch(self):
        self.receipt["request_id"] = "wrong"
        self.assertEqual(self.check()["status"], "HOLD")
    def test_no_backlog(self):
        self.receipt["github_backlog_status"] = "PENDING"
        self.assertEqual(self.check()["status"], "HOLD")
    def test_no_local_receipt(self):
        self.receipt["local_pull_status"] = "MISSING"
        self.assertEqual(self.check()["status"], "HOLD")
    def test_local_bytes_mismatch(self):
        self.receipt["local_sha256"] = "0"*64
        self.assertEqual(self.check()["status"], "HOLD")
    def test_exe_rejected(self):
        self.path = self.path.with_suffix(".exe")
        self.path.write_bytes(b"exe")
        self.assertEqual(self.check()["status"], "HOLD")
    def test_manifest_mismatch(self):
        with zipfile.ZipFile(self.path, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("AppxManifest.xml", '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="wrong" Publisher="wrong" Version="1.2.3.4"/></Package>')
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.approval["msix_sha256"] = digest
        self.receipt["msix_sha256"] = self.receipt["local_sha256"] = digest
        self.assertEqual(self.check()["reason"], "MANIFEST_IDENTITY_MISMATCH")
if __name__ == "__main__":
    unittest.main()
