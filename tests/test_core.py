import copy
import json
import tempfile
import unittest
from pathlib import Path

from all_auto.core import SECURITY_KEYS, check_product, export_results, preflight, sha256_file


class CoordinatorPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        package = self.root / "Sample.msix"
        package.write_bytes(b"synthetic-fixture-not-a-real-msix")
        self.package_hash = sha256_file(package)
        checker_report = self.root / "checker.json"
        checker_report.write_text('{"status":"READY_CANDIDATE_NOT_CERTIFIED"}', encoding="utf-8")
        build_report = self.root / "build.json"
        build_report.write_text('{"status":"mock-fixture"}', encoding="utf-8")
        identity = {"store_id": "9ABCDEF123", "name": "SignedOfficial.Identity",
                    "publisher": "CN=TEST", "version": "1.0.0.0", "architecture": "x64"}
        self.product = {
            "id": "sample",
            "type": "app",
            "submission_kind": "update",
            "repository": "https://github.com/shihuiarenjinba-png/sample",
            "source_ref": "codex/qa",
            "source_sha": "a" * 40,
            "identity": identity,
            "approved_identity": identity.copy(),
            "package_path": str(package),
            "package_sha256": self.package_hash,
            "checker": {
                "status": "READY_CANDIDATE_NOT_CERTIFIED",
                "package_sha256": self.package_hash,
                "report_path": str(checker_report),
                "report_sha256": sha256_file(checker_report),
            },
            "build": {
                "source_sha": "a" * 40,
                "package_sha256": self.package_hash,
                "report_path": str(build_report),
                "report_sha256": sha256_file(build_report),
            },
            "security": {
                "package_sha256": self.package_hash,
                "confirmed": True,
                "confirmed_at": "2026-10-26T00:00:00Z",
                "confirmed_by": "QA_OPERATOR",
                "fields": {k: False for k in SECURITY_KEYS},
            },
            "price": {"amount_minor": 1000, "currency": "JPY"},
            "assets_reviewed": True,
            "owner_approved_for_draft": True,
        }

    def check(self, obj=None):
        return check_product(self.product if obj is None else obj, self.root)

    def assert_finding(self, code, obj=None):
        result = self.check(obj)
        self.assertIn(code, result["findings"])
        self.assertNotEqual(result["status"], "READY_FOR_WINDOWS_QA")

    def test_01_fully_evidenced_fixture_is_only_windows_qa_ready(self):
        result = self.check()
        self.assertEqual(result["status"], "READY_FOR_WINDOWS_QA")
        self.assertIn("no Store operation performed", result["meaning"])

    def test_02_never_claims_store_upload(self):
        result = preflight({"schema_version": "1", "products": [self.product]}, self.root)
        self.assertEqual(result["store_uploads_attempted"], 0)
        self.assertEqual(result["drafts_saved"], 0)
        self.assertEqual(result["certified"], 0)

    def test_03_changed_package_blocks(self):
        obj = copy.deepcopy(self.product)
        obj["package_sha256"] = "f" * 64
        self.assert_finding("PACKAGE_SHA_MISMATCH", obj)

    def test_04_missing_package_holds(self):
        obj = copy.deepcopy(self.product)
        obj["package_path"] = "missing.msix"
        self.assert_finding("PACKAGE_FILE_NOT_FOUND", obj)

    def test_05_invalid_format_blocks(self):
        obj = copy.deepcopy(self.product)
        obj["package_path"] = "fixture.zip"
        self.assert_finding("UNSUPPORTED_PACKAGE_SUFFIX", obj)

    def test_06_official_identity_mismatch_blocks(self):
        obj = copy.deepcopy(self.product)
        obj["approved_identity"]["publisher"] = "CN=OTHER"
        self.assert_finding("IDENTITY_MISMATCH_PUBLISHER", obj)

    def test_07_missing_identity_holds(self):
        obj = copy.deepcopy(self.product)
        del obj["approved_identity"]["store_id"]
        self.assert_finding("IDENTITY_NOT_VERIFIED_STORE_ID", obj)

    def test_08_checker_blocked_is_blocked(self):
        obj = copy.deepcopy(self.product)
        obj["checker"]["status"] = "BLOCKED"
        self.assert_finding("WINDOWS_CHECKER_BLOCKED", obj)

    def test_09_checker_needs_review_holds(self):
        obj = copy.deepcopy(self.product)
        obj["checker"]["status"] = "NEEDS_REVIEW"
        self.assert_finding("WINDOWS_CHECKER_NOT_READY", obj)

    def test_10_checker_report_tampering_blocks(self):
        obj = copy.deepcopy(self.product)
        obj["checker"]["report_sha256"] = "b" * 64
        self.assert_finding("CHECKER_REPORT_HASH_MISMATCH", obj)

    def test_11_build_wrong_commit_blocks(self):
        obj = copy.deepcopy(self.product)
        obj["build"]["source_sha"] = "b" * 40
        self.assert_finding("BUILD_SOURCE_SHA_MISMATCH", obj)

    def test_12_build_report_tampering_blocks(self):
        obj = copy.deepcopy(self.product)
        obj["build"]["report_sha256"] = "b" * 64
        self.assert_finding("WINDOWS_DATA_REPORT_HASH_MISMATCH", obj)

    def test_13_security_unconfirmed_holds(self):
        obj = copy.deepcopy(self.product)
        obj["security"]["confirmed"] = False
        self.assert_finding("SECURITY_HUMAN_CONFIRMATION_REQUIRED", obj)

    def test_14_security_package_changed_holds(self):
        obj = copy.deepcopy(self.product)
        obj["security"]["package_sha256"] = "b" * 64
        self.assert_finding("SECURITY_CONFIRMATION_PACKAGE_MISMATCH", obj)

    def test_15_security_fields_missing_holds(self):
        obj = copy.deepcopy(self.product)
        del obj["security"]["fields"]["microphone"]
        self.assert_finding("SECURITY_NINE_FIELDS_INCOMPLETE", obj)

    def test_16_security_field_must_be_bool(self):
        obj = copy.deepcopy(self.product)
        obj["security"]["fields"]["microphone"] = "no"
        self.assert_finding("SECURITY_NINE_FIELDS_INCOMPLETE", obj)

    def test_17_price_not_guessed(self):
        obj = copy.deepcopy(self.product)
        obj["price"] = {"amount_minor": 0, "currency": "JPY"}
        self.assert_finding("PAID_PRICE_UNCONFIRMED", obj)

    def test_18_explicit_draft_approval(self):
        obj = copy.deepcopy(self.product)
        obj["owner_approved_for_draft"] = False
        self.assert_finding("DRAFT_WRITE_NOT_AUTHORIZED", obj)

    def test_19_duplicate_product_id_blocks(self):
        doc = {"schema_version": "1", "products": [self.product, copy.deepcopy(self.product)]}
        result = preflight(doc, self.root)
        self.assertEqual(result["counts"]["BLOCKED"], 2)

    def test_20_duplicate_store_id_blocks(self):
        second = copy.deepcopy(self.product)
        second["id"] = "other"
        doc = {"schema_version": "1", "products": [self.product, second]}
        result = preflight(doc, self.root)
        self.assertEqual(result["counts"]["BLOCKED"], 2)

    def test_21_mixed_queue_accounting(self):
        a = copy.deepcopy(self.product)
        b = copy.deepcopy(self.product)
        b["id"] = "other"
        b["identity"]["store_id"] = "9OTHER123"
        b["approved_identity"]["store_id"] = "9OTHER123"
        b["security"]["confirmed"] = False
        c = copy.deepcopy(self.product)
        c["id"] = "third"
        c["identity"]["store_id"] = "9THIRD123"
        c["approved_identity"]["store_id"] = "9THIRD123"
        c["checker"]["status"] = "BLOCKED"
        r = preflight({"schema_version": "1", "products": [a, b, c]}, self.root)
        self.assertEqual(r["counts"], {"READY_FOR_WINDOWS_QA": 1, "HOLD": 1, "BLOCKED": 1})

    def test_22_report_export_has_no_certification_claim(self):
        r = preflight({"schema_version": "1", "products": [self.product]}, self.root)
        out = self.root / "reports"
        export_results(r, out)
        self.assertEqual(json.loads((out / "summary.json").read_text())["drafts_saved"], 0)
        self.assertTrue((out / "audit-sample.json").exists())
        self.assertIn("No Partner Center operation", (out / "summary.md").read_text())

    def test_23_manifest_version_enforced(self):
        with self.assertRaises(ValueError):
            preflight({"products": [self.product]}, self.root)

    def test_24_empty_product_list_enforced(self):
        with self.assertRaises(ValueError):
            preflight({"schema_version": "1", "products": []}, self.root)

    def test_25_foreign_repo_unverified(self):
        obj = copy.deepcopy(self.product)
        obj["repository"] = "https://github.com/another-user/other-app"
        self.assert_finding("GITHUB_REPO_UNCONFIRMED", obj)

    def test_26_invalid_product_identifier_blocks(self):
        obj = copy.deepcopy(self.product)
        obj["id"] = "../escape"
        self.assert_finding("INVALID_PRODUCT_ID", obj)


if __name__ == "__main__":
    unittest.main()
