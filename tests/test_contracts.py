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


if __name__ == "__main__":
    unittest.main()
