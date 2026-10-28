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
        result = {key: job[key] for key in
                  ("request_id", "slug", "source_sha", "identity_return_target")}
        result.update(github_return_status="APPLIED", package_version_gate="HOLD",
                      store_submission="NOT_PERFORMED")
        resumed = batch.complete_active(claimed, result)
        claimed2, job2 = batch.claim_next(resumed)
        self.assertEqual(job2["batch_index"], 2)
        self.assertEqual(claimed2["active_index"], 2)

    def test_cross_product_identity_stops_batch(self):
        state, job = batch.claim_next(batch.discover(ledger(), spec()))
        result = {key: job[key] for key in
                  ("request_id", "slug", "source_sha", "identity_return_target")}
        result["request_id"] = PRODUCTS[1][2]
        result.update(github_return_status="APPLIED", package_version_gate="HOLD",
                      store_submission="NOT_PERFORMED")
        with self.assertRaisesRegex(batch.BatchHold, "CONTAMINATION"):
            batch.complete_active(state, result)

    def test_schedule_trigger_must_be_proven(self):
        value = spec()
        value["trigger_origin"] = "MANUAL_RUN_NOW"
        with self.assertRaisesRegex(batch.BatchHold, "TRIGGER_NOT_PROVEN"):
            batch.discover(ledger(), value)


if __name__ == "__main__":
    unittest.main()
