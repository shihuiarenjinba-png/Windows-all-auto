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

    def test_group_registries_reference_snapshot_without_overwriting_static_ids(self):
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
        for key in ("ai-upload-guard", "image-privacy-cleaner", "excel-csv-privacy-cleaner"):
            record = group_c["products"][key]
            self.assertEqual(record["partner_center_live_observation"]["store_id"], EXPECTED[key][0])
            self.assertEqual(record["partner_center_live_observation"]["submission_id"], EXPECTED[key][2])
            self.assertEqual(record["partner_center_live_observation"]["overall_status"],
                             "LIVE_OBSERVATION_RECORDED_REGISTRY_ENRICHMENT_REQUIRED")
        dca = group_c["products"]["data-contract-auditor"]
        self.assertEqual(dca["store_id"], "9PDL4ZWSB45P")
        self.assertEqual(dca["draft_id"], "1152921505702212222")
        self.assertEqual(dca["partner_center_live_observation"]["submission_id"], "1152921505702212222")
        # These missing static fields remain untouched; the live values live in a separate observation.
        for key in ("pdf-privacy", "web-evidence-archiver"):
            record = group_c["products"][key]
            self.assertIsNone(record["store_id"])
            self.assertIsNone(record["draft_id"])
            self.assertEqual(record["partner_center_live_observation"]["store_id"], EXPECTED[key][0])
        hub = group_b["products"]["workflow-automation-hub"]
        self.assertEqual(hub["partner_center_live_observation"]["submission_id"], None)
        self.assertEqual(hub["partner_center_live_observation"]["submission_state"], "No submission shown")
        self.assertTrue(hub["partner_center_live_observation"]["start_submission_available"])


if __name__ == "__main__":
    unittest.main()
