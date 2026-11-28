"""Append-only 01:10 reconciliation for PR165, PR220 transport and product HOLD gates."""
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OVERLAY=ROOT/"ops/active_e2e_handoff_overlay_20261129_0110.json"
QUEUE=ROOT/"ops/completion_rush_queue_20261129_0110.json"
LEDGER_BLOB="86c5f81660c18f4893cdf2dd0c0922934f365126"
LEDGER_COMMIT="afced8eb3a08244e036ff66582a6639102622e31"
PR165_HEAD="a4eea4096673813cb91c6c70f1711b637c356f3b"
PR220_HEAD="9526f0849b5b0728986a3bd332ee3fd1288a2d70"
PR220_RUNS=[46163629226,46163629251,46163629215]


class CurrentLiveProductReconciliation0110Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.overlay=json.loads(OVERLAY.read_text(encoding="utf-8"))
        cls.queue=json.loads(QUEUE.read_text(encoding="utf-8"))

    def test_canonical_ledger_is_preserved_and_overlay_is_append_only(self):
        pointer=self.overlay["canonical_ledger_reconciliation"]
        self.assertEqual(pointer["blob_sha"],LEDGER_BLOB)
        self.assertEqual(pointer["canonical_ledger_commit_sha"],LEDGER_COMMIT)
        self.assertFalse(pointer["canonical_json_mutated"])
        self.assertTrue(pointer["append_only_overlay_is_current"])
        self.assertEqual(pointer["latest_canonical_observation_key"],"latest_execution_reconciliation_20261129_0058")
        self.assertEqual(self.queue["source_observation"]["canonical_ledger_blob_sha"],LEDGER_BLOB)
        self.assertEqual(self.queue["source_observation"]["overlay_path"],"ops/active_e2e_handoff_overlay_20261129_0110.json")

    def test_parent_pr165_head_and_exact_ci_are_directly_reconciled(self):
        pr=self.overlay["pr165"]
        self.assertEqual(pr["head_sha_at_observation"],PR165_HEAD)
        self.assertEqual(pr["head_compare"],{"status":"ahead","ahead_by":358,"behind_by":0})
        self.assertEqual(pr["product_code_head_sha"],"71f07b71bf13374f78320fb1e5f9882c8f37b63e")
        self.assertEqual([x["run_id"] for x in pr["exact_head_ci"]],[46162808044,46162808104,46162808059])
        self.assertTrue(all(x["head_sha"]==PR165_HEAD and x["conclusion"]=="success" for x in pr["exact_head_ci"]))
        self.assertEqual(pr["product_e2e_status"],"HOLD")
        self.assertFalse(pr["real_msix"])

    def test_pr220_exact_head_transport_and_windows_ubuntu_ci_pass(self):
        pr=self.overlay["pr220"]
        self.assertEqual(pr["head_sha"],PR220_HEAD)
        self.assertEqual(pr["base_sha"],PR165_HEAD)
        self.assertEqual(pr["head_compare"],{"status":"ahead","ahead_by":8,"behind_by":0})
        self.assertEqual([x["run_id"] for x in pr["exact_head_ci"]],PR220_RUNS)
        self.assertTrue(all(x["head_sha"]==PR220_HEAD and x["conclusion"]=="success" for x in pr["exact_head_ci"]))
        self.assertEqual(pr["exact_head_ci_status"],"PASS_EXACT_HEAD_CI")
        self.assertTrue(pr["synthetic_fixture_only"])
        self.assertEqual(pr["synthetic_fixture_status"],"PASS")
        self.assertEqual(pr["synthetic_fixture_marker"],"QA_FIXTURE_ONLY_NOT_PRODUCT")
        self.assertEqual(pr["product_e2e_status"],"HOLD")

    def test_transport_contract_does_not_claim_a_real_product_receipt(self):
        transport=self.overlay["transport_contract"]
        self.assertEqual(transport["exact_head_sha"],PR220_HEAD)
        self.assertEqual(transport["status"],"IMPLEMENTED_FAIL_CLOSED__PR220_EXACT_HEAD_CI_PASS")
        self.assertTrue(transport["synthetic_integration_fixture_status"]=="PASS")
        self.assertFalse(transport["real_product_msix_received"])
        self.assertFalse(transport["real_product_local_pull_receipt"])
        self.assertFalse(transport["real_product_checker_receipt"])
        self.assertFalse(self.overlay["first_unconnected_interval"]["real_product_msix_received"])

    def test_focus_and_file_identity_version_and_real_package_gates_remain_held(self):
        products=self.overlay["products"]
        focus=products["focus_session_desk"]
        self.assertEqual(focus["identity"]["current_source_binding_status"],"STALE_HISTORICAL_SOURCE_MISMATCH")
        self.assertIsNone(focus["package_version"])
        self.assertFalse(focus["real_msix"])
        filep=products["file_integrity_ledger"]
        self.assertFalse(filep["identity"]["current_source_approved_identity_present"])
        self.assertIsNone(filep["package_version"])
        self.assertFalse(filep["real_msix"])

    def test_store_and_merge_safety_remain_closed(self):
        safety=self.overlay["safety"]
        for field in ("store_submission_allowed","certification_allowed","publish_allowed","partner_center_write","identity_write","version_write","merge_allowed","force_push_allowed","main_release_write_allowed"):
            self.assertFalse(safety[field])
        self.assertEqual(self.overlay["store_upload_test"]["eligible_fresh_unsold_products"],0)
        self.assertEqual(self.queue["status"],"HOLD")
        self.assertFalse(self.queue["e2e_pass"])
        self.assertEqual(self.queue["pr220"]["exact_head_ci_status"],"PASS_EXACT_HEAD_CI")


if __name__=="__main__":
    unittest.main()
