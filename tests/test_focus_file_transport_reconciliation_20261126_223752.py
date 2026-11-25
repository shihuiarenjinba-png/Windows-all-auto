import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "ops" / "active_e2e_handoff.json"
QUEUE = ROOT / "ops" / "completion_rush_queue_20261116.json"
OVERLAY = ROOT / "ops" / "active_e2e_handoff_overlay_20261126_223752.json"
RECON = ROOT / "ops" / "focus_file_transport_reconciliation_20261126_223752.json"

HEAD = "6ff05c0a3b682ade5016894c08c9edfbdf75e375"
PARENT = "dbd714347c198e6922ac6596b64240c61c7d4db4"
CI_RUNS = [45707767241, 45707766948, 45707766837]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class CurrentHeadReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = read(LEDGER)
        cls.queue = read(QUEUE)
        cls.overlay = read(OVERLAY)
        cls.recon = read(RECON)

    def test_live_pr165_head_and_exact_head_ci_are_reconciled(self):
        obs = self.ledger["current_pr165_head_observation_20261126_223752"]
        self.assertEqual(obs["head_sha"], HEAD)
        self.assertEqual(obs["parent_sha"], PARENT)
        self.assertEqual([x["run_id"] for x in obs["exact_head_ci"]], CI_RUNS)
        self.assertTrue(all(x["head_sha"] == HEAD and x["conclusion"] == "success"
                            for x in obs["exact_head_ci"]))
        self.assertEqual(obs["exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertTrue(obs["repository_ci_is_not_product_e2e"])
        self.assertEqual(obs["product_e2e_status"], "HOLD")
        self.assertIs(obs["e2e_pass"], False)
        self.assertEqual([x["run_id"] for x in obs["parent_exact_head_ci"]],
                         [45707537321, 45707537431, 45707537270])
        self.assertEqual(obs["parent_exact_head_ci_status"], "PASS_EXACT_HEAD_CI")
        self.assertEqual(self.ledger["current_live_head_reconciliation_20261126_223752"]["actual_pr165_head"], HEAD)
        self.assertIs(self.ledger["current_live_head_reconciliation_20261126_223752"]["active_ledger_reconciled"], True)
        self.assertEqual(self.ledger["e2e_status"], "HOLD")
        self.assertIs(self.ledger["e2e_pass"], False)
        self.assertIsNone(self.ledger["current_active_product"])
        self.assertIs(self.ledger["active_product_is_historical"], True)

    def test_focus_and_file_identity_version_and_package_gates_remain_separate(self):
        products = self.recon["products"]
        focus = products["focus_session_desk"]
        self.assertEqual(focus["current_source_sha"], "fb6293839bc7b0bbff0a6d1d3c04e2f8f5942e79")
        self.assertEqual(focus["approved_identity_source_sha"], "8b00bc4e90828c4282463826873aa8dfd2eb93f4")
        self.assertNotEqual(focus["approved_identity_source_sha"], focus["current_source_sha"])
        self.assertEqual(focus["current_source_identity_binding_status"],
                         "REVALIDATION_REQUIRED_AFTER_SOURCE_HEAD_CHANGE")
        self.assertEqual(focus["current_source_request_status"],
                         "GENERATED__DRY_RUN_ARTIFACT_VERIFIED__IDENTITY_READBACK_PENDING")
        self.assertEqual(focus["current_source_request_artifact_id"], 15049692591)
        self.assertIs(focus["current_source_request_artifact_verified"], True)
        self.assertEqual(focus["official_identity_status"], "NOT_COLLECTED")
        self.assertIsNone(focus["package_version"])
        self.assertEqual(focus["msix_export"]["status"], "FAILED_MISSING_VERIFIED_VERSION")
        self.assertEqual(focus["msix_export"]["artifact_count"], 0)
        self.assertIs(focus["real_msix"], False)

        file_product = products["file_integrity_ledger"]
        self.assertEqual(file_product["current_source_sha"], "33d612be2774ac155ea3d85289ec5cb7981c81c1")
        self.assertEqual(file_product["historical_approved_identity_source_sha"],
                         "d1108d12f7d1697af30400f97c7db39cba5e6791")
        self.assertIs(file_product["current_source_approved_identity_present"], False)
        self.assertEqual(file_product["current_source_request_status"],
                         "DRY_RUN__OFFICIAL_IDENTITY_UNVERIFIED__PACKAGE_NOT_BUILT__LOCAL_WINDOWS_BUILD_NOT_IMPLEMENTED")
        self.assertEqual(file_product["current_source_request_artifact_id"], 14934034365)
        self.assertIs(file_product["current_source_request_artifact_verified"], True)
        self.assertEqual(file_product["official_identity_status"], "UNVERIFIED")
        self.assertEqual(file_product["package_status"], "NOT_BUILT")
        self.assertIsNone(file_product["package_version"])
        self.assertIs(file_product["human_owner_visual_review_required"], True)
        self.assertEqual(file_product["msix_export"]["status"], "SKIPPED_NO_ARTIFACT")
        self.assertEqual(file_product["msix_export"]["artifact_count"], 0)
        self.assertIs(file_product["real_msix"], False)

    def test_queue_overlay_and_reconciliation_agree_on_holds_and_downstream_receipts(self):
        queue_obs = self.queue["latest_observation_20261126_223752"]
        self.assertEqual(queue_obs["central_head"], HEAD)
        self.assertEqual([x["run_id"] for x in queue_obs["exact_head_ci"]], CI_RUNS)
        self.assertIs(queue_obs["real_msix"], False)
        self.assertEqual(queue_obs["store_upload_test_eligible_products"], 0)
        focus = next(x for x in self.queue["priority"] if x["product"] == "Focus Session Desk")
        file_product = next(x for x in self.queue["priority"] if x["product"] == "File Integrity Ledger")
        self.assertEqual(focus["current_source_request_artifact_id"], 15049692591)
        self.assertEqual(file_product["current_source_request_artifact_id"], 14934034365)
        self.assertIsNone(focus["package_version"])
        self.assertIsNone(file_product["package_version"])
        self.assertIs(focus["real_msix"], False)
        self.assertIs(file_product["real_msix"], False)

        for data in (self.overlay, self.recon):
            self.assertEqual(data["status"], "HOLD")
            self.assertIs(data["e2e_pass"], False)
            self.assertEqual(data["pr165"]["head_sha"], HEAD)
            self.assertEqual([x["run_id"] for x in data["pr165"]["exact_head_ci"]], CI_RUNS)
            self.assertTrue(data["pr165"]["repository_ci_is_not_product_e2e"])
            self.assertEqual(data["first_unconnected_interval"]["status"], "BLOCKED_BEFORE_REAL_MSIX_BUILD")
            self.assertTrue(all(value is False for value in data["downstream_receipts"].values()))
            self.assertEqual(data["store_upload_test"]["eligible_fresh_unsold_products"], 0)
            self.assertIs(data["store_upload_test"]["dry_run_started"], False)
            for key in ("store_submission_allowed", "certification_allowed", "publish_allowed",
                        "live_partner_center_write_allowed", "merge_allowed", "force_push_allowed"):
                self.assertIs(data["safety"][key], False)

    def test_pr161_pr171_and_pr183_are_not_misclassified_as_product_e2e(self):
        self.assertEqual(self.recon["pr161"]["head_sha"], "71d9c2125b6aed44a86ca1872d48ad19963f3e63")
        self.assertEqual(self.recon["pr161"]["exact_head_ci"][0]["run_id"], 42712757936)
        self.assertIs(self.recon["pr161"]["product_e2e"], False)
        self.assertEqual(self.recon["pr171"]["head_sha"], "764721021f13be96364529650b44fb439770bac9")
        self.assertEqual(self.recon["pr171"]["exact_head_ci"][0]["run_id"], 44437197470)
        self.assertIs(self.recon["pr171"]["store_upload_dry_run_started"], False)
        self.assertEqual(self.recon["pr171"]["eligible_fresh_unsold_products"], 0)
        pr183 = self.recon["pr183"]
        self.assertEqual(pr183["comparison_to_current_pr165_head"]["ahead_by"], 12)
        self.assertEqual(pr183["comparison_to_current_pr165_head"]["behind_by"], 64)
        self.assertEqual(pr183["decision"], "DO_NOT_RESTACK_WHOLE_PR__SELECTIVELY_REAPPLY_LOCAL_PULL_CUSTODY")
        self.assertEqual(self.recon["local_code_sync"]["receipt_status"], "NOT_OBSERVED__CLOUD_PASS_ONLY")


if __name__ == "__main__":
    unittest.main()
