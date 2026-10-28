"""Offline APP cohort and real Prism 3D queue isolation regression tests."""
import copy
import tempfile
import unittest
from pathlib import Path

from scripts import rotation_pre_identity_intake as intake

PIN = "15fdcb52e46e35e6de8e87c55af99719c21e09b9"
EXE = "66b26ad96df7458ea917b632a73ac7c88bb058db24dbd11a457fd50435ab7b13"


def make_job(lane, i=0):
    is_3d = lane == "GAME_3D"
    slug = "prism-route-3d" if is_3d else "app-cohort-" + str(i)
    sha = PIN if is_3d else f"{i + 1:040x}"
    repo = ("shihuiarenjinba-png/3d-game-factory" if is_3d
            else "shihuiarenjinba-png/AI-App-Factory")
    rid = ("3d-prism-route-3d-15fdcb52e46e" if is_3d
           else "app-cohort-" + str(i) + "-" + sha[:12])
    reg = "MSIX_OR_PWA_GAME" if is_3d else "MSIX_OR_PWA_APP"
    job = {
        "product_type": lane, "status": "PRE_IDENTITY_READY",
        "request_id": rid, "slug": slug, "source_repository": repo,
        "source_branch": "codex/3d-canary-prism-route-20261028" if is_3d
                         else "codex/app-cohort-" + str(i),
        "source_sha": sha, "factory_build_head": sha,
        "expected_exe_sha256": EXE,
        "registration_type": reg, "partner_center_selection": intake.REGISTRATIONS[reg],
        "packaging_strategy": "GODOT_WINDOWS_EXE_PCK_MAKEAPPX_MSIX" if is_3d else "APP_MSIX",
        "packaging_family": "MSIX",
    }
    request = {
        "request_id": rid, "slug": slug, "repo": repo,
        "source_branch": job["source_branch"], "source_sha": sha,
        "registration_type": reg, "partner_center_selection": job["partner_center_selection"],
        "identity_target": intake.IDENTITY_TARGET,
        "identity_return_target": f"products/{slug}/store/approved-identity.json",
        "status": "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE" if is_3d
                  else "WAITING_USER_IDENTITY",
        "allow_local_product_creation": False,
    }
    return job, request


def ledger(apps=0, include_3d=True):
    jobs, requests = [], []
    for i in range(apps):
        j, r = make_job("APP", i)
        jobs.append(j)
        requests.append(r)
    three_d = []
    if include_3d:
        j, r = make_job("GAME_3D")
        j["observed_pr_head"] = "11417b75636ee18816028ffd5221884c4c9a9836"
        three_d.append(j)
        requests.append(r)
    return {"e2e_pass": False, "new_product_allowed": False,
            "rotation_cohorts": {"app_jobs": jobs, "three_d_jobs": three_d},
            "user_id_requests": {"items": requests}}


class RotationIntakeTests(unittest.TestCase):
    def test_real_prism_queue_preserves_pin_and_drift_hold(self):
        output = intake.project(ledger())
        self.assertEqual(output["metrics"]["3d_total_jobs"], 1)
        self.assertEqual(output["metrics"]["3d_pre_identity_pass"], 1)
        job = output["jobs"][0]
        self.assertEqual(job["source_sha"], PIN)
        self.assertEqual(job["source_head_status"], "HOLD_SOURCE_BRANCH_HEAD_DRIFT")
        self.assertEqual(job["identity_status"], "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE")
        self.assertEqual(job["identity_return_target"],
                         "products/prism-route-3d/store/approved-identity.json")
        self.assertEqual(len(job["rotation_intake_digest"]), 64)
        self.assertNotIn("queue_job_digest", job)
        for key in ("remote_head_verified", "identity_validated", "cas_return_pass",
                    "real_msix_pass", "e2e_pass"):
            self.assertFalse(job[key])

    def test_five_apps_plus_3d_do_not_cross_bind(self):
        result = intake.project(ledger(apps=5))
        self.assertEqual(len(result["jobs"]), 6)
        self.assertEqual(result["metrics"]["app_total_jobs"], 5)
        self.assertEqual(result["metrics"]["app_waiting_user_identity"], 5)
        self.assertEqual(result["metrics"]["3d_total_jobs"], 1)
        self.assertEqual(len({x["request_id"] for x in result["jobs"]}), 6)
        self.assertEqual(len({x["rotation_intake_digest"] for x in result["jobs"]}), 6)

    def test_sixth_app_rejected(self):
        with self.assertRaisesRegex(intake.IntakeHold, "CAPACITY"):
            intake.project(ledger(apps=6))

    def test_duplicate_request_across_lanes_rejected(self):
        data = ledger(apps=1)
        data["rotation_cohorts"]["app_jobs"][0]["request_id"] = data["rotation_cohorts"]["three_d_jobs"][0]["request_id"]
        with self.assertRaisesRegex(intake.IntakeHold, "DUPLICATE_REQUEST"):
            intake.project(data)

    def test_cross_product_request_target_rejected(self):
        data = ledger()
        data["user_id_requests"]["items"][0]["identity_return_target"] = "products/other/store/approved-identity.json"
        with self.assertRaisesRegex(intake.IntakeHold, "IDENTITY_RETURN_TARGET"):
            intake.project(data)

    def test_request_sha_mismatch_rejected(self):
        data = ledger()
        data["user_id_requests"]["items"][0]["source_sha"] = "f" * 40
        with self.assertRaisesRegex(intake.IntakeHold, "CROSS_PRODUCT"):
            intake.project(data)

    def test_registration_family_and_packaging_enforced(self):
        data = ledger()
        data["rotation_cohorts"]["three_d_jobs"][0]["registration_type"] = "GDK_GAME"
        data["rotation_cohorts"]["three_d_jobs"][0]["partner_center_selection"] = "GDK game"
        data["user_id_requests"]["items"][0]["registration_type"] = "GDK_GAME"
        data["user_id_requests"]["items"][0]["partner_center_selection"] = "GDK game"
        with self.assertRaisesRegex(intake.IntakeHold, "GDK_PACKAGING_EVIDENCE"):
            intake.project(data)

    def test_exe_hash_required(self):
        data = ledger()
        data["rotation_cohorts"]["three_d_jobs"][0]["expected_exe_sha256"] = "not-sha"
        with self.assertRaisesRegex(intake.IntakeHold, "EXPECTED_EXE_SHA"):
            intake.project(data)

    def test_existing_product_creation_must_be_disabled(self):
        data = ledger()
        data["user_id_requests"]["items"][0]["allow_local_product_creation"] = True
        with self.assertRaisesRegex(intake.IntakeHold, "OPERATOR_CREATION_POLICY"):
            intake.project(data)

    def test_focus_app_operator_is_independent_of_drifted_prism(self):
        data = ledger(apps=1)
        app_request = data["user_id_requests"]["items"][0]
        app_request["status"] = "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE"
        app_request["allow_local_product_creation"] = True
        output = intake.project(data)
        app = next(x for x in output["jobs"] if x["lane"] == "APP")
        prism = next(x for x in output["jobs"] if x["lane"] == "GAME_3D")
        self.assertEqual(app["source_head_status"], "REMOTE_HEAD_RECHECK_REQUIRED")
        self.assertEqual(app["identity_status"], "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE")
        self.assertEqual(prism["source_head_status"], "HOLD_SOURCE_BRANCH_HEAD_DRIFT")
        self.assertEqual(output["metrics"]["app_waiting_user_identity"], 1)
        self.assertFalse(app["identity_validated"])
        self.assertFalse(app["cas_return_pass"])

    def test_app_operator_requires_explicit_creation_policy(self):
        data = ledger(apps=1, include_3d=False)
        req = data["user_id_requests"]["items"][0]
        req["status"] = "LOCAL_PARTNER_CENTER_OPERATOR_ACTIVE"
        req.pop("allow_local_product_creation")
        with self.assertRaisesRegex(intake.IntakeHold, "OPERATOR_CREATION_POLICY_MISSING"):
            intake.project(data)
        req["allow_local_product_creation"] = "true"
        with self.assertRaisesRegex(intake.IntakeHold, "OPERATOR_CREATION_POLICY_MISSING"):
            intake.project(data)

    def test_identity_received_is_not_validated(self):
        data = ledger(apps=1, include_3d=False)
        data["user_id_requests"]["items"][0]["status"] = "USER_IDENTITY_RECEIVED"
        result = intake.project(data)
        self.assertEqual(result["metrics"]["app_identity_received"], 1)
        self.assertFalse(result["jobs"][0]["identity_validated"])
        self.assertFalse(result["jobs"][0]["cas_return_pass"])

    def test_unsafe_branch_and_unknown_registration_rejected(self):
        data = ledger()
        data["rotation_cohorts"]["three_d_jobs"][0]["source_branch"] = "main"
        with self.assertRaisesRegex(intake.IntakeHold, "SOURCE_REPOSITORY_OR_BRANCH"):
            intake.project(data)
        data = ledger()
        data["rotation_cohorts"]["three_d_jobs"][0]["registration_type"] = "UNRESOLVED"
        with self.assertRaisesRegex(intake.IntakeHold, "REGISTRATION_SELECTION"):
            intake.project(data)

    def test_duplicate_json_keys_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.json"
            path.write_text('{"e2e_pass":false,"e2e_pass":true}', encoding="utf-8")
            with self.assertRaisesRegex(intake.IntakeHold, "DUPLICATE_JSON_KEY"):
                intake.read_ledger(path)

    def test_no_e2e_promotion(self):
        data = ledger()
        data["e2e_pass"] = True
        with self.assertRaisesRegex(intake.IntakeHold, "CENTRAL_LEDGER_SAFETY_GATE"):
            intake.project(data)


if __name__ == "__main__":
    unittest.main()
