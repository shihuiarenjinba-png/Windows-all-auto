"""End-to-end offline bytes for local QA -> Windows-checker preflight adapter."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.local_checker_queue import check_local_queue

SOURCE = "a" * 40
EXE = b"MZ" + b"offline-fixture" * 4
MANIFEST = (b'<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
            b'<Identity Name="Sample.Test" Publisher="CN=VerifiedElsewhere" Version="1.0.0.0"/>'
            b'<Applications><Application Id="App" Executable="main.exe"/></Applications></Package>')


class LocalCheckerQueueTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()
        self.reports = self.root / "reports"
        self.checker = self.root / "checker"
        self.checker.mkdir()
        (self.checker / "run.py").write_text(
            "import json,sys\n"
            "from pathlib import Path\n"
            "p=Path(sys.argv[sys.argv.index('--report')+1])\n"
            "p.write_text(json.dumps({'verdict':'NEEDS_REVIEW'}))\n"
            "sys.exit(1)\n", encoding="utf-8")

    def bundle(self, lane, slug, source=SOURCE, request=None):
        kind = lane.lower()
        folder = self.inbox / lane / slug
        folder.mkdir(parents=True)
        package = folder / "package.msix"
        with zipfile.ZipFile(package, "w") as z:
            z.writestr("AppxManifest.xml", MANIFEST)
            z.writestr("AppxBlockMap.xml", b"<BlockMap/>")
            z.writestr("[Content_Types].xml", b"<Types/>")
            z.writestr("main.exe", EXE)
        payload = package.read_bytes()
        factory = "AI-App-Factory" if lane == "APP" else "AI-Game-Factory"
        meta = {
            "schema_version": 1, "source_repository":
                "https://github.com/shihuiarenjinba-png/" + factory,
            "source_sha": source, "type": kind, "slug": slug,
            "package": "package.msix", "status": "QA_UNSIGNED",
            "package_bytes": len(payload),
            "package_sha256": hashlib.sha256(payload).hexdigest(),
            "identity": {"name": "Sample.Test", "publisher": "CN=VerifiedElsewhere",
                         "version": "1.0.0.0"},
            "request_id": request or (kind + "-sample-0001"),
            "product_type": lane, "source_factory": factory,
            "source_branch": "codex/sample-active-product",
            "expected_head_sha": source, "store_id": "9N12345678",
            "signature_status": "UNSIGNED",
        }
        if lane == "APP":
            meta.update({
                "factory_head_sha": source,
                "display_name": "Sample App",
                "prebuilt_exe_sha256": hashlib.sha256(EXE).hexdigest(),
            })
        (folder / "handoff.json").write_text(json.dumps(meta), encoding="utf-8")
        if lane == "APP":
            # Synthetic source-bound receipts exercise the production intake
            # contract; they are not real Partner Center or product approval.
            verifier = "fixture-operator"
            evidence = "https://partner.microsoft.com/dashboard/products/" + meta["store_id"] + "/identity"
            approved = {
                "schema_version": "1.0", "reviewed": True, "source": "partner_center",
                "request_id": meta["request_id"], "product_type": "APP",
                "source_factory": "AI-App-Factory",
                "source_repository": "shihuiarenjinba-png/AI-App-Factory",
                "source_branch": meta["source_branch"], "source_sha": source,
                "expected_head_sha": source, "store_id": meta["store_id"],
                "name": meta["identity"]["name"], "publisher": meta["identity"]["publisher"],
                "version": meta["identity"]["version"], "package_version_gate": "PASS",
                "operator_verified": True, "verified_by": verifier, "evidence_url": evidence,
            }
            approved_raw = json.dumps(approved, separators=(",", ":")).encode("utf-8")
            (folder / "approved-identity.json").write_bytes(approved_raw)
            approved_blob_sha = hashlib.sha1(
                b"blob " + str(len(approved_raw)).encode("ascii") + b"\0" + approved_raw
            ).hexdigest()
            transport = {
                "schema_version": 1, "status": "SOURCE_BOUND_VERSION_APPROVED",
                "source_sha": source, "expected_head_sha": source, "factory_head_sha": source,
                "source_repository": meta["source_repository"], "product_type": "APP",
                "source_factory": "AI-App-Factory", "package_sha256": meta["package_sha256"],
                "package_bytes": meta["package_bytes"], "identity": meta["identity"],
                "approval_source": "partner_center", "package_version_gate": "PASS",
                "package_version": meta["identity"]["version"], "operator_verified": True,
                "store_submission_allowed": False, "certification_allowed": False, "publish_allowed": False,
                "approved_identity_file_sha": approved_blob_sha, "verified_by": verifier,
                "evidence_url": evidence, "request_id": meta["request_id"],
                "source_branch": meta["source_branch"], "store_id": meta["store_id"],
                "display_name": meta["display_name"], "prebuilt_exe_sha256": meta["prebuilt_exe_sha256"],
            }
            (folder / "transport_receipt.json").write_text(json.dumps(transport), encoding="utf-8")
            custody = {
                "status": "CUSTODY_VERIFIED_ONLY", "e2e_pass": False,
                "source_sha": source, "msix_sha256": meta["package_sha256"],
                "run_id": 12345, "artifact_id": 67890,
                "repository": "shihuiarenjinba-png/AI-App-Factory",
                "archive_sha256": "d" * 64,
            }
            (folder / "github-custody.json").write_text(json.dumps(custody), encoding="utf-8")
        return folder

    def test_empty_inbox_is_hold_not_e2e(self):
        result = check_local_queue(self.inbox, self.checker, self.reports)
        self.assertEqual(result["reason"], "NO_REAL_MSIX_IN_LOCAL_QA_QUEUE")
        self.assertFalse(result["e2e_pass"])
        self.assertFalse(self.reports.exists())

    def test_actual_app_and_game_bytes_reach_checker_separately(self):
        self.bundle("APP", "sample-app")
        self.bundle("GAME", "sample-game")
        result = check_local_queue(self.inbox, self.checker, self.reports)
        self.assertEqual(result["checked"], 2)
        self.assertEqual({x["product_type"] for x in result["results"]}, {"APP", "GAME"})
        self.assertTrue(all(x["checker_verdict"] == "NEEDS_REVIEW" for x in result["results"]))
        self.assertTrue(all(x["local_gui_qa"] == "NOT_RUN" for x in result["results"]))
        self.assertFalse(result["e2e_pass"])
        self.assertEqual(len(list(self.reports.glob("*.checker.json"))), 2)

    def test_corrupted_msix_rejected_before_checker(self):
        folder = self.bundle("GAME", "sample-game")
        with (folder / "package.msix").open("ab") as f:
            f.write(b"tamper")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            check_local_queue(self.inbox, self.checker, self.reports)
        self.assertFalse(self.reports.exists())

    def test_cross_source_reuse_of_request_is_conflict(self):
        self.bundle("GAME", "sample-game", source="a" * 40, request="same-request-001")
        self.bundle("GAME", "other-game", source="b" * 40, request="same-request-001")
        with self.assertRaisesRegex(ValueError, "CONFLICT"):
            check_local_queue(self.inbox, self.checker, self.reports)
        self.assertFalse(self.reports.exists())

    def test_no_checker_report_never_passes(self):
        self.bundle("APP", "sample-app")
        (self.checker / "run.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "without valid report"):
            check_local_queue(self.inbox, self.checker, self.reports)

    def test_report_cannot_be_written_inside_package_queue(self):
        self.bundle("GAME", "sample-game")
        with self.assertRaisesRegex(ValueError, "outside package inbox"):
            check_local_queue(self.inbox, self.checker, self.inbox / "reports")


if __name__ == "__main__":
    unittest.main()
