import copy
import unittest

from all_auto.contracts import (
    ContractError,
    parse_windows_automator,
    parse_windows_checker,
    parse_windows_data,
)


class UpstreamContractTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "schema_version": 1,
            "status": "READY_CANDIDATE_NOT_CERTIFIED",
            "repository_url": "https://github.com/shihuiarenjinba-png/sample",
            "source_head": "a" * 40,
            "store_id": "9REALTEST",
            "identity": {
                "name": "Example.Identity",
                "publisher": "CN=EXAMPLE",
                "version": "1.2.3.4",
                "architecture": "x64",
            },
            "artifacts": [
                {
                    "kind": "MSIX",
                    "path": "C:/qa/Example.msix",
                    "sha256": "b" * 64,
                    "size": 100,
                }
            ],
            "holds": [],
        }
        self.checker = {
            "schema_version": 1,
            "total": 1,
            "blocked": 0,
            "needs_review": 0,
            "ready_candidates": 1,
            "items": [
                {
                    "id": "sample",
                    "verdict": "READY_CANDIDATE_NOT_CERTIFIED",
                    "report": "audit-sample.json",
                }
            ],
        }
        self.automator = {
            "summary": {
                "mode": "single",
                "total": 1,
                "success": 1,
                "hold": 0,
                "failed": 0,
                "unknown": 0,
            },
            "results": [
                {
                    "product_name": "Example",
                    "status": "DONE",
                    "findings": [],
                    "actions": ["packages:upload:C:/qa/Example.msix", "review:save_draft_only"],
                }
            ],
        }
        self.automator_live = {
            "schema_version": 2,
            "summary": {
                "mode": "single",
                "total": 1,
                "success": 1,
                "draft_saved": 1,
                "hold": 0,
                "failed": 0,
                "unknown": 0,
            },
            "results": [
                {
                    "product_name": "Example",
                    "status": "DRAFT_SAVED",
                    "findings": [],
                    "actions": ["packages:upload:C:/qa/Example.msix", "packages:save_draft"],
                    "execution_mode": "live",
                    "submission_route": "msix_pwa_app",
                    "draft_saved": True,
                    "save_verified_after_reload": True,
                    "package_uploaded": True,
                    "package_validation": "VALID",
                    "package_section_completion": "COMPLETE",
                    "draft_id": "12345",
                    "product_id": "9REALTEST",
                    "package_sha256": "b" * 64,
                    "source_sha": "a" * 40,
                    "identity": {
                        "name": "Example.Identity",
                        "publisher": "CN=EXAMPLE",
                        "version": "1.2.3.4",
                    },
                    "sections": {
                        "pricing_availability": "SAVED",
                        "properties": "SAVED",
                        "age_ratings": "SAVED",
                        "packages": "SAVED",
                        "store_listings": "SAVED",
                        "submission_options": "SAVED",
                    },
                    "current_draft_url": "https://partner.microsoft.com/en-us/dashboard/products/9REALTEST/submissions/12345",
                    "evidence": [
                        {"kind": "partner_center_draft_screenshot", "path": "C:/qa/proof.png"}
                    ],
                    "submitted": False,
                    "certified": False,
                    "published": False,
                }
            ],
        }

    def test_01_windows_data_ready_contract(self):
        result = parse_windows_data(
            self.data,
            expected_repository_url="https://github.com/shihuiarenjinba-png/sample",
        )
        self.assertTrue(result["ready_for_checker"])
        self.assertEqual(result["package_sha256"], "b" * 64)

    def test_02_windows_data_unknown_schema_fails_closed(self):
        obj = copy.deepcopy(self.data)
        obj["schema_version"] = 2
        with self.assertRaises(ContractError):
            parse_windows_data(obj)

    def test_03_windows_data_ready_requires_exactly_one_msix(self):
        obj = copy.deepcopy(self.data)
        obj["artifacts"].append(copy.deepcopy(obj["artifacts"][0]))
        with self.assertRaises(ContractError):
            parse_windows_data(obj)

    def test_04_windows_data_hold_does_not_claim_checker_ready(self):
        obj = {"schema_version": 1, "status": "HOLD", "holds": [{"code": "BUILD_NOT_RUN"}]}
        result = parse_windows_data(obj)
        self.assertFalse(result["ready_for_checker"])

    def test_05_checker_ready_is_not_certification(self):
        result = parse_windows_checker(self.checker, product_id="sample")
        self.assertTrue(result["ready_for_submission_preparation"])
        self.assertFalse(result["certified"])

    def test_06_checker_count_tampering_fails_closed(self):
        obj = copy.deepcopy(self.checker)
        obj["ready_candidates"] = 0
        with self.assertRaises(ContractError):
            parse_windows_checker(obj, product_id="sample")

    def test_07_checker_needs_exact_product_match(self):
        with self.assertRaises(ContractError):
            parse_windows_checker(self.checker, product_id="other")

    def test_08_automator_done_is_only_dry_run_done(self):
        result = parse_windows_automator(self.automator, product_name="Example")
        self.assertEqual(result["status"], "DRY_RUN_DONE")
        self.assertFalse(result["draft_saved"])
        self.assertFalse(result["submitted"])

    def test_09_automator_draft_saved_claim_is_rejected_until_live_contract_exists(self):
        obj = copy.deepcopy(self.automator)
        obj["results"][0]["status"] = "DRAFT_SAVED"
        with self.assertRaises(ContractError):
            parse_windows_automator(obj, product_name="Example")

    def test_10_automator_ambiguous_result_stays_unknown(self):
        obj = copy.deepcopy(self.automator)
        obj["results"][0]["status"] = "UNKNOWN"
        result = parse_windows_automator(obj, product_name="Example")
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertFalse(result["draft_saved"])

    def _parse_live(self, payload=None, **overrides):
        values = {
            "product_name": "Example",
            "expected_product_id": "9REALTEST",
            "expected_submission_route": "msix_pwa_app",
            "expected_package_sha256": "b" * 64,
            "expected_source_sha": "a" * 40,
            "expected_identity_name": "Example.Identity",
            "expected_identity_publisher": "CN=EXAMPLE",
            "expected_version": "1.2.3.4",
        }
        values.update(overrides)
        return parse_windows_automator(payload or self.automator_live, **values)

    def test_11_verified_live_contract_accepts_draft_saved(self):
        result = self._parse_live()
        self.assertEqual(result["status"], "DRAFT_SAVED")
        self.assertTrue(result["draft_saved"])
        self.assertTrue(result["save_verified_after_reload"])
        self.assertFalse(result["submitted"])

    def test_12_live_contract_requires_all_immutable_expectations(self):
        with self.assertRaises(ContractError):
            parse_windows_automator(self.automator_live, product_name="Example")

    def test_13_live_contract_rejects_product_package_or_source_mismatch(self):
        for key, value in (
            ("expected_product_id", "9OTHER"),
            ("expected_package_sha256", "c" * 64),
            ("expected_source_sha", "d" * 40),
        ):
            with self.subTest(key=key), self.assertRaises(ContractError):
                self._parse_live(**{key: value})

    def test_14_live_contract_rejects_identity_or_version_mismatch(self):
        for key, value in (
            ("expected_identity_name", "Other.Identity"),
            ("expected_identity_publisher", "CN=OTHER"),
            ("expected_version", "9.9.9.9"),
        ):
            with self.subTest(key=key), self.assertRaises(ContractError):
                self._parse_live(**{key: value})

    def test_15_live_contract_rejects_unproven_write_or_warning(self):
        for key, value in (
            ("draft_saved", False),
            ("save_verified_after_reload", False),
            ("package_uploaded", False),
            ("package_validation", "WARNING"),
            ("package_section_completion", "INCOMPLETE"),
        ):
            obj = copy.deepcopy(self.automator_live)
            obj["results"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ContractError):
                self._parse_live(obj)

    def test_16_live_contract_rejects_missing_section_or_evidence(self):
        obj = copy.deepcopy(self.automator_live)
        del obj["results"][0]["sections"]["store_listings"]
        with self.assertRaises(ContractError):
            self._parse_live(obj)
        obj = copy.deepcopy(self.automator_live)
        obj["results"][0]["evidence"] = []
        with self.assertRaises(ContractError):
            self._parse_live(obj)

    def test_17_live_contract_never_accepts_submit_certify_or_publish(self):
        for key in ("submitted", "certified", "published"):
            obj = copy.deepcopy(self.automator_live)
            obj["results"][0][key] = True
            with self.subTest(key=key), self.assertRaises(ContractError):
                self._parse_live(obj)

    def test_18_live_done_is_not_silently_promoted(self):
        obj = copy.deepcopy(self.automator)
        obj["results"][0]["execution_mode"] = "live"
        with self.assertRaises(ContractError):
            parse_windows_automator(obj, product_name="Example")

    def test_19_live_contract_requires_exact_immutable_submission_route(self):
        result = self._parse_live()
        self.assertEqual(result["submission_route"], "msix_pwa_app")
        with self.assertRaises(ContractError):
            self._parse_live(expected_submission_route="exe_msi_app")
        obj = copy.deepcopy(self.automator_live)
        del obj["results"][0]["submission_route"]
        with self.assertRaises(ContractError):
            self._parse_live(obj)


if __name__ == "__main__":
    unittest.main()
