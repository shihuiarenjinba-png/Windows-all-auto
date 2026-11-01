"""Regression guards for the mixed APP identity batch and evidence-only ledger.

These tests intentionally read the checked-in central ledger; they do not call
Partner Center, change a Factory source, or assert physical Windows success.
"""
import json
import unittest
from pathlib import Path


LEDGER = Path(__file__).resolve().parents[1] / "ops" / "active_e2e_handoff.json"
EXPECTED = (
    ("Focus Session Desk", "focus-session-desk",
     "app-focus-session-desk-8b00bc4e9082",
     "8b00bc4e90828c4282463826873aa8dfd2eb93f4",
     "8a7139375524830bf823469526837259266172be"),
    ("File Integrity Ledger", "file-integrity-ledger",
     "app-file-integrity-ledger-d1108d12f7d1",
     "d1108d12f7d1697af30400f97c7db39cba5e6791",
     "db9a57af822788af4c8384499a6e343ec7b0353d"),
    ("Offline Text Diff Desk", "offline-text-diff-desk",
     "app-offline-text-diff-desk-a7d372800898",
     "a7d37280089893a9ea4b9ac3336020a920e73e0c", None),
    ("Offline Image Inventory Desk", "offline-image-inventory-desk",
     "app-offline-image-inventory-desk-16b6a772952c",
     "16b6a772952ca0988f2ae2f8b5f4db2e59ec5877", None),
)


class IdentityBatch4LedgerRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.jobs = cls.data["rotation_cohorts"]["app_jobs"]
        cls.pipeline = {p["product"]: p for p in cls.data["post_identity_pipeline"]["products"]}
        cls.batch = cls.data["multi_product_partner_center_batch_4"]
        cls.results = cls.batch["products"]

    def test_exact_four_product_isolation_and_unique_job_contract(self):
        self.assertEqual(len(self.jobs), 4)
        self.assertEqual(len(self.results), 4)
        self.assertEqual([j["display_name"] for j in self.jobs], [e[0] for e in EXPECTED])
        self.assertEqual([p["product"] for p in self.results], [e[0] for e in EXPECTED])
        for field in ("request_id", "slug", "source_sha", "identity_return_target"):
            values = [j[field] for j in self.jobs]
            self.assertEqual(len(values), len(set(values)), field)
        for i, (name, slug, request, source, returned) in enumerate(EXPECTED):
            with self.subTest(product=name):
                job, batch, pipeline = self.jobs[i], self.results[i], self.pipeline[name]
                self.assertEqual(batch["batch_index"], i + 1)
                self.assertEqual((job["slug"], job["request_id"], job["source_sha"]),
                                 (slug, request, source))
                self.assertEqual((batch["slug"], batch["request_id"], batch["source_sha"]),
                                 (slug, request, source))
                self.assertEqual((pipeline["request_id"], pipeline["source_sha"]),
                                 (request, source))
                self.assertEqual(job["registration_type"], "MSIX_OR_PWA_APP")
                self.assertEqual(job["partner_center_selection"], "MSIX or PWA app")
                self.assertEqual(job["identity_return_target"],
                                 f"products/{slug}/store/approved-identity.json")
                self.assertEqual(batch["identity_return_commit_sha"], returned)

    def test_post_identity_products_never_reenter_pre_identity_queue(self):
        for i, (name, _, _, source, commit) in enumerate(EXPECTED[:2]):
            with self.subTest(product=name):
                job, pipeline, batch = self.jobs[i], self.pipeline[name], self.results[i]
                self.assertEqual(job["status"], "POST_IDENTITY_READY")
                self.assertEqual(pipeline["state"], "POST_IDENTITY_READY")
                self.assertEqual(pipeline["identity_status"], "CAS_RETURN_COMMIT_GITHUB_VERIFIED")
                self.assertEqual(job["identity_return_commit_sha"], commit)
                self.assertEqual(pipeline["identity_return_commit_sha"], commit)
                self.assertEqual(job["source_sha"], source)  # immutable pre-identity source
                self.assertNotEqual(job["observed_pr_head"], source)
                self.assertFalse(job["identity_cas_allowed"])
                self.assertEqual(batch["source_sync_status"], "LOCAL_NOT_RUN")
                self.assertEqual(batch["package_version_gate"], "HOLD")

    def test_remaining_pre_identity_jobs_do_not_inherit_identity(self):
        for i, (name, _, _, _, _) in enumerate(EXPECTED[2:], start=2):
            with self.subTest(product=name):
                job, pipeline, batch = self.jobs[i], self.pipeline[name], self.results[i]
                self.assertEqual(job["status"], "PRE_IDENTITY_READY")
                self.assertEqual(pipeline["identity_status"], "PRE_IDENTITY_READY__NO_APPROVED_FILE")
                self.assertIsNone(pipeline["identity_return_commit_sha"])
                self.assertIsNone(batch["identity_return_commit_sha"])
                self.assertEqual(batch["github_return_status"], "NOT_RUN")
                self.assertEqual(batch["identity_capture_status"], "NOT_RUN")
                self.assertFalse(job["identity_cas_allowed"])
                self.assertEqual(job["real_msix"], "NOT_BUILT")

    def test_cloud_discovery_is_not_local_batch_or_scheduled_trigger(self):
        gates = self.data["revision_review_reconciliation"]["cross_lane_gates"]
        self.assertEqual(self.batch["cloud_preflight_discovered_count"], 4)
        self.assertEqual(self.batch["local_batch_discovered_count"], 0)
        self.assertEqual(self.batch["processed_count"], 0)
        self.assertEqual(self.batch["success_count"], 0)
        self.assertEqual(self.batch["next_resume_index"], 3)
        self.assertEqual(self.batch["trigger_proof"], "BATCH_SCHEDULE_TRIGGER_NOT_PROVEN")
        self.assertNotEqual(self.batch["trigger_origin"], "SCHEDULED_TRIGGER_PROVEN")
        self.assertEqual((gates["app_batch_cloud_discovered"],
                          gates["app_github_identity_returned"],
                          gates["app_pre_identity_pending"],
                          gates["app_local_processed"]), (4, 2, 2, 0))
        for key in ("scheduled_trigger_proven", "physical_local_code_sync_receipt_verified",
                    "local_task_scheduler_last_result_verified"):
            self.assertFalse(gates[key], key)

    def test_offline_notes_reference_is_not_a_bound_request(self):
        notes = self.pipeline["Offline Notes Canary"]
        self.assertEqual(notes["state"], "HOLD_SOURCE_REQUEST_BINDING")
        self.assertEqual(notes["identity_status"],
                         "USER_IDENTITY_REFERENCE_RECEIVED__SOURCE_REQUEST_UNBOUND")
        self.assertIsNone(notes["source_sha"])
        self.assertIsNone(notes["request_id"])
        self.assertIsNone(notes["identity_return_commit_sha"])
        request = next(p for p in self.data["user_id_requests"]["items"]
                       if p["product_name"] == "Offline Notes Canary")
        self.assertEqual(request["status"], "NOT_YET_REQUIRED")
        self.assertEqual(request["identity_reference_status"], "USER_IDENTITY_RECEIVED_UNBOUND")
        self.assertIsNone(request["source_sha"])
        self.assertIsNone(request["request_id"])

    def test_real_product_e2e_gates_remain_fail_closed(self):
        gates = self.data["revision_review_reconciliation"]["cross_lane_gates"]
        for key in ("real_msix_pass", "github_real_product_backlog_pass",
                    "local_pull_pass", "checker_pass", "gui_install_pass", "e2e_pass"):
            self.assertFalse(gates[key], key)
        self.assertFalse(self.data["e2e_pass"])
        quality = self.data["quality_gates"]
        for key in ("real_msix_pass", "github_backlog_real_product_pass",
                    "local_pull_pass", "checker_pass", "gui_qa_pass", "e2e_pass",
                    "local_source_code_sync_physical_pass",
                    "local_source_code_sync_scheduler_pass"):
            self.assertFalse(quality[key], key)
        for product in self.pipeline.values():
            self.assertEqual(product["gates"]["package_version"], "HOLD_NOT_APPROVED")
            self.assertEqual(product["gates"]["github_backlog"], "NOT_QUEUED_REAL_PACKAGE")
            self.assertEqual(product["gates"]["local_pull"], "NOT_RUN")
            self.assertEqual(product["gates"]["windows_checker"], "NOT_RUN")
            self.assertEqual(product["gates"]["gui_install_qa"], "NOT_RUN")
            self.assertEqual(product["gates"]["store_final_submission"], "NOT_PERFORMED")

    def test_market_review_head_cannot_promote_image_pre_identity_source(self):
        image = self.data["revision_review_reconciliation"]["observations"]["offline-image-inventory-desk"]
        old = self.jobs[3]
        self.assertEqual(image["score"], 64)
        self.assertEqual(image["independent_buyers_completed"], 0)
        self.assertFalse(image["why_pay_verified"])
        self.assertEqual(image["market_fit_gate"], "MARKET_FIT_HOLD")
        self.assertFalse(image["current_review_revision_promoted"])
        self.assertEqual(image["immutable_pre_identity_source_sha"], old["source_sha"])
        self.assertNotEqual(image["current_review_head_sha"], old["source_sha"])
        self.assertIsNone(image["new_revision_request_id"])
        self.assertIsNone(image["new_revision_source_sha"])


if __name__ == "__main__":
    unittest.main()
