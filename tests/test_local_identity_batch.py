from copy import deepcopy
import unittest

from scripts import local_identity_batch as batch


PRODUCTS = [
    (1, "focus-session-desk", "app-focus-session-desk-8b00bc4e9082", "8b00bc4e90828c4282463826873aa8dfd2eb93f4", 12807496604, "04b2d7e4eae215855217285f07f8835ffe3cf60dc5aab24ede141d28f563416d"),
    (2, "file-integrity-ledger", "app-file-integrity-ledger-d1108d12f7d1", "d1108d12f7d1697af30400f97c7db39cba5e6791", 12826068537, "9100bbcfba20ed2768e5d2dffcb39c987466377d26a34af1e03cc166071e02ca"),
    (3, "offline-text-diff-desk", "app-offline-text-diff-desk-a7d372800898", "a7d37280089893a9ea4b9ac3336020a920e73e0c", 12815845218, "1a0e4f61dfab52e2cac7317bc28bb4ff34b6aa477974e0430ff360d7e2b4381e"),
    (4, "offline-image-inventory-desk", "app-offline-image-inventory-desk-16b6a772952c", "16b6a772952ca0988f2ae2f8b5f4db2e59ec5877", 12817339804, "0e023bcd74f6035a2a3e1cf4cd785f83033c69785723a5c01f7f69d2c5d7b980"),
]


def spec():
    return {
        "schema_version": 1, "batch_id": "batch-20261029-001",
        "trigger_origin": batch.TRIGGER_ORIGIN, "automation_id": batch.AUTOMATION_ID,
        "dispatch_origin": batch.DISPATCH_ORIGIN,
        "execution_origin": "MANUAL_WINDOWS_TERMINAL",
        "central_repository": batch.CENTRAL_REPOSITORY,
        "central_branch": batch.CENTRAL_BRANCH, "central_head_sha": "a" * 40,
        "scheduled_at": "2026-10-29T00:36:00Z",
        "products": [{
            "batch_index": i, "slug": slug, "request_id": rid, "source_sha": sha,
            "artifact_id": aid, "expected_exe_sha256": exe,
            "identity_return_target": f"products/{slug}/store/approved-identity.json",
        } for i, slug, rid, sha, aid, exe in PRODUCTS],
    }


def ledger():
    jobs, requests = [], []
    for i, slug, rid, sha, aid, exe in PRODUCTS:
        display = " ".join(x.title() for x in slug.split("-"))
        jobs.append({
            "product_type": "APP", "display_name": display, "slug": slug,
            "status": "PRE_IDENTITY_READY", "request_id": rid,
            "source_repository": "shihuiarenjinba-png/AI-App-Factory",
            "source_branch": "codex/" + slug, "source_sha": sha,
            "factory_build_head": sha, "expected_exe_sha256": exe,
            "factory_artifact_id": aid, "artifact_metadata_verified": True,
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "identity_return_target": f"products/{slug}/store/approved-identity.json",
        })
        requests.append({
            "request_id": rid, "slug": slug, "repo": "shihuiarenjinba-png/AI-App-Factory",
            "source_branch": "codex/" + slug, "source_sha": sha,
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "identity_return_target": f"products/{slug}/store/approved-identity.json",
            "status": "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE",
            "allow_local_product_creation": True,
        })
    return {
        "partner_center_local_operator": {"mode": "LOCAL_OPERATOR_ACTIVE__BATCH"},
        "rotation_cohorts": {"app_jobs": jobs, "three_d_jobs": []},
        "user_id_requests": {"items": requests},
    }


def success_result(state, job):
    return {
        "batch_id": state["batch_id"], "batch_index": job["batch_index"],
        "request_id": job["request_id"], "slug": job["slug"],
        "source_sha": job["source_sha"], "source_snapshot_head": job["source_sha"],
        "identity_return_target": job["identity_return_target"],
        "registration_type": job["registration_type"],
        "partner_center_selection": job["partner_center_selection"],
        "queue_job_digest": job["queue_job_digest"],
        "central_head_sha": state["central_head_sha"],
        "source_sync_status": "DOWNLOADED_EXACT_SNAPSHOT",
        "partner_center_search_count": 0, "creation_status": "CREATED",
        "overview_exact_match_count": 1,
        "identity_capture_status": "IDENTITY_CAPTURED__AUTHENTICATED_UI__GITHUB_BOUND",
        "authenticated_partner_center_pass": True,
        "identity_details_observed": True,
        "store_id": "9N12345678ABC",
        "identity_name": "OkinawaDesktopTools.TestProduct",
        "pfn": "OkinawaDesktopTools.TestProduct_j8yefg9jgfh58",
        "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
        "github_return_status": "APPLIED",
        "github_replay_status": "EXISTING_VERIFIED",
        "identity_return_commit_sha": "a" * 40,
        "package_version_gate": "HOLD",
        "store_submission": "NOT_PERFORMED",
        "cross_product_contamination": 0,
        "duplicate_creation": 0,
    }


def synthetic_test_only_verifier(*, state, job, result):
    # Test double only. No production CLI or worker supplies this callback.
    return (job["request_id"] == result["request_id"]
            and state["batch_id"] == result["batch_id"])


class BatchTests(unittest.TestCase):
    def test_discovers_exact_ordered_four(self):
        state = batch.discover(ledger(), spec())
        self.assertEqual(state["discovered_count"], 4)
        self.assertEqual([x["slug"] for x in state["products"]],
                         [x[1] for x in PRODUCTS])

    def test_incomplete_discovery_holds(self):
        value = ledger()
        value["rotation_cohorts"]["app_jobs"].pop()
        with self.assertRaisesRegex(batch.BatchHold, "DISCOVERY_INCOMPLETE"):
            batch.discover(value, spec())

    def test_extra_product_holds_scope(self):
        value = ledger()
        value["rotation_cohorts"]["app_jobs"].append({
            **value["rotation_cohorts"]["app_jobs"][0], "slug": "unexpected",
            "request_id": "app-unexpected-00000000",
        })
        with self.assertRaisesRegex(batch.BatchHold, "SCOPE_CONFLICT"):
            batch.discover(value, spec())

    def test_duplicate_request_id_rejected(self):
        value = spec()
        value["products"][1]["request_id"] = value["products"][0]["request_id"]
        with self.assertRaisesRegex(batch.BatchHold, "DUPLICATE_REQUEST_ID"):
            batch.discover(ledger(), value)

    def test_wrong_source_sha_rejected(self):
        value = spec()
        value["products"][0]["source_sha"] = "f" * 40
        with self.assertRaisesRegex(batch.BatchHold, "BINDING_CONFLICT"):
            batch.discover(ledger(), value)

    def test_wrong_return_target_rejected(self):
        value = spec()
        value["products"][0]["identity_return_target"] = "products/wrong/store/approved-identity.json"
        with self.assertRaisesRegex(batch.BatchHold, "WRONG_IDENTITY_RETURN_TARGET"):
            batch.discover(ledger(), value)

    def test_wrong_registration_type_rejected(self):
        value = ledger()
        value["rotation_cohorts"]["app_jobs"][0]["registration_type"] = "GDK_GAME"
        with self.assertRaises(Exception):
            batch.discover(value, spec())

    def test_single_flight_and_resume_order(self):
        state = batch.discover(ledger(), spec())
        claimed, job = batch.claim_next(state)
        self.assertEqual(job["batch_index"], 1)
        with self.assertRaisesRegex(batch.BatchHold, "SINGLE_FLIGHT"):
            batch.claim_next(claimed)
        resumed = batch.complete_active(claimed, success_result(claimed, job),
                                      independent_evidence_verifier=synthetic_test_only_verifier)
        claimed2, job2 = batch.claim_next(resumed)
        self.assertEqual(job2["batch_index"], 2)
        self.assertEqual(claimed2["active_index"], 2)

    def test_interrupted_claim_resumes_same_job_without_second_claim(self):
        state = batch.discover(ledger(), spec())
        in_flight, first = batch.claim_or_resume(state)
        recovered, same = batch.claim_or_resume(in_flight)
        self.assertEqual(recovered, in_flight)
        self.assertEqual(same, first)
        self.assertEqual(recovered["active_index"], 1)
        self.assertEqual(recovered["processed_count"], 0)
        self.assertEqual(sum(x["state"] == "PROCESSING"
                             for x in recovered["products"]), 1)
        completed = batch.complete_active(recovered, success_result(recovered, same),
                                          independent_evidence_verifier=synthetic_test_only_verifier)
        next_state, second = batch.claim_or_resume(completed)
        self.assertEqual(second["batch_index"], 2)
        self.assertEqual(next_state["active_index"], 2)

    def test_corrupt_inflight_state_rejected_before_resume(self):
        state, first = batch.claim_next(batch.discover(ledger(), spec()))
        state["products"][1]["state"] = "PROCESSING"
        with self.assertRaisesRegex(batch.BatchHold, "ACTIVE_JOB_NOT_UNIQUE"):
            batch.claim_or_resume(state)
        state["products"][1]["state"] = "PENDING"
        state["next_resume_index"] = 2
        with self.assertRaisesRegex(batch.BatchHold, "ACTIVE_JOB_NOT_UNIQUE"):
            batch.claim_or_resume(state)

    def test_replay_same_completed_result_is_idempotent(self):
        state, job = batch.claim_next(batch.discover(ledger(), spec()))
        result = success_result(state, job)
        completed = batch.complete_active(state, result,
                                          independent_evidence_verifier=synthetic_test_only_verifier)
        replay = batch.complete_active(completed, result)
        self.assertEqual(replay["processed_count"], 1)
        self.assertEqual(replay["success_count"], 1)
        self.assertEqual(replay["next_resume_index"], 2)
        altered = dict(result, identity_return_commit_sha="b" * 40)
        with self.assertRaisesRegex(batch.BatchHold, "REPLAY_CONFLICT"):
            batch.complete_active(completed, altered)

    def test_forged_complete_ui_and_cas_json_never_counts_without_verifier(self):
        state, job = batch.claim_next(batch.discover(ledger(), spec()))
        fake = success_result(state, job)
        fake["independent_evidence_verifier"] = True  # untrusted JSON field
        with self.assertRaisesRegex(batch.BatchHold, "VERIFIER_UNAVAILABLE"):
            batch.complete_active(state, fake)
        self.assertEqual(state["success_count"], 0)
        self.assertEqual(state["processed_count"], 0)

    def test_false_or_broken_independent_verifier_fails_closed(self):
        state, job = batch.claim_next(batch.discover(ledger(), spec()))
        result = success_result(state, job)
        with self.assertRaisesRegex(batch.BatchHold, "NOT_VERIFIED"):
            batch.complete_active(state, result,
                                  independent_evidence_verifier=lambda **kwargs: False)
        def broken(**kwargs):
            raise RuntimeError("untrusted evidence")
        with self.assertRaisesRegex(batch.BatchHold, "VERIFICATION_FAILED"):
            batch.complete_active(state, result,
                                  independent_evidence_verifier=broken)
        self.assertEqual(state["success_count"], 0)

    def test_cross_product_identity_stops_batch(self):
        state, job = batch.claim_next(batch.discover(ledger(), spec()))
        result = {key: job[key] for key in
                  ("request_id", "slug", "source_sha", "identity_return_target")}
        result["request_id"] = PRODUCTS[1][2]
        result.update(github_return_status="APPLIED", package_version_gate="HOLD",
                      store_submission="NOT_PERFORMED")
        with self.assertRaisesRegex(batch.BatchHold, "CONTAMINATION"):
            batch.complete_active(state, result)


    def test_status_only_applied_never_counts_as_success(self):
        state, job = batch.claim_next(batch.discover(ledger(), spec()))
        fake = {key: job[key] for key in
                ("request_id", "slug", "source_sha", "identity_return_target")}
        fake.update(github_return_status="APPLIED", package_version_gate="HOLD",
                    store_submission="NOT_PERFORMED")
        with self.assertRaisesRegex(batch.BatchHold, "SUCCESS_EVIDENCE_INCOMPLETE"):
            batch.complete_active(state, fake)

    def test_missing_replay_or_wrong_identity_rejected(self):
        state, job = batch.claim_next(batch.discover(ledger(), spec()))
        result = success_result(state, job)
        result["github_replay_status"] = "NOT_RUN"
        with self.assertRaisesRegex(batch.BatchHold, "SUCCESS_EVIDENCE_INCOMPLETE"):
            batch.complete_active(state, result)
        result["github_replay_status"] = "EXISTING_VERIFIED"
        result["package_sid"] = "invalid"
        with self.assertRaisesRegex(batch.BatchHold, "IDENTITY_SCHEMA_INVALID"):
            batch.complete_active(state, result)

    def test_authentication_failure_stops_entire_batch(self):
        state, job = batch.claim_next(batch.discover(ledger(), spec()))
        result = {key: job[key] for key in
                  ("request_id", "slug", "source_sha", "identity_return_target")}
        result.update(github_return_status="HOLD", package_version_gate="HOLD",
                      store_submission="NOT_PERFORMED",
                      error_code="HOLD_MFA_REQUIRED")
        with self.assertRaisesRegex(batch.BatchHold, "GLOBAL_STOP_REQUIRED"):
            batch.complete_active(state, result)

    def test_product_hold_can_advance_one_index(self):
        state, job = batch.claim_next(batch.discover(ledger(), spec()))
        result = {key: job[key] for key in
                  ("request_id", "slug", "source_sha", "identity_return_target")}
        result.update(github_return_status="HOLD", package_version_gate="HOLD",
                      store_submission="NOT_PERFORMED",
                      error_code="HOLD_NAME_UNAVAILABLE")
        resumed = batch.complete_active(state, result)
        self.assertEqual(resumed["hold_count"], 1)
        next_state, next_job = batch.claim_next(resumed)
        self.assertEqual(next_job["batch_index"], 2)

    def test_four_claimed_successes_still_require_host_schedule_proof(self):
        state = batch.discover(ledger(), spec())
        self.assertFalse(state["execution_trigger_proven"])
        for _ in range(4):
            state, job = batch.claim_next(state)
            state = batch.complete_active(state, success_result(state, job),
                                          independent_evidence_verifier=synthetic_test_only_verifier)
        self.assertEqual(state["success_count"], 4)
        self.assertEqual(state["final_status"], "MULTI_PRODUCT_IDENTITY_BATCH_PARTIAL")

    def test_trusted_manual_execution_can_complete_batch(self):
        state = batch.discover(ledger(), spec())
        state = batch.attest_local_execution(
            state, "MANUAL_WINDOWS_TERMINAL",
            verifier=lambda **kwargs: True,
        )
        for _ in range(4):
            state, job = batch.claim_next(state)
            state = batch.complete_active(
                state, success_result(state, job),
                independent_evidence_verifier=synthetic_test_only_verifier,
            )
        self.assertEqual(state["final_status"], "MULTI_PRODUCT_IDENTITY_BATCH_PASS")


    def test_schedule_trigger_must_be_proven(self):
        value = spec()
        value["trigger_origin"] = "MANUAL_RUN_NOW"
        with self.assertRaisesRegex(batch.BatchHold, "TRIGGER_NOT_PROVEN"):
            batch.discover(ledger(), value)


if __name__ == "__main__":
    unittest.main()
