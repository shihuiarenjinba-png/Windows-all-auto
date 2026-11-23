"""Offline fail-closed tests of independent artifact API + local byte custody."""
import hashlib
import io
import json
import os
import struct
import zlib
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from scripts.github_artifact_custody import main, verify_custody
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
        self.set_archive(self.local.read_bytes())
    def archive(self, data):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("actual.msix", data)
        return buf.getvalue()
    def set_archive(self, data):
        self.zip = self.archive(data)
        self.artifact["digest"] = "sha256:" + hashlib.sha256(self.zip).hexdigest()
    def check(self):
        def get_json(url):
            return self.run if "/runs/" in url else self.artifact
        return verify_custody(self.expected, self.local, get_json, lambda url: self.zip)
    def test_matching_bytes_never_e2e(self):
        result = self.check()
        self.assertEqual(result["status"], "CUSTODY_VERIFIED_ONLY")
        self.assertFalse(result["e2e_pass"])
        self.assertEqual(result["signature"], "NOT_VERIFIED")
    def test_cli_writes_create_only_receipt_after_exact_custody(self):
        expected_path = Path(self.tmp.name) / "expected.json"
        expected_path.write_text(json.dumps(self.expected), encoding="utf-8")
        output = Path(self.tmp.name) / "github-custody.json"
        artifact = dict(self.artifact)
        artifact["digest"] = "sha256:" + hashlib.sha256(self.zip).hexdigest()

        def fake_clients(token):
            self.assertEqual(token, "test-token")
            def get_json(url):
                return self.run if "/runs/" in url else artifact
            return get_json, lambda url: self.zip

        args = ["--expected", str(expected_path), "--local-bundle", str(self.local),
                "--output", str(output)]
        with patch("scripts.github_artifact_custody.github_clients", side_effect=fake_clients), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=True), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = main(args)
        self.assertEqual(result, 0)
        receipt_text = output.read_text(encoding="utf-8")
        receipt = json.loads(receipt_text)
        self.assertEqual(receipt["status"], "CUSTODY_VERIFIED_ONLY")
        self.assertFalse(receipt["e2e_pass"])
        self.assertNotIn("test-token", receipt_text)

        # A durable receipt is create-only; retries cannot overwrite it.
        with patch("scripts.github_artifact_custody.github_clients", side_effect=AssertionError("must not call API")), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=True), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            retry = main(args)
        self.assertEqual(retry, 2)
        self.assertEqual(output.read_text(encoding="utf-8"), receipt_text)

    def test_cli_hold_never_writes_receipt_without_archive_digest(self):
        expected_path = Path(self.tmp.name) / "expected.json"
        expected_path.write_text(json.dumps(self.expected), encoding="utf-8")
        output = Path(self.tmp.name) / "github-custody.json"
        artifact = dict(self.artifact)
        artifact.pop("digest", None)

        def fake_clients(token):
            def get_json(url):
                return self.run if "/runs/" in url else artifact
            return get_json, lambda url: self.zip

        args = ["--expected", str(expected_path), "--local-bundle", str(self.local),
                "--output", str(output)]
        with patch("scripts.github_artifact_custody.github_clients", side_effect=fake_clients), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=True), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = main(args)
        self.assertEqual(result, 2)
        self.assertFalse(output.exists())

    def test_cli_accepts_transport_receipt_and_adds_custody_to_bundle(self):
        package_bytes = self.local.read_bytes()
        identity = {"name": "OkinawaDesktopTools.Test", "publisher": "CN=Test", "version": "1.0.0.0"}
        handoff = {
            "schema_version": 1, "package": "package.msix", "status": "QA_UNSIGNED",
            "source_sha": "a" * 40, "package_sha256": self.digest,
            "package_bytes": len(package_bytes), "identity": identity
        }
        handoff_bytes = json.dumps(handoff, separators=(",", ":")).encode("utf-8")
        bundle = Path(self.tmp.name) / "bundle"
        bundle.mkdir()
        (bundle / "handoff.json").write_bytes(handoff_bytes)
        (bundle / "package.msix").write_bytes(package_bytes)
        (bundle / "transport_receipt.json").write_text('{"schema_version":1}', encoding="utf-8")

        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as z:
            z.writestr("handoff.json", handoff_bytes)
            z.writestr("package.msix", package_bytes)
        archive = archive_buffer.getvalue()
        artifact = dict(self.artifact)
        artifact["digest"] = "sha256:" + hashlib.sha256(archive).hexdigest()
        expected = dict(self.expected, identity=identity)
        expected_path = Path(self.tmp.name) / "expected-bundle.json"
        expected_path.write_text(json.dumps(expected), encoding="utf-8")
        output = bundle / "github-custody.json"

        def fake_clients(token):
            def get_json(url):
                return self.run if "/runs/" in url else artifact
            return get_json, lambda url: archive

        args = ["--expected", str(expected_path), "--local-bundle", str(bundle),
                "--output", str(output)]
        with patch("scripts.github_artifact_custody.github_clients", side_effect=fake_clients), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}, clear=True), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = main(args)
        self.assertEqual(result, 0)
        self.assertTrue(output.is_file())
        self.assertEqual({p.name for p in bundle.iterdir()},
                         {"handoff.json", "package.msix", "transport_receipt.json", "github-custody.json"})
        receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "CUSTODY_VERIFIED_ONLY")
        self.assertEqual(receipt["source_sha"], "a" * 40)
        self.assertFalse(receipt["e2e_pass"])

    def test_cli_requires_token_and_does_not_write(self):
        expected_path = Path(self.tmp.name) / "expected.json"
        expected_path.write_text(json.dumps(self.expected), encoding="utf-8")
        output = Path(self.tmp.name) / "github-custody.json"
        args = ["--expected", str(expected_path), "--local-bundle", str(self.local),
                "--output", str(output)]
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            result = main(args)
        self.assertEqual(result, 2)
        self.assertFalse(output.exists())

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
        self.set_archive(b"different")
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
        self.artifact["digest"] = "sha256:" + hashlib.sha256(self.zip).hexdigest()
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
            # Synthetic assets exercise the transport gate without claiming production readiness.
            for asset, size in (("StoreLogo.png", 50), ("Square150.png", 150), ("Square44.png", 44)):
                ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
                chunk = b"IHDR" + ihdr
                png = (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + chunk
                       + struct.pack(">I", zlib.crc32(chunk)))
                z.writestr("Assets/" + asset, png + b"synthetic-fixture-not-production")
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
        self.set_archive(self.local.read_bytes())
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
        self.set_archive(b"tampered")
        rejected = self.check()
        self.assertEqual(rejected["status"], "HOLD")
        self.assertEqual(authorize_transport(identity, approval, self.local, receipt, rejected)["status"], "HOLD")
        # Even valid custody must not override a missing official version approval.
        self.set_archive(self.local.read_bytes())
        approval["approved"] = False
        self.assertEqual(authorize_transport(identity, approval, self.local, receipt, custody)["reason"],
                         "VERSION_NOT_APPROVED")


    def test_current_completion_queue_cannot_promote_without_authoritative_version(self):
        """Live queue is a HOLD fixture; synthetic custody cannot authorize a product."""
        import json
        root = Path(__file__).resolve().parents[1]
        queue = json.loads((root / "ops/completion_rush_queue_20261116.json").read_text(encoding="utf-8"))
        ledger = json.loads((root / "ops/active_e2e_handoff.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["e2e_status"], "HOLD")
        self.assertIs(ledger["e2e_pass"], False)
        for product in ("Focus Session Desk", "File Integrity Ledger"):
            item = next(p for p in queue["priority"] if p["product"] == product)
            self.assertEqual(item["hold_class"], "DELIVERY_HOLD")
            self.assertEqual(item["state"], "POST_IDENTITY_UPGRADE")
            self.assertIsNone(item["package_version"])
            self.assertIs(item["real_msix"], False)
            self.assertEqual(item["current_source_identity_binding_status"],
                             "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
            self.assertNotEqual(item["source_sha"], item["store_assets_branch_head"])
            identity = dict(request_id="unapproved-request", source_sha=item["source_sha"],
                            verified_source_sha=item["store_assets_branch_head"],
                            expected_head_sha=item["source_sha"], package_version_gate="HOLD")
            rejected = authorize_transport(identity, {}, self.local, {}, None)
            self.assertEqual(rejected["status"], "HOLD")
            self.assertEqual(rejected["reason"], "SOURCE_DRIFT")

        prism = next(p for p in queue["priority"] if p["product"] == "Prism Route 3D")
        self.assertEqual(prism["factory_source_sha"], "b03ce7b16c3f75c04fe20fdda224c45849eeba0d")
        self.assertEqual(prism["historical_factory_source_sha"], "4c22875c5ed79d393516c6a7a95361b9e9ed1950")
        self.assertEqual(prism["physical_qa_sessions"], "0/6")
        signal = next(p for p in queue["priority"] if p["product"] == "Signal Sprint")
        self.assertEqual(signal["historical_source_sha"], "c058cbf7fe38e02d929c67d047d717ff74bd522e")
        self.assertEqual(signal["current_candidate_source_sha"], "1a349faa41663c417c40710140a4d50c79b62b78")
        self.assertEqual(signal["build_artifact_status"], "HOLD_BUILD_ARTIFACT_NOT_CONFIGURED")
        self.assertIs(ledger["store_submission_allowed"], False)
        self.assertIs(ledger["certification_allowed"], False)
        self.assertIs(ledger["publish_allowed"], False)
        self.assertIs(queue["new_product_generation_allowed"], False)
        file_item = next(p for p in queue["priority"] if p["product"] == "File Integrity Ledger")
        self.assertEqual(file_item["current_stack_revalidation"]["status"], "PASS_EXACT_HEAD_CI_AFTER_STACK")

    def test_current_focus_file_transport_reconciliation_stays_fail_closed(self):
        root = Path(__file__).resolve().parents[1]
        ledger = json.loads((root / "ops/active_e2e_handoff.json").read_text(encoding="utf-8"))
        recon = json.loads((root / "ops/focus_file_transport_reconciliation_20261123.json").read_text(encoding="utf-8"))
        latest = ledger["latest_transport_reconciliation"]
        self.assertEqual(latest["central_tested_head_sha"], "41f74a28e8aac9356279349343f1dbe0d251800a")
        self.assertEqual(latest["previous_central_head_sha"], "6ac7c7f0fef32682bb5d8b0d19c59bd174482926")
        self.assertEqual(latest["ledger_followup_head_sha"], "41f74a28e8aac9356279349343f1dbe0d251800a")
        self.assertEqual(latest["ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual([x["run_id"] for x in latest["exact_head_ci"]],
                         [45230271440, 45230271518, 45230271524])
        self.assertEqual(latest["status"], "HOLD")
        self.assertIs(latest["e2e_pass"], False)
        self.assertIs(latest["real_msix"], False)
        self.assertEqual(latest["store_upload_test_eligible_products"], 0)
        self.assertIs(ledger["store_submission_allowed"], False)
        self.assertIs(ledger["certification_allowed"], False)
        self.assertIs(ledger["publish_allowed"], False)
        for product in recon["products"]:
            self.assertIsNone(product["package_version"])
            self.assertEqual(product["current_source_identity_binding_status"],
                             "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
            self.assertIs(product["real_msix"], False)
        self.assertEqual(recon["store_upload_test_eligibility"]["eligible_fresh_unsold_products"], 0)
        self.assertFalse(recon["store_upload_test_eligibility"]["dry_run_started"])
        queue = json.loads((root / "ops/completion_rush_queue_20261116.json").read_text(encoding="utf-8"))
        queue_latest = queue["latest_transport_reconciliation"]
        self.assertEqual(queue_latest["central_head"], latest["central_tested_head_sha"])
        self.assertEqual(recon["central_head"], latest["central_tested_head_sha"])
        self.assertEqual([x["run_id"] for x in queue_latest["exact_head_ci"]],
                         [x["run_id"] for x in latest["exact_head_ci"]])
        file_item = next(p for p in queue["priority"] if p["product"] == "File Integrity Ledger")
        self.assertEqual(file_item["current_gui_followup_pr"], 100)
        self.assertEqual(file_item["current_gui_followup_head"], "081fc168544022c401ce95a0f481644568912337")
        self.assertEqual(file_item["current_gui_followup"]["artifact_sha256"],
                         "bfb653798a47f14e036ad4ecc69a604b82b64b2df845b7c314c90f242ccdb3c9")
        self.assertEqual(file_item["current_gui_followup"]["exe_sha256"],
                         "5b788cdb0bc7c63d92956228358983fefc1352797fa5d7133ab365d2a7d774aa")
        self.assertFalse(file_item["current_gui_followup"]["visual_review_required"])
        self.assertFalse(file_item["approved_identity_file_present_on_current_pr100_head"])
        self.assertIsNone(file_item["package_version"])
        self.assertIs(file_item["real_msix"], False)

if __name__ == "__main__":
    unittest.main()
