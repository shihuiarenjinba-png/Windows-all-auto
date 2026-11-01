"""End-to-end offline bytes for local QA -> Windows-checker preflight adapter."""
import hashlib
import json
import shutil
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

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
            "import hashlib,json,sys\n"
            "from pathlib import Path\n"
            "p=Path(sys.argv[sys.argv.index('--report')+1])\n"
            "msix=Path(sys.argv[sys.argv.index('--msix')+1])\n"
            "kind=sys.argv[sys.argv.index('--type')+1]\n"
            "digest=hashlib.sha256(msix.read_bytes()).hexdigest().upper()\n"
            "p.write_text(json.dumps({'schema_version':1,'product_type':kind,'metadata':{'msix_sha256':digest},'verdict':'NEEDS_REVIEW'}))\n"
            "sys.exit(1)\n", encoding="utf-8")

    def _checker_output(self, raw, exit_code=1):
        # A real subprocess writes this untrusted report; tests do not fake
        # a successful Windows Checker or a physical GUI/install result.
        (self.checker / "run.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            + "Path(sys.argv[sys.argv.index('--report')+1]).write_text("
            + repr(raw) + ", encoding='utf-8')\n"
            + "sys.exit(" + str(exit_code) + ")\n",
            encoding="utf-8")

    def bundle(self, lane, slug, source=SOURCE, request=None):
        kind = {"APP": "app", "GAME": "game", "GAME_3D": "3d-game"}[lane]
        folder = self.inbox / lane / slug
        folder.mkdir(parents=True)
        package = folder / "package.msix"
        with zipfile.ZipFile(package, "w") as z:
            z.writestr("AppxManifest.xml", MANIFEST)
            z.writestr("AppxBlockMap.xml", b"<BlockMap/>")
            z.writestr("[Content_Types].xml", b"<Types/>")
            z.writestr("main.exe", EXE)
        payload = package.read_bytes()
        factory = {"APP": "AI-App-Factory", "GAME": "AI-Game-Factory",
                   "GAME_3D": "3d-game-factory"}[lane]
        repository = ("shihuiarenjinba-png/3d-game-factory"
                      if lane == "GAME_3D"
                      else "https://github.com/shihuiarenjinba-png/" + factory)
        meta = {
            "schema_version": 1, "source_repository": repository,
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
        elif lane == "GAME_3D":
            meta.pop("store_id")
            meta["factory_build_head"] = "b" * 40
            meta["local_package_sha256"] = hashlib.sha256(payload).hexdigest()
            meta["identity"].update({
                "store_id": "9N12345678",
                "package_family_name": "Sample.Test_abcdefghijklm",
                "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
            })
        (folder / "handoff.json").write_text(json.dumps(meta), encoding="utf-8")
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

    def test_3d_build_head_distinct_from_source_reaches_game_checker(self):
        self.bundle("GAME_3D", "sample-3d")
        result = check_local_queue(self.inbox, self.checker, self.reports)
        self.assertEqual(result["checked"], 1)
        receipt = result["results"][0]
        self.assertEqual(receipt["product_type"], "GAME_3D")
        self.assertEqual(receipt["checker_cli_type"], "game")
        self.assertEqual(receipt["source_factory"], "3d-game-factory")
        self.assertEqual(receipt["source_sha"], SOURCE)
        self.assertEqual(receipt["factory_build_head"], "b" * 40)
        self.assertEqual(receipt["checker_verdict"], "NEEDS_REVIEW")
        self.assertEqual(len(receipt["checker_report_package_sha256"]), 64)
        self.assertEqual(receipt["local_gui_qa"], "NOT_RUN")
        self.assertFalse(receipt["e2e_pass"])
        self.assertFalse(receipt["submitted_to_store"])

    def test_all_three_lanes_reach_checker_with_distinct_receipts(self):
        self.bundle("APP", "sample-app")
        self.bundle("GAME", "sample-game")
        self.bundle("GAME_3D", "sample-3d")
        result = check_local_queue(self.inbox, self.checker, self.reports)
        self.assertEqual(result["checked"], 3)
        self.assertEqual({x["product_type"] for x in result["results"]},
                         {"APP", "GAME", "GAME_3D"})
        self.assertEqual(len(list(self.reports.glob("*.checker.json"))), 3)
        self.assertFalse(result["e2e_pass"])

    def test_cross_lane_same_request_is_global_conflict(self):
        self.bundle("APP", "sample-app", request="same-request-0001")
        self.bundle("GAME", "sample-game", request="same-request-0001")
        with self.assertRaisesRegex(ValueError, "CONFLICT"):
            check_local_queue(self.inbox, self.checker, self.reports)
        self.assertFalse(self.reports.exists())

    def test_3d_cannot_relabel_as_ordinary_game(self):
        folder = self.bundle("GAME_3D", "sample-3d")
        meta_path = folder / "handoff.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["product_type"] = "GAME"
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "collision"):
            check_local_queue(self.inbox, self.checker, self.reports)
        self.assertFalse(self.reports.exists())

    def test_checker_enforces_2gib_local_capacity_before_execution(self):
        self.bundle("GAME_3D", "sample-3d")
        with patch("scripts.local_checker_queue.MAX_QUEUED_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "capacity"):
                check_local_queue(self.inbox, self.checker, self.reports)
        self.assertFalse(self.reports.exists())

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

    def test_checker_duplicate_verdict_is_not_accepted(self):
        self.bundle("APP", "sample-app")
        self._checker_output(
            '{"verdict":"BLOCKED","verdict":"READY_CANDIDATE_NOT_CERTIFIED"}',
            exit_code=0)
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            check_local_queue(self.inbox, self.checker, self.reports)

    def test_checker_nested_duplicate_key_is_not_accepted(self):
        self.bundle("GAME", "sample-game")
        self._checker_output(
            '{"verdict":"NEEDS_REVIEW","details":{"source":"one","source":"two"}}')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            check_local_queue(self.inbox, self.checker, self.reports)

    def test_checker_nan_and_non_object_are_rejected(self):
        self.bundle("APP", "sample-app")
        self._checker_output('{"verdict":"NEEDS_REVIEW","score":NaN}')
        with self.assertRaisesRegex(ValueError, "non-finite JSON"):
            check_local_queue(self.inbox, self.checker, self.reports)
        self._checker_output('[]')
        with self.assertRaisesRegex(ValueError, "invalid checker report object"):
            check_local_queue(self.inbox, self.checker, self.reports)

    def test_checker_oversize_report_is_rejected(self):
        self.bundle("APP", "sample-app")
        self._checker_output(
            '{"verdict":"NEEDS_REVIEW","padding":"' + 'x' * 2_000_001 + '"}')
        with self.assertRaisesRegex(ValueError, "invalid checker report size"):
            check_local_queue(self.inbox, self.checker, self.reports)

    def test_handoff_duplicate_key_and_nonfinite_are_rejected(self):
        folder = self.bundle("GAME", "sample-game")
        path = folder / "handoff.json"
        raw = path.read_text(encoding="utf-8")
        path.write_text(raw.replace('"source_sha":', '"source_sha":"spoof", "source_sha":', 1),
                        encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            check_local_queue(self.inbox, self.checker, self.reports)
        path.write_text(raw.replace('"package_bytes":', '"risk":NaN, "package_bytes":', 1),
                        encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "non-finite JSON"):
            check_local_queue(self.inbox, self.checker, self.reports)

    def test_checker_report_must_bind_exact_package_sha(self):
        self.bundle("APP", "sample-app")
        self._checker_output(json.dumps({
            "schema_version": 1, "product_type": "app",
            "metadata": {"msix_sha256": "0" * 64},
            "verdict": "NEEDS_REVIEW",
        }))
        with self.assertRaisesRegex(ValueError, "checker report package SHA mismatch"):
            check_local_queue(self.inbox, self.checker, self.reports)
        self.assertEqual(list(self.reports.glob("*.checker.json")), [])

    def test_checker_report_missing_package_hash_is_hold(self):
        self.bundle("GAME_3D", "sample-3d")
        self._checker_output(json.dumps({
            "schema_version": 1, "product_type": "game",
            "metadata": {}, "verdict": "NEEDS_REVIEW",
        }))
        with self.assertRaisesRegex(ValueError, "checker report package SHA mismatch"):
            check_local_queue(self.inbox, self.checker, self.reports)

    def test_checker_report_wrong_lane_and_boolean_schema_are_hold(self):
        self.bundle("GAME", "sample-game")
        self._checker_output(json.dumps({
            "schema_version": 1, "product_type": "app",
            "metadata": {"msix_sha256": "0" * 64},
            "verdict": "NEEDS_REVIEW",
        }))
        with self.assertRaisesRegex(ValueError, "checker report schema/product mismatch"):
            check_local_queue(self.inbox, self.checker, self.reports)
        self._checker_output(json.dumps({
            "schema_version": True, "product_type": "game",
            "metadata": {"msix_sha256": "0" * 64},
            "verdict": "NEEDS_REVIEW",
        }))
        with self.assertRaisesRegex(ValueError, "checker report schema/product mismatch"):
            check_local_queue(self.inbox, self.checker, self.reports)

    def test_checker_mutation_rejected_even_with_forged_original_sha(self):
        self.bundle("APP", "sample-app")
        (self.checker / "run.py").write_text(
            "import hashlib,json,sys\nfrom pathlib import Path\n"
            "msix=Path(sys.argv[sys.argv.index('--msix')+1])\n"
            "report=Path(sys.argv[sys.argv.index('--report')+1])\n"
            "original=hashlib.sha256(msix.read_bytes()).hexdigest()\n"
            "payload=bytearray(msix.read_bytes()); payload[-1]^=1\n"
            "msix.write_bytes(payload)\n"
            "report.write_text(json.dumps({'schema_version':1,'product_type':'app',"
            "'metadata':{'msix_sha256':original},'verdict':'NEEDS_REVIEW'}))\n"
            "sys.exit(1)\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "package changed during checker"):
            check_local_queue(self.inbox, self.checker, self.reports)
        self.assertEqual(list(self.reports.glob("*.checker.json")), [])

    def test_checker_package_append_rejected_before_report_acceptance(self):
        self.bundle("GAME", "sample-game")
        (self.checker / "run.py").write_text(
            "import hashlib,json,sys\nfrom pathlib import Path\n"
            "msix=Path(sys.argv[sys.argv.index('--msix')+1])\n"
            "report=Path(sys.argv[sys.argv.index('--report')+1])\n"
            "original=hashlib.sha256(msix.read_bytes()).hexdigest()\n"
            "with msix.open('ab') as stream: stream.write(b'append')\n"
            "report.write_text(json.dumps({'schema_version':1,'product_type':'game',"
            "'metadata':{'msix_sha256':original},'verdict':'NEEDS_REVIEW'}))\n"
            "sys.exit(1)\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "package changed during checker"):
            check_local_queue(self.inbox, self.checker, self.reports)
        self.assertEqual(list(self.reports.glob("*.checker.json")), [])

    def test_same_request_replay_keeps_exact_checker_receipt_binding(self):
        self.bundle("APP", "sample-app", request="app-request-0001")
        first = check_local_queue(self.inbox, self.checker, self.reports)
        second = check_local_queue(self.inbox, self.checker, self.reports)
        self.assertEqual(first["results"][0]["request_id"],
                         second["results"][0]["request_id"])
        self.assertEqual(len(list(self.reports.glob("*.checker.json"))), 1)
        self.assertFalse(second["e2e_pass"])

    def test_rotated_inbox_cannot_overwrite_prior_request_receipt(self):
        folder = self.bundle("APP", "sample-app", request="app-request-0001")
        package_bytes = (folder / "package.msix").read_bytes()
        check_local_queue(self.inbox, self.checker, self.reports)
        prior = next(self.reports.glob("*.checker.json"))
        original = prior.read_bytes()
        shutil.rmtree(folder)
        rotated = self.bundle("APP", "sample-app", request="app-request-0002")
        # ZipFile.writestr timestamps can differ across the second boundary
        # (especially on Windows). Reuse the *exact* prior package bytes so
        # this test deterministically exercises the report-name collision.
        (rotated / "package.msix").write_bytes(package_bytes)
        metadata_path = rotated / "handoff.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["package_sha256"] = hashlib.sha256(package_bytes).hexdigest()
        metadata["package_bytes"] = len(package_bytes)
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "existing checker receipt provenance conflict"):
            check_local_queue(self.inbox, self.checker, self.reports)
        self.assertEqual(prior.read_bytes(), original)

    def test_tampered_existing_receipt_is_hold_before_checker(self):
        self.bundle("GAME_3D", "sample-3d")
        check_local_queue(self.inbox, self.checker, self.reports)
        prior = next(self.reports.glob("*.checker.json"))
        data = json.loads(prior.read_text(encoding="utf-8"))
        data["receipt"]["source_sha"] = "f" * 40
        prior.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "existing checker receipt provenance conflict"):
            check_local_queue(self.inbox, self.checker, self.reports)

    def test_report_cannot_be_written_inside_package_queue(self):
        self.bundle("GAME", "sample-game")
        with self.assertRaisesRegex(ValueError, "outside package inbox"):
            check_local_queue(self.inbox, self.checker, self.inbox / "reports")


if __name__ == "__main__":
    unittest.main()
