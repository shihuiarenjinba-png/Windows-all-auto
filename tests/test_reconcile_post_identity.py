"""Offline contract tests: no browser, network, CAS or Store writes."""
import copy
import json
import unittest

from scripts.reconcile_post_identity import ReconcileHold, reconcile_approved_return

SOURCE = "a" * 40
RETURN = "b" * 40
EXE = "c" * 64
REPO = "shihuiarenjinba-png/AI-App-Factory"
BRANCH = "codex/test-app"


def fixture():
    job = {
        "product_type": "APP", "display_name": "Test App",
        "slug": "test-app", "status": "PRE_IDENTITY_READY",
        "registration_type": "MSIX_OR_PWA_APP",
        "partner_center_selection": "MSIX or PWA app",
        "request_id": "app-test-app-aaaaaaaaaaaa",
        "source_repository": REPO, "source_branch": BRANCH,
        "source_sha": SOURCE, "expected_exe_sha256": EXE,
        "identity_return_target": "products/test-app/store/approved-identity.json",
    }
    ledger = {
        "rotation_cohorts": {"app_jobs": [job], "three_d_jobs": []},
        "user_id_requests": {"items": [{
            "request_id": job["request_id"], "status": "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE",
            "product_name": job["display_name"], "repo": REPO,
            "source_branch": BRANCH, "source_sha": SOURCE,
            "identity_return_target": job["identity_return_target"],
            "product_type": "APP", "slug": "test-app",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "requested_fields": ["Store ID"], "allow_local_product_creation": True,
        }]},
        "registration_router": {"entries": [{"product": "Test App",
            "repository": REPO,
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "identity_status": "LOCAL_OPERATOR_ACTIVE"}]},
        "post_identity_pipeline": {"products": [{
            "product": "Test App", "lane": "APP",
            "request_id": job["request_id"],
            "source_repository": REPO, "source_branch": BRANCH,
            "source_sha": SOURCE,
            "identity_return_target": job["identity_return_target"],
            "state": "WAITING_IDENTITY_CAPTURE_AND_CAS",
        }]},
    }
    approved = {
        "reviewed": True, "source": "partner_center",
        "request_id": job["request_id"], "product_type": "APP",
        "source_repository": REPO, "source_branch": BRANCH,
        "source_sha": SOURCE, "expected_head_sha": SOURCE,
        "package_sha256": EXE, "package_version_gate": "HOLD",
        "store_id": "9P6452C61N7B", "name": "OkinawaDesktopTools.TestApp",
        "reserved_display_name": "Test App", "publisher_display_name": "Test Publisher",
        "publisher": "CN=Test", "package_family_name": "OkinawaDesktopTools.TestApp_j8yefg9jgfh58",
        "package_sid": "S-1-15-2-1-2-3-4-5-6-7",
    }
    return ledger, approved


def reconcile(ledger, approved, head=RETURN, ancestry=True):
    return reconcile_approved_return(
        ledger, "test-app",
        fetch_branch_head=lambda repo, branch: head,
        verify_source_ancestry=lambda repo, source, actual, target: (
            ancestry and target == "products/test-app/store/approved-identity.json"),
        fetch_approved_file=lambda repo, path, branch: (
            json.dumps(approved) if isinstance(approved, dict) else approved
        ),
    )


class ReconcileTests(unittest.TestCase):
    def test_valid_promotion_and_immutable_input(self):
        ledger, approved = fixture()
        original = copy.deepcopy(ledger)
        result, status = reconcile(ledger, approved)
        self.assertEqual(status, "POST_IDENTITY_READY")
        self.assertEqual(ledger, original)
        job = result["rotation_cohorts"]["app_jobs"][0]
        self.assertEqual(job["source_sha"], SOURCE)
        self.assertEqual(job["identity_return_commit_sha"], RETURN)
        self.assertEqual(job["status"], "POST_IDENTITY_READY")
        self.assertEqual(job["package_version_gate"], "HOLD")
        self.assertFalse(job["identity_cas_allowed"])
        self.assertEqual(result["user_id_requests"]["items"][0]["requested_fields"], [])
        self.assertEqual(result["post_identity_pipeline"]["products"][0]["state"],
                         "POST_IDENTITY_READY")

    def test_approved_file_read_uses_immutable_verified_head(self):
        ledger, approved = fixture()
        observed = []
        result, transition = reconcile_approved_return(
            ledger, "test-app",
            fetch_branch_head=lambda repo, branch: RETURN,
            verify_source_ancestry=lambda *_: True,
            fetch_approved_file=lambda repo, target, ref: (
                observed.append((repo, target, ref)) or json.dumps(approved)),
        )
        self.assertEqual(transition, "POST_IDENTITY_READY")
        self.assertEqual(observed, [(REPO,
            "products/test-app/store/approved-identity.json", RETURN)])
        self.assertNotEqual(observed[0][2], BRANCH)

    def test_factory_head_rechecked_after_immutable_reads(self):
        ledger, approved = fixture()
        observed = []
        result, transition = reconcile_approved_return(
            ledger, "test-app",
            fetch_branch_head=lambda *_: (observed.append(RETURN) or RETURN),
            verify_source_ancestry=lambda *_: True,
            fetch_approved_file=lambda *_: json.dumps(approved),
        )
        self.assertEqual(transition, "POST_IDENTITY_READY")
        self.assertEqual(observed, [RETURN, RETURN])
        self.assertEqual(result["rotation_cohorts"]["app_jobs"][0]
                         ["identity_return_commit_sha"], RETURN)

    def test_factory_head_drift_during_identity_read_holds_without_mutation(self):
        ledger, approved = fixture()
        original = copy.deepcopy(ledger)
        heads = iter((RETURN, "d" * 40))
        with self.assertRaisesRegex(ReconcileHold, "HOLD_FACTORY_HEAD_DRIFT"):
            reconcile_approved_return(
                ledger, "test-app",
                fetch_branch_head=lambda *_: next(heads),
                verify_source_ancestry=lambda *_: True,
                fetch_approved_file=lambda *_: json.dumps(approved),
            )
        self.assertEqual(ledger, original)

    def test_factory_head_drift_during_market_fit_read_holds(self):
        ledger, approved = fixture()
        current = [RETURN]
        def read_market_fit(*_):
            current[0] = "d" * 40
            return None
        with self.assertRaisesRegex(ReconcileHold, "HOLD_FACTORY_HEAD_DRIFT"):
            reconcile_approved_return(
                ledger, "test-app",
                fetch_branch_head=lambda *_: current[0],
                verify_source_ancestry=lambda *_: True,
                fetch_approved_file=lambda *_: json.dumps(approved),
                fetch_market_fit=read_market_fit,
            )
        self.assertEqual(ledger["rotation_cohorts"]["app_jobs"][0]["status"],
                         "PRE_IDENTITY_READY")

    def test_factory_head_drift_on_post_replay_holds(self):
        ledger, approved = fixture()
        promoted, _ = reconcile(ledger, approved)
        original = copy.deepcopy(promoted)
        heads = iter((RETURN, "e" * 40))
        with self.assertRaisesRegex(ReconcileHold, "HOLD_FACTORY_HEAD_DRIFT"):
            reconcile_approved_return(
                promoted, "test-app",
                fetch_branch_head=lambda *_: next(heads),
                verify_source_ancestry=lambda *_: True,
                fetch_approved_file=lambda *_: json.dumps(approved),
            )
        self.assertEqual(promoted, original)

    def test_user_identity_request_cross_product_binding_holds(self):
        for field, wrong in (
            ("product_name", "Different App"),
            ("repo", "shihuiarenjinba-png/Other-Factory"),
            ("source_branch", "codex/other"),
            ("source_sha", "d" * 40),
            ("identity_return_target", "products/other/store/approved-identity.json"),
            ("product_type", "GAME"),
            ("slug", "different-app"),
        ):
            with self.subTest(field=field):
                ledger, approved = fixture()
                ledger["user_id_requests"]["items"][0][field] = wrong
                original = copy.deepcopy(ledger)
                with self.assertRaisesRegex(
                        ReconcileHold, "HOLD_USER_ID_REQUEST_SOURCE_CONFLICT"):
                    reconcile(ledger, approved)
                self.assertEqual(ledger, original)

    def test_user_identity_request_exact_binding_is_accepted(self):
        ledger, approved = fixture()
        request = ledger["user_id_requests"]["items"][0]
        job = ledger["rotation_cohorts"]["app_jobs"][0]
        request.update({
            "product_name": job["display_name"], "repo": REPO,
            "source_branch": BRANCH, "source_sha": SOURCE,
            "identity_return_target": job["identity_return_target"],
            "product_type": "APP", "slug": "test-app",
        })
        result, transition = reconcile(ledger, approved)
        self.assertEqual(transition, "POST_IDENTITY_READY")
        self.assertEqual(result["user_id_requests"]["items"][0]["status"],
                         "USER_IDENTITY_RECEIVED")

    def test_missing_canonical_request_binding_fails_closed(self):
        fields = ("product_name", "repo", "source_branch", "source_sha",
                  "identity_return_target", "product_type", "slug",
                  "registration_type", "partner_center_selection")
        for field in fields:
            for invalid in ("missing", "empty", "null"):
                with self.subTest(field=field, invalid=invalid):
                    ledger, approved = fixture()
                    request = ledger["user_id_requests"]["items"][0]
                    if invalid == "missing":
                        request.pop(field)
                    else:
                        request[field] = "" if invalid == "empty" else None
                    original = copy.deepcopy(ledger)
                    with self.assertRaisesRegex(
                            ReconcileHold, "HOLD_USER_ID_REQUEST_BINDING_INCOMPLETE"):
                        reconcile(ledger, approved)
                    self.assertEqual(ledger, original)

    def test_duplicate_user_identity_request_holds(self):
        ledger, approved = fixture()
        ledger["user_id_requests"]["items"].append(
            copy.deepcopy(ledger["user_id_requests"]["items"][0]))
        with self.assertRaisesRegex(ReconcileHold, "HOLD_USER_ID_REQUEST_DUPLICATE"):
            reconcile(ledger, approved)

    def test_registration_router_wrong_repository_holds(self):
        ledger, approved = fixture()
        ledger["registration_router"]["entries"][0]["repository"] = (
            "shihuiarenjinba-png/Other-Factory")
        with self.assertRaisesRegex(
                ReconcileHold, "HOLD_REGISTRATION_ROUTER_SOURCE_CONFLICT"):
            reconcile(ledger, approved)

    def test_registration_router_wrong_type_holds(self):
        ledger, approved = fixture()
        ledger["rotation_cohorts"]["app_jobs"][0]["registration_type"] = (
            "MSIX_OR_PWA_APP")
        ledger["registration_router"]["entries"][0]["registration_type"] = (
            "GDK_GAME")
        with self.assertRaisesRegex(
                ReconcileHold, "HOLD_REGISTRATION_ROUTER_SOURCE_CONFLICT"):
            reconcile(ledger, approved)

    def test_duplicate_registration_router_entry_holds(self):
        ledger, approved = fixture()
        ledger["registration_router"]["entries"].append(
            copy.deepcopy(ledger["registration_router"]["entries"][0]))
        with self.assertRaisesRegex(ReconcileHold, "HOLD_REGISTRATION_ROUTER_DUPLICATE"):
            reconcile(ledger, approved)

    def test_idempotent_replay_requires_same_return_head(self):
        ledger, approved = fixture()
        once, _ = reconcile(ledger, approved)
        twice, status = reconcile(once, approved)
        self.assertEqual(status, "EXISTING_VERIFIED")
        self.assertEqual(once, twice)
        with self.assertRaisesRegex(ReconcileHold, "HOLD_RETURN_COMMIT_DRIFT"):
            reconcile(once, approved, head="d" * 40)

    def test_post_replay_rejects_changed_store_id(self):
        ledger, approved = fixture()
        once, _ = reconcile(ledger, approved)
        once["rotation_cohorts"]["app_jobs"][0]["identity_store_id"] = "9OTHER123456"
        with self.assertRaisesRegex(ReconcileHold, "HOLD_POST_IDENTITY_BINDING_CONFLICT"):
            reconcile(once, approved)

    def test_post_replay_rejects_missing_pfn(self):
        ledger, approved = fixture()
        once, _ = reconcile(ledger, approved)
        del once["rotation_cohorts"]["app_jobs"][0]["identity_pfn"]
        with self.assertRaisesRegex(ReconcileHold, "HOLD_POST_IDENTITY_BINDING_CONFLICT"):
            reconcile(once, approved)

    def test_pre_with_stale_identity_cannot_be_promoted(self):
        ledger, approved = fixture()
        ledger["rotation_cohorts"]["app_jobs"][0]["identity_pfn"] = (
            "OkinawaDesktopTools.Other_j8yefg9jgfh58")
        with self.assertRaisesRegex(ReconcileHold, "HOLD_PRE_IDENTITY_STALE_BINDING"):
            reconcile(ledger, approved)

    def test_pipeline_receives_verified_store_id_and_pfn(self):
        ledger, approved = fixture()
        result, _ = reconcile(ledger, approved)
        entry = result["post_identity_pipeline"]["products"][0]
        self.assertEqual(entry["identity_store_id"], approved["store_id"])
        self.assertEqual(entry["identity_pfn"], approved["package_family_name"])

    def test_pipeline_rejects_conflicting_identity_without_mutating_input(self):
        ledger, approved = fixture()
        ledger["post_identity_pipeline"]["products"][0]["identity_pfn"] = (
            "OkinawaDesktopTools.Other_j8yefg9jgfh58")
        original = copy.deepcopy(ledger)
        with self.assertRaisesRegex(ReconcileHold, "HOLD_POST_IDENTITY_PIPELINE_CONFLICT"):
            reconcile(ledger, approved)
        self.assertEqual(ledger, original)

    def test_pipeline_rejects_duplicate_request(self):
        ledger, approved = fixture()
        ledger["post_identity_pipeline"]["products"].append(
            copy.deepcopy(ledger["post_identity_pipeline"]["products"][0]))
        with self.assertRaisesRegex(ReconcileHold, "HOLD_POST_IDENTITY_PIPELINE_DUPLICATE"):
            reconcile(ledger, approved)

    def test_pipeline_missing_record_holds(self):
        ledger, approved = fixture()
        ledger["post_identity_pipeline"]["products"] = []
        with self.assertRaisesRegex(ReconcileHold, "HOLD_POST_IDENTITY_PIPELINE_MISSING"):
            reconcile(ledger, approved)

    def test_pipeline_missing_collection_holds(self):
        ledger, approved = fixture()
        ledger.pop("post_identity_pipeline")
        with self.assertRaisesRegex(ReconcileHold, "HOLD_POST_IDENTITY_PIPELINE_MISSING"):
            reconcile(ledger, approved)

    def test_pipeline_cross_product_source_and_lane_holds(self):
        for field, wrong in (
            ("product", "Other App"),
            ("lane", "GAME"),
            ("source_repository", "shihuiarenjinba-png/AI-Game-Factory"),
            ("source_branch", "codex/other"),
            ("source_sha", "f" * 40),
            ("identity_return_target", "products/other/store/approved-identity.json"),
        ):
            with self.subTest(field=field):
                ledger, approved = fixture()
                ledger["post_identity_pipeline"]["products"][0][field] = wrong
                with self.assertRaisesRegex(
                        ReconcileHold, "HOLD_POST_IDENTITY_PIPELINE_SOURCE_CONFLICT"):
                    reconcile(ledger, approved)

    def test_pipeline_wrong_state_and_stale_pre_identity_hold(self):
        ledger, approved = fixture()
        ledger["post_identity_pipeline"]["products"][0]["state"] = "POST_IDENTITY_READY"
        with self.assertRaisesRegex(ReconcileHold, "HOLD_POST_IDENTITY_PIPELINE_STATE_CONFLICT"):
            reconcile(ledger, approved)
        ledger, approved = fixture()
        ledger["post_identity_pipeline"]["products"][0]["identity_store_id"] = approved["store_id"]
        with self.assertRaisesRegex(ReconcileHold, "HOLD_POST_IDENTITY_PIPELINE_CONFLICT"):
            reconcile(ledger, approved)

    def test_pipeline_post_replay_requires_existing_store_id_and_pfn(self):
        ledger, approved = fixture()
        once, _ = reconcile(ledger, approved)
        for field in ("identity_store_id", "identity_pfn"):
            changed = copy.deepcopy(once)
            del changed["post_identity_pipeline"]["products"][0][field]
            with self.subTest(field=field), self.assertRaisesRegex(
                    ReconcileHold, "HOLD_POST_IDENTITY_PIPELINE_CONFLICT"):
                reconcile(changed, approved)

    def test_source_binding_conflict(self):
        ledger, approved = fixture()
        approved["request_id"] = "other-request"
        with self.assertRaisesRegex(ReconcileHold, "HOLD_APPROVED_IDENTITY_SOURCE_CONFLICT"):
            reconcile(ledger, approved)

    def test_store_reserved_name_must_match_queue_product(self):
        ledger, approved = fixture()
        approved["reserved_display_name"] = "Different App"
        with self.assertRaisesRegex(ReconcileHold, "HOLD_APPROVED_IDENTITY_PRODUCT_CONFLICT"):
            reconcile(ledger, approved)

    def test_store_reserved_name_missing_is_not_sufficient(self):
        ledger, approved = fixture()
        del approved["reserved_display_name"]
        with self.assertRaisesRegex(ReconcileHold, "HOLD_APPROVED_IDENTITY_SCHEMA"):
            reconcile(ledger, approved)

    def test_optional_display_name_mismatch_is_rejected(self):
        ledger, approved = fixture()
        approved["display_name"] = "Different App"
        with self.assertRaisesRegex(ReconcileHold, "HOLD_APPROVED_IDENTITY_PRODUCT_CONFLICT"):
            reconcile(ledger, approved)

    def test_pfn_prefix_must_equal_identity_name(self):
        ledger, approved = fixture()
        approved["name"] = "OkinawaDesktopTools.DifferentApp"
        with self.assertRaisesRegex(ReconcileHold, "HOLD_APPROVED_IDENTITY_PRODUCT_CONFLICT"):
            reconcile(ledger, approved)

    def test_publisher_display_name_required(self):
        ledger, approved = fixture()
        approved.pop("publisher_display_name")
        with self.assertRaisesRegex(ReconcileHold, "HOLD_APPROVED_IDENTITY_SCHEMA"):
            reconcile(ledger, approved)

    def test_exe_hash_conflict(self):
        ledger, approved = fixture()
        approved["package_sha256"] = "d" * 64
        with self.assertRaisesRegex(ReconcileHold, "HOLD_PREIDENTITY_ARTIFACT_CONFLICT"):
            reconcile(ledger, approved)

    def test_return_not_observed(self):
        ledger, approved = fixture()
        with self.assertRaisesRegex(ReconcileHold, "HOLD_RETURN_COMMIT_NOT_OBSERVED"):
            reconcile(ledger, approved, head=SOURCE)

    def test_version_not_approved_is_not_inferred(self):
        ledger, approved = fixture()
        approved["package_version_gate"] = "PASS"
        with self.assertRaisesRegex(ReconcileHold, "HOLD_IDENTITY_OR_VERSION_GATE"):
            reconcile(ledger, approved)

    def test_duplicate_json_key_rejected(self):
        ledger, approved = fixture()
        raw = json.dumps(approved).replace('"reviewed": true',
                                           '"reviewed": true, "reviewed": true')
        with self.assertRaisesRegex(ReconcileHold, "HOLD_APPROVED_IDENTITY_DUPLICATE_KEY"):
            reconcile(ledger, raw)

    def test_cross_product_duplicate_request_rejected(self):
        ledger, approved = fixture()
        other = copy.deepcopy(ledger["rotation_cohorts"]["app_jobs"][0])
        other["slug"] = "another"
        ledger["rotation_cohorts"]["app_jobs"].append(other)
        with self.assertRaisesRegex(ReconcileHold, "HOLD_CROSS_PRODUCT_IDENTITY"):
            reconcile(ledger, approved)

    def test_cross_product_duplicate_store_id_rejected(self):
        ledger, approved = fixture()
        other = copy.deepcopy(ledger["rotation_cohorts"]["app_jobs"][0])
        other.update({"slug": "another", "request_id": "another-request",
                      "identity_return_target": "products/another/store/approved-identity.json",
                      "identity_store_id": approved["store_id"]})
        ledger["rotation_cohorts"]["app_jobs"].append(other)
        with self.assertRaisesRegex(ReconcileHold, "HOLD_CROSS_PRODUCT_IDENTITY"):
            reconcile(ledger, approved)

    def test_independent_verifier_receives_exact_return_target(self):
        ledger, approved = fixture()
        observed = []
        result, status = reconcile_approved_return(
            ledger, "test-app",
            fetch_branch_head=lambda *_: RETURN,
            fetch_approved_file=lambda *_: json.dumps(approved),
            verify_source_ancestry=lambda repo, source, head, target: (
                observed.append((repo, source, head, target)) or True),
        )
        self.assertEqual(status, "POST_IDENTITY_READY")
        self.assertEqual(observed, [(
            REPO, SOURCE, RETURN, "products/test-app/store/approved-identity.json")])

    def test_unrelated_return_head_is_rejected(self):
        ledger, approved = fixture()
        with self.assertRaisesRegex(ReconcileHold, "HOLD_SOURCE_ANCESTRY_CONFLICT"):
            reconcile(ledger, approved, ancestry=False)

    def test_missing_independent_ancestry_reader_is_rejected(self):
        ledger, approved = fixture()
        with self.assertRaisesRegex(ReconcileHold, "HOLD_SOURCE_ANCESTRY_VERIFIER_MISSING"):
            reconcile_approved_return(
                ledger, "test-app",
                fetch_branch_head=lambda *_: RETURN,
                fetch_approved_file=lambda *_: json.dumps(approved),
            )

    def test_no_file_no_promotion(self):
        ledger, approved = fixture()
        with self.assertRaisesRegex(ReconcileHold, "HOLD_APPROVED_IDENTITY_FILE_INVALID"):
            reconcile_approved_return(
                ledger, "test-app",
                fetch_branch_head=lambda *_: RETURN,
                fetch_approved_file=lambda *_: None,
                verify_source_ancestry=lambda *_: True,
            )



    def test_registration_lane_conflict_even_when_router_agrees(self):
        ledger, approved = fixture()
        job = ledger["rotation_cohorts"]["app_jobs"][0]
        job["registration_type"] = "GDK_GAME"
        job["partner_center_selection"] = "GDK game"
        router = ledger["registration_router"]["entries"][0]
        router["registration_type"] = "GDK_GAME"
        router["partner_center_selection"] = "GDK game"
        original = copy.deepcopy(ledger)
        with self.assertRaisesRegex(ReconcileHold, "HOLD_REGISTRATION_LANE_CONFLICT"):
            reconcile(ledger, approved)
        self.assertEqual(ledger, original)

    def test_registration_type_missing_or_unknown_holds(self):
        for value in (None, "OTHER", ["GDK_GAME"]):
            with self.subTest(value=value):
                ledger, approved = fixture()
                ledger["rotation_cohorts"]["app_jobs"][0]["registration_type"] = value
                with self.assertRaisesRegex(ReconcileHold, "HOLD_REGISTRATION_LANE_CONFLICT"):
                    reconcile(ledger, approved)

    def test_job_partner_center_selection_must_match_type(self):
        ledger, approved = fixture()
        ledger["rotation_cohorts"]["app_jobs"][0]["partner_center_selection"] = "GDK game"
        with self.assertRaisesRegex(ReconcileHold, "HOLD_REGISTRATION_SELECTION_CONFLICT"):
            reconcile(ledger, approved)

    def test_request_registration_and_selection_must_match(self):
        for field, wrong in (("registration_type", "GDK_GAME"),
                             ("partner_center_selection", "GDK game")):
            with self.subTest(field=field):
                ledger, approved = fixture()
                ledger["user_id_requests"]["items"][0][field] = wrong
                with self.assertRaisesRegex(
                        ReconcileHold, "HOLD_USER_ID_REQUEST_SOURCE_CONFLICT"):
                    reconcile(ledger, approved)

    def test_router_registration_and_selection_required(self):
        for field, wrong in (("registration_type", None),
                             ("partner_center_selection", None),
                             ("partner_center_selection", "GDK game")):
            with self.subTest(field=field, wrong=wrong):
                ledger, approved = fixture()
                entry = ledger["registration_router"]["entries"][0]
                if wrong is None:
                    del entry[field]
                else:
                    entry[field] = wrong
                with self.assertRaisesRegex(
                        ReconcileHold, "HOLD_REGISTRATION_ROUTER_SOURCE_CONFLICT"):
                    reconcile(ledger, approved)

    def test_full_registration_binding_promotes(self):
        ledger, approved = fixture()
        request = ledger["user_id_requests"]["items"][0]
        request["registration_type"] = "MSIX_OR_PWA_APP"
        request["partner_center_selection"] = "MSIX or PWA app"
        result, transition = reconcile(ledger, approved)
        self.assertEqual(transition, "POST_IDENTITY_READY")
        self.assertEqual(result["registration_router"]["entries"][0]
                         ["identity_status"], "GITHUB_APPROVED_IDENTITY_RETURN_VERIFIED")



    def test_missing_matching_user_id_request_holds_without_mutation(self):
        for mode in ("absent_collection", "empty_items", "different_request"):
            with self.subTest(mode=mode):
                ledger, approved = fixture()
                if mode == "absent_collection":
                    del ledger["user_id_requests"]
                elif mode == "empty_items":
                    ledger["user_id_requests"]["items"] = []
                else:
                    ledger["user_id_requests"]["items"][0]["request_id"] = "other-request"
                original = copy.deepcopy(ledger)
                with self.assertRaisesRegex(ReconcileHold, "HOLD_USER_ID_REQUEST_MISSING"):
                    reconcile(ledger, approved)
                self.assertEqual(ledger, original)

    def test_missing_matching_registration_route_holds_without_mutation(self):
        for mode in ("absent_collection", "empty_entries", "different_product"):
            with self.subTest(mode=mode):
                ledger, approved = fixture()
                if mode == "absent_collection":
                    del ledger["registration_router"]
                elif mode == "empty_entries":
                    ledger["registration_router"]["entries"] = []
                else:
                    ledger["registration_router"]["entries"][0]["product"] = "Other App"
                original = copy.deepcopy(ledger)
                with self.assertRaisesRegex(ReconcileHold, "HOLD_REGISTRATION_ROUTER_MISSING"):
                    reconcile(ledger, approved)
                self.assertEqual(ledger, original)

    def test_missing_router_repository_cannot_default_to_job(self):
        ledger, approved = fixture()
        del ledger["registration_router"]["entries"][0]["repository"]
        with self.assertRaisesRegex(ReconcileHold, "HOLD_REGISTRATION_ROUTER_SOURCE_CONFLICT"):
            reconcile(ledger, approved)

class MarketFitPackageGateTests(unittest.TestCase):
    def market_evidence(self):
        ledger, _ = fixture()
        job = ledger["rotation_cohorts"]["app_jobs"][0]
        return {
            "schema_version": 1,
            "slug": job["slug"], "request_id": job["request_id"],
            "source_repository": job["source_repository"],
            "source_branch": job["source_branch"],
            "source_sha": job["source_sha"],
            "reviewed": True, "status": "MARKET_FIT_PASS", "score": 75,
            "why_pay": "Saves repeated manual reconciliation work",
            "free_alternative_difference": "One-click offline batch validation",
            "competitor_research": [{"competitor": "Example Alternative",
                                      "difference": "Requires manual review"}],
        }

    def run_gate(self, evidence, *, raw=None):
        ledger, approved = fixture()
        observed = []
        result, transition = reconcile_approved_return(
            ledger, "test-app",
            fetch_branch_head=lambda *_: RETURN,
            verify_source_ancestry=lambda *_: True,
            fetch_approved_file=lambda *_: json.dumps(approved),
            fetch_market_fit=lambda repo, path, sha: (
                observed.append((repo, path, sha))
                or (raw if raw is not None else json.dumps(evidence))),
        )
        self.assertEqual(transition, "POST_IDENTITY_READY")
        self.assertEqual(observed, [(REPO, "products/test-app/market-fit.json", SOURCE)])
        return result

    def test_no_factory_reader_holds_package_but_not_identity(self):
        ledger, approved = fixture()
        result, status = reconcile(ledger, approved)
        self.assertEqual(status, "POST_IDENTITY_READY")
        job = result["rotation_cohorts"]["app_jobs"][0]
        self.assertEqual(job["market_fit_gate"], "MARKET_FIT_HOLD")
        self.assertEqual(job["next_action"], "MARKET_FIT_HOLD")
        self.assertEqual(job["package_version_gate"], "HOLD")
        self.assertEqual(result["post_identity_pipeline"]["products"][0]["next_action"],
                         "MARKET_FIT_HOLD")

    def test_factory_source_sha_bound_reviewed_evidence_passes_market_gate_only(self):
        result = self.run_gate(self.market_evidence())
        job = result["rotation_cohorts"]["app_jobs"][0]
        self.assertEqual(job["market_fit_gate"], "MARKET_FIT_PASS")
        self.assertEqual(job["package_version_gate"], "HOLD")
        self.assertEqual(job["next_action"], "PACKAGE_VERSION_AND_ASSET_APPROVAL_GATE")
        self.assertEqual(result["post_identity_pipeline"]["products"][0]["market_fit_gate"],
                         "MARKET_FIT_PASS")

    def test_market_fit_evidence_flag_is_synchronized_on_pass_and_replay_hold(self):
        ledger, approved = fixture()
        evidence = self.market_evidence()
        callbacks = {
            "fetch_branch_head": lambda *_: RETURN,
            "verify_source_ancestry": lambda *_: True,
            "fetch_approved_file": lambda *_: json.dumps(approved),
        }
        passed, transition = reconcile_approved_return(
            ledger, "test-app", **callbacks,
            fetch_market_fit=lambda *_: json.dumps(evidence))
        self.assertEqual(transition, "POST_IDENTITY_READY")
        self.assertTrue(passed["rotation_cohorts"]["app_jobs"][0]["market_fit_evidence_verified"])
        self.assertTrue(passed["post_identity_pipeline"]["products"][0]["market_fit_evidence_verified"])

        held, transition = reconcile_approved_return(
            passed, "test-app", **callbacks,
            fetch_market_fit=lambda *_: None)
        self.assertEqual(transition, "EXISTING_VERIFIED")
        for item in (held["rotation_cohorts"]["app_jobs"][0],
                     held["post_identity_pipeline"]["products"][0]):
            self.assertEqual(item["market_fit_gate"], "MARKET_FIT_HOLD")
            self.assertIs(item["market_fit_evidence_verified"], False)
        self.assertEqual(held["rotation_cohorts"]["app_jobs"][0]["package_version_gate"], "HOLD")
        self.assertTrue(passed["rotation_cohorts"]["app_jobs"][0]["market_fit_evidence_verified"])

    def test_stale_market_fit_flag_is_cleared_without_reader(self):
        ledger, approved = fixture()
        ledger["rotation_cohorts"]["app_jobs"][0]["market_fit_evidence_verified"] = True
        ledger["post_identity_pipeline"]["products"][0]["market_fit_evidence_verified"] = True
        result, _ = reconcile(ledger, approved)
        self.assertIs(result["rotation_cohorts"]["app_jobs"][0]["market_fit_evidence_verified"], False)
        self.assertIs(result["post_identity_pipeline"]["products"][0]["market_fit_evidence_verified"], False)

    def test_missing_schema_version_holds(self):
        evidence = self.market_evidence()
        evidence.pop("schema_version")
        self.assertEqual(self.run_gate(evidence)["rotation_cohorts"]["app_jobs"][0]
                         ["market_fit_reason"], "HOLD_MARKET_FIT_SCHEMA")

    def test_score_below_70_holds(self):
        evidence = self.market_evidence()
        evidence["score"] = 69
        self.assertEqual(self.run_gate(evidence)["rotation_cohorts"]["app_jobs"][0]
                         ["market_fit_reason"], "HOLD_MARKET_FIT_SCORE_BELOW_70_OR_INVALID")

    def test_boolean_score_is_not_numeric_approval(self):
        evidence = self.market_evidence()
        evidence["score"] = True
        self.assertEqual(self.run_gate(evidence)["rotation_cohorts"]["app_jobs"][0]
                         ["market_fit_gate"], "MARKET_FIT_HOLD")

    def test_why_pay_missing_holds(self):
        evidence = self.market_evidence()
        evidence["why_pay"] = " "
        self.assertEqual(self.run_gate(evidence)["rotation_cohorts"]["app_jobs"][0]
                         ["market_fit_reason"], "HOLD_MARKET_FIT_WHY_PAY_UNCLEAR")

    def test_no_free_alternative_difference_holds(self):
        evidence = self.market_evidence()
        evidence["free_alternative_difference"] = ""
        self.assertEqual(self.run_gate(evidence)["rotation_cohorts"]["app_jobs"][0]
                         ["market_fit_reason"],
                         "HOLD_MARKET_FIT_NO_FREE_ALTERNATIVE_DIFFERENCE")

    def test_competitor_research_missing_holds(self):
        evidence = self.market_evidence()
        evidence["competitor_research"] = []
        self.assertEqual(self.run_gate(evidence)["rotation_cohorts"]["app_jobs"][0]
                         ["market_fit_reason"], "HOLD_MARKET_FIT_COMPETITOR_RESEARCH_MISSING")

    def test_unreviewed_claim_cannot_pass(self):
        evidence = self.market_evidence()
        evidence["reviewed"] = False
        self.assertEqual(self.run_gate(evidence)["rotation_cohorts"]["app_jobs"][0]
                         ["market_fit_gate"], "MARKET_FIT_HOLD")

    def test_cross_product_source_binding_holds(self):
        evidence = self.market_evidence()
        evidence["request_id"] = "different-product"
        self.assertEqual(self.run_gate(evidence)["rotation_cohorts"]["app_jobs"][0]
                         ["market_fit_reason"], "HOLD_MARKET_FIT_SOURCE_CONFLICT")

    def test_duplicate_key_in_factory_evidence_holds(self):
        evidence = self.market_evidence()
        raw = json.dumps(evidence).replace('"score": 75', '"score": 75, "score": 95')
        self.assertEqual(self.run_gate(evidence, raw=raw)["rotation_cohorts"]["app_jobs"][0]
                         ["market_fit_reason"], "HOLD_MARKET_FIT_DUPLICATE_KEY")

    def test_missing_factory_file_holds(self):
        from scripts.market_fit_gate import assess_market_fit
        job = fixture()[0]["rotation_cohorts"]["app_jobs"][0]
        self.assertEqual(assess_market_fit(job, lambda *_: None),
                         ("MARKET_FIT_HOLD", "HOLD_MARKET_FIT_FACTORY_EVIDENCE_MISSING"))

    def test_market_fit_replay_is_idempotent(self):
        ledger, approved = fixture()
        evidence = self.market_evidence()
        readers = {
            "fetch_branch_head": lambda *_: RETURN,
            "verify_source_ancestry": lambda *_: True,
            "fetch_approved_file": lambda *_: json.dumps(approved),
            "fetch_market_fit": lambda *_: json.dumps(evidence),
        }
        once, _ = reconcile_approved_return(ledger, "test-app", **readers)
        twice, status = reconcile_approved_return(once, "test-app", **readers)
        self.assertEqual(status, "EXISTING_VERIFIED")
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
