"""Fail-closed transport boundary: no synthetic package may become a local QA receipt."""
import hashlib
import json
import re
import struct
import zlib
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

SHA = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
NS = "{http://schemas.microsoft.com/appx/manifest/foundation/windows10}"

def authorize_transport(identity, approval, package_path, receipt, custody=None):
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
    # The producer's VERIFIED strings alone do not prove custody.
    if not isinstance(custody, dict) or custody.get("status") != "CUSTODY_VERIFIED_ONLY":
        return hold("INDEPENDENT_CUSTODY_REQUIRED")
    if custody.get("e2e_pass") is not False or custody.get("msix_sha256") != digest:
        return hold("CUSTODY_SCOPE_OR_DIGEST_MISMATCH")
    if any(type(custody.get(k)) is not int or custody[k] <= 0 or receipt.get(k) != custody[k]
           for k in ("run_id", "artifact_id")):
        return hold("CUSTODY_RUN_ARTIFACT_MISMATCH")
    try:
        with zipfile.ZipFile(p) as z:
            members = z.namelist()
            if len(members) != len(set(members)) or z.testzip() is not None:
                return hold("PACKAGE_CORRUPT")
            if "AppxManifest.xml" not in members or "[Content_Types].xml" not in members:
                return hold("PACKAGE_STRUCTURE_INVALID")
            if z.getinfo("AppxManifest.xml").file_size > 1024 * 1024:
                return hold("MANIFEST_OVERSIZED")
            required_assets = {"StoreLogo.png": (50, 50), "Square150.png": (150, 150), "Square44.png": (44, 44)}
            for asset, expected_size in required_assets.items():
                matches = [n for n in members if n.rsplit("/", 1)[-1] == asset]
                if len(matches) != 1:
                    return hold("STORE_ASSET_MISSING_OR_DUPLICATE")
                info = z.getinfo(matches[0])
                if info.file_size > 10 * 1024 * 1024:
                    return hold("STORE_ASSET_OVERSIZED")
                raw = z.read(matches[0])
                if len(raw) < 45 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
                    return hold("STORE_ASSET_INVALID_PNG")
                if struct.unpack(">II", raw[16:24]) != expected_size:
                    return hold("STORE_ASSET_DIMENSIONS_MISMATCH")
                if zlib.crc32(raw[12:29]) != struct.unpack(">I", raw[29:33])[0]:
                    return hold("STORE_ASSET_INVALID_PNG")
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
            for asset, size in (("StoreLogo.png", 50), ("Square150.png", 150), ("Square44.png", 44)):
                ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
                chunk = b"IHDR" + ihdr
                png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + chunk + struct.pack(">I", zlib.crc32(chunk))
                z.writestr("Assets/" + asset, png + b"synthetic-fixture-not-production")
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("AppxManifest.xml", '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="OkinawaDesktopTools.FileIntegrityLedger" Publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC" Version="1.2.3.4"/></Package>')
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.approval["msix_sha256"] = digest
        self.receipt = {k:self.identity[k] for k in ("request_id","source_sha","name","publisher","store_id")}
        self.receipt.update(package_version="1.2.3.4", msix_sha256=digest, local_sha256=digest,
            artifact_kind="REAL_MSIX", github_backlog_status="VERIFIED", local_pull_status="VERIFIED",
            run_id=12345, artifact_id=67890)
        self.custody = dict(status="CUSTODY_VERIFIED_ONLY", e2e_pass=False,
            msix_sha256=digest, run_id=12345, artifact_id=67890)
    def check(self):
        return authorize_transport(self.identity, self.approval, self.path, self.receipt, self.custody)
    def test_mock_only_preflight_never_e2e(self):
        self.assertEqual(self.check()["status"], "TRANSPORT_PREFLIGHT_PASS_ONLY")
        self.assertFalse(self.check()["e2e_pass"])
    def test_missing_store_asset_fails_closed(self):
        with zipfile.ZipFile(self.path, "r") as z:
            entries = [(i.filename, z.read(i.filename)) for i in z.infolist() if not i.filename.endswith("Square44.png")]
        with zipfile.ZipFile(self.path, "w") as z:
            for name, data in entries:
                z.writestr(name, data)
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.approval["msix_sha256"] = self.receipt["msix_sha256"] = self.receipt["local_sha256"] = self.custody["msix_sha256"] = digest
        self.assertEqual(self.check()["reason"], "STORE_ASSET_MISSING_OR_DUPLICATE")
    def test_self_reported_verified_is_not_independent_custody(self):
        result = authorize_transport(self.identity, self.approval, self.path, self.receipt)
        self.assertEqual(result["reason"], "INDEPENDENT_CUSTODY_REQUIRED")
    def test_custody_digest_mismatch(self):
        self.custody["msix_sha256"] = "0" * 64
        self.assertEqual(self.check()["reason"], "CUSTODY_SCOPE_OR_DIGEST_MISMATCH")
    def test_custody_run_mismatch(self):
        self.receipt["run_id"] = 999
        self.assertEqual(self.check()["reason"], "CUSTODY_RUN_ARTIFACT_MISMATCH")
    def test_custody_claims_e2e(self):
        self.custody["e2e_pass"] = True
        self.assertEqual(self.check()["reason"], "CUSTODY_SCOPE_OR_DIGEST_MISMATCH")
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
        with zipfile.ZipFile(self.path, "r") as z:
            entries = [(i.filename, z.read(i.filename)) for i in z.infolist()]
        with zipfile.ZipFile(self.path, "w") as z:
            for name, data in entries:
                if name == "AppxManifest.xml":
                    data = b'<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="wrong" Publisher="wrong" Version="1.2.3.4"/></Package>'
                z.writestr(name, data)
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.approval["msix_sha256"] = digest
        self.receipt["msix_sha256"] = self.receipt["local_sha256"] = digest
        # Keep independent custody evidence consistent with the deliberately altered fixture.
        # Otherwise the digest gate correctly rejects before manifest validation is reached.
        self.custody["msix_sha256"] = digest
        self.assertEqual(self.check()["reason"], "MANIFEST_IDENTITY_MISMATCH")
class CurrentLedgerGateTests(unittest.TestCase):
    def test_current_delivery_queue_cannot_enter_transport_without_binding_and_version(self):
        root = Path(__file__).resolve().parents[1]
        queue = json.loads((root / "ops/completion_rush_queue_20261116.json").read_text(encoding="utf-8"))
        ledger = json.loads((root / "ops/active_e2e_handoff.json").read_text(encoding="utf-8"))
        for product in ("Focus Session Desk", "File Integrity Ledger"):
            item = next(p for p in queue["priority"] if p["product"] == product)
            self.assertEqual(item["hold_class"], "DELIVERY_HOLD")
            self.assertIsNone(item["package_version"])
            self.assertIs(item["real_msix"], False)
            self.assertEqual(item["current_source_identity_binding_status"],
                             "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
            identity = {
                "request_id": "ledger-fixture",
                "source_sha": item["source_sha"],
                "verified_source_sha": item["store_assets_branch_head"],
                "expected_head_sha": item["source_sha"],
                "package_version_gate": "HOLD",
            }
            result = authorize_transport(identity, {}, Path("unused.msix"), {}, None)
            self.assertEqual(result["status"], "HOLD")
            self.assertEqual(result["reason"], "SOURCE_DRIFT")
        self.assertEqual(ledger["e2e_status"], "HOLD")
        self.assertIs(ledger["e2e_pass"], False)
        self.assertIs(ledger["store_submission_allowed"], False)
        self.assertIs(ledger["certification_allowed"], False)
        self.assertIs(ledger["publish_allowed"], False)
        latest = ledger["latest_transport_reconciliation"]
        self.assertEqual(latest["central_tested_head_sha"], "6cdde02db4cce115c8b61c8601abc529caef8870")
        self.assertEqual(len(latest["exact_head_ci"]), 3)
        self.assertTrue(all(x["conclusion"] == "success" for x in latest["exact_head_ci"]))
        self.assertTrue(ledger["active_product_is_historical"])
        self.assertEqual(ledger["current_priority_products"][0]["product"], "Focus Session Desk")
        self.assertEqual(ledger["current_priority_products"][1]["product"], "File Integrity Ledger")
        file_item = next(p for p in queue["priority"] if p["product"] == "File Integrity Ledger")
        self.assertEqual(file_item["current_stack_revalidation"]["status"], "PASS_EXACT_HEAD_CI_AFTER_STACK")


    def test_latest_reconciliation_keeps_focus_file_version_and_source_gates_held(self):
        root = Path(__file__).resolve().parents[1]
        ledger = json.loads((root / "ops/active_e2e_handoff.json").read_text(encoding="utf-8"))
        recon = json.loads((root / "ops/focus_file_transport_reconciliation_20261123.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["e2e_status"], "HOLD")
        self.assertIs(ledger["e2e_pass"], False)
        self.assertEqual(ledger["windows_e2e_custody_reconciliation"]["pr165_tested_head_sha"],
                         "6cdde02db4cce115c8b61c8601abc529caef8870")
        self.assertEqual(ledger["windows_e2e_custody_reconciliation"]["approved_version"], "UNVERIFIED")
        self.assertEqual(recon["version_discovery"]["decision"],
                         "KEEP_VERSION_HOLD__DO_NOT_INFER_OR_WRITE_VERSION")
        self.assertEqual(recon["first_unconnected_interval"]["status"],
                         "BLOCKED_BEFORE_REAL_MSIX_BUILD")
        self.assertIs(ledger["store_submission_allowed"], False)
        self.assertIs(ledger["certification_allowed"], False)
        self.assertIs(ledger["publish_allowed"], False)

if __name__ == "__main__":
    unittest.main()
