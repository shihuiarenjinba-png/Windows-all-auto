from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "ops" / "partner_center_fleet_observation_20261125.json"
SNAPSHOT_REF = "ops/partner_center_fleet_observation_20261125.json"
PUBLISHER = "CN=46263F21-A700-41DB-8C9B-114C22FB82FC"

EXPECTED = {
    "ai-upload-guard": ("9PDJ1T5BQ4P1", "OkinawaDesktopTools.AIUploadGuard", "1152921505702212224", "Not started"),
    "image-privacy-cleaner": ("9PNSPFBKBBTQ", "OkinawaDesktopTools.ImagePrivacyCleaner", "1152921505702212225", "Not started"),
    "excel-csv-privacy-cleaner": ("9P3Z36J7PSFC", "OkinawaDesktopTools.ExcelCSVPrivacyCleaner", "1152921505702213008", "Not started"),
    "data-contract-auditor": ("9PDL4ZWSB45P", "OkinawaDesktopTools.DataContractAuditor", "1152921505702212222", "Incomplete"),
    "pdf-privacy": ("9PD1RXLFWPBC", "OkinawaDesktopTools.PDFPrivacy", "1152921505702212497", "Not started"),
    "web-evidence-archiver": ("9NNT1B142ZWV", "OkinawaDesktopTools.WebEvidenceArchiver", "1152921505702212223", "Not started"),
    "workflow-automation-hub": ("9P6SXJNNB5KK", "OkinawaDesktopTools.WorkflowAutomationHub", None, None),
}


class PartnerCenterFleetObservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        cls.products = {p["product_key"]: p for p in cls.snapshot["products"]}

    def test_snapshot_schema_and_provenance_are_explicit(self):
        snapshot = self.snapshot
        self.assertEqual(snapshot["schema_version"], "partner-center-fleet-observation/1")
        self.assertEqual(snapshot["observation_mode"], "READ_ONLY")
        self.assertTrue(snapshot["read_only"])
        self.assertEqual(
            snapshot["source"]["evidence_status"],
            "TRANSCRIBED_FROM_USER_SUPPLIED_FINAL_REPORT",
        )
        self.assertFalse(snapshot["source"]["cdp_endpoint_available"])
        self.assertFalse(snapshot["source"]["independent_screenshot_attached_to_this_commit"])
        self.assertTrue(snapshot["source"]["limitations"])

    def test_all_seven_product_identities_and_submission_observations_are_present(self):
        self.assertEqual(set(self.products), set(EXPECTED))
        store_ids = []
        identity_names = []
        for key, (store_id, identity_name, submission_id, packages_status) in EXPECTED.items():
            with self.subTest(product=key):
                row = self.products[key]
                self.assertEqual(row["store_id"], store_id)
                self.assertEqual(row["identity_name"], identity_name)
                self.assertEqual(row["publisher"], PUBLISHER)
                store_ids.append(row["store_id"])
                identity_names.append(row["identity_name"])
                submission = row["submission"]
                self.assertEqual(submission["submission_id"], submission_id)
                if submission_id is None:
                    self.assertEqual(submission["state"], "No submission shown")
                    self.assertTrue(submission["start_submission_available"])
                    self.assertIsNone(submission["packages_status"])
                else:
                    self.assertEqual(submission["state"], "In draft")
                    self.assertFalse(submission["start_submission_available"])
                    self.assertEqual(submission["packages_status"], packages_status)
                    self.assertEqual(submission["submission_number"], 1)
        self.assertEqual(len(store_ids), len(set(store_ids)))
        self.assertEqual(len(identity_names), len(set(identity_names)))

    def test_unavailable_package_fields_are_not_inferred(self):
        for key, row in self.products.items():
            with self.subTest(product=key):
                submission = row["submission"]
                if submission["package_row_present"] is False:
                    self.assertIsNone(submission.get("package_version"))
                    self.assertIsNone(submission.get("architecture"))
                    self.assertFalse(submission.get("binary_sha256_observable", False))

    def test_observation_proves_no_partner_center_side_effects(self):
        self.assertEqual(
            self.snapshot["side_effects"],
            {
                "product_created": False,
                "submission_started": False,
                "package_uploaded": False,
                "packages_saved": False,
                "pricing_changed": False,
                "markets_changed": False,
                "certification_started": False,
                "published": False,
            },
        )

    def test_six_existing_submission_bindings_match_group_c_registry(self):
        group_c = json.loads(
            (ROOT / "ops" / "group_c_store_products.json").read_text(encoding="utf-8")
        )
        group_b = json.loads(
            (ROOT / "ops" / "group_b_standard_store_products.json").read_text(encoding="utf-8")
        )
        for registry in (group_b, group_c):
            self.assertEqual(
                registry["partner_center_observation_snapshot"]["path"], SNAPSHOT_REF
            )
        for key in (
            "ai-upload-guard",
            "image-privacy-cleaner",
            "excel-csv-privacy-cleaner",
            "data-contract-auditor",
            "pdf-privacy",
            "web-evidence-archiver",
        ):
            record = group_c["products"][key]
            expected = EXPECTED[key]
            with self.subTest(product=key):
                self.assertEqual(record["store_id"], expected[0])
                self.assertEqual(record["identity_name"], expected[1])
                self.assertEqual(record["publisher"], PUBLISHER)
                self.assertEqual(record["draft_id"], expected[2])
                self.assertEqual(
                    record["partner_center_live_observation"]["submission_id"], expected[2]
                )
                self.assertEqual(
                    record["partner_center_live_observation"]["overall_status"],
                    "EXACT_REGISTRY_MATCH",
                )

    def test_qa_unsigned_artifacts_are_recorded_but_never_uploadable(self):
        group_c = json.loads(
            (ROOT / "ops" / "group_c_store_products.json").read_text(encoding="utf-8")
        )
        for key in (
            "ai-upload-guard",
            "image-privacy-cleaner",
            "excel-csv-privacy-cleaner",
            "pdf-privacy",
        ):
            record = group_c["products"][key]
            artifact = record["remote_package_artifact_discovery"]
            with self.subTest(product=key):
                self.assertTrue(artifact["qa_unsigned_msix_artifact_available"])
                self.assertEqual(artifact["classification"], "QA_UNSIGNED_VALIDATION_ONLY")
                self.assertFalse(artifact["uploadable"])
                self.assertRegex(artifact["qa_unsigned_msix_sha256"], r"^[A-F0-9]{64}$")
                self.assertEqual(artifact["sha256_evidence"]["evidence_level"], "BUILDER_REPORTED_HASH")
                self.assertFalse(artifact["sha256_evidence"]["binary_downloaded_and_rehashed_locally"])
                self.assertEqual(
                    artifact["formal_store_msix_build"], "SKIPPED_STORE_READINESS_GATE"
                )

        dca = group_c["products"]["data-contract-auditor"]["remote_package_artifact_discovery"]
        # 107e... is the QA baseline; the formal candidate source is 5a09...
        self.assertEqual(dca["qa_baseline_source_sha"], "107e59f2cbcde9c6ca88cf1aaf3d52262004e6e0")
        self.assertEqual(dca["candidate_source_sha"], "5a09d81955e25664761ea25ecfb4ebf8d24cea6d")
        self.assertEqual(dca["required_source_sha"], "5a09d81955e25664761ea25ecfb4ebf8d24cea6d")
        self.assertTrue(dca["source_match"])
        self.assertEqual(dca["package_sha256"], "80cd02c0df8e75d1962d03ce63c1ba72d9a8f67e8056f43718ffc5bd8d3f3279")
        self.assertEqual(dca["current_branch_head_sha"], "722ec7a077d2c6109e657c4ee661c9f3d06a4506")
        self.assertEqual(
            dca["current_branch_head_relation"]["application_runtime_source_changed_after_formal_candidate"],
            False,
        )
        self.assertFalse(dca["uploadable"])

    def test_web_evidence_archiver_artifact_waits_for_branch_integration(self):
        group_c = json.loads(
            (ROOT / "ops" / "group_c_store_products.json").read_text(encoding="utf-8")
        )
        wea = group_c["products"]["web-evidence-archiver"]
        self.assertEqual(wea["source_reconciliation"]["status"], "HOLD_DIVERGED_BRANCHES")
        self.assertEqual(
            wea["remote_package_artifact_discovery"]["classification"],
            "QA_UNSIGNED_VALIDATION_ONLY",
        )
        wea_artifact = wea["remote_package_artifact_discovery"]
        self.assertFalse(wea_artifact["uploadable"])
        self.assertEqual(wea_artifact["qa_unsigned_msix_version"], "1.0.55.0")
        self.assertEqual(wea_artifact["qa_unsigned_msix_sha256"], "91fae107652539bad0c0bdc30e9ae1891542c1a92f2460218e1be24af987cebe")

    def test_workflow_hub_has_source_bound_technical_artifact_but_no_submission(self):
        group_b = json.loads(
            (ROOT / "ops" / "group_b_standard_store_products.json").read_text(encoding="utf-8")
        )
        hub = group_b["products"]["workflow-automation-hub"]
        self.assertEqual(hub["publisher"], PUBLISHER)
        self.assertIsNone(hub["draft_id"])
        self.assertEqual(hub["submission_state"], "NO_SUBMISSION_OBSERVED")
        observation = hub["partner_center_live_observation"]
        self.assertIsNone(observation["submission_id"])
        self.assertEqual(observation["overall_status"], "NO_SUBMISSION_OBSERVED")
        self.assertTrue(observation["start_submission_available"])
        artifact = hub["remote_package_artifact_discovery"]
        self.assertEqual(artifact["source_sha"], "f2ba58895492f0c64da7676b17edfc97e98330e7")
        self.assertTrue(artifact["workflow_run_head_verified"])
        self.assertTrue(artifact["store_handoff_json_included"])
        self.assertTrue(artifact["msix_sha256_text_included"])
        self.assertEqual(artifact["package_signature"], "UNSIGNED")
        self.assertEqual(artifact["package_sha256"], "512da1ab4449a69b02901baf9c8eaff6577f1e58d336f43ef608f4fbc3892a97")
        self.assertEqual(artifact["version_approval"], "TECHNICAL_DRAFT_ONLY_PUBLIC_RELEASE_HOLD")
        self.assertFalse(artifact["uploadable"])


if __name__ == "__main__":
    unittest.main()
