"""Factory-to-local structured product QA plan contract tests."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from all_auto.product_qa_plan import (
    BoundProductPlanPlanner, ProductQAPlanHold, canonical, load_bound_plan,
    verify_plan_for_job,
)


SOURCE = "a" * 40
PACKAGE = "b" * 64


def template(executable_sha: str):
    return {
        "schema_version": "windows-product-qa-plan-template-v1",
        "product_slug": "demo-product",
        "product_type": "APP",
        "plan_version": 1,
        "steps": [
            {
                "step_id": "artifact-hash",
                "action": "ARTIFACT_HASH",
                "requires": [],
                "required": True,
                "params": {},
            },
            {
                "step_id": "process-start",
                "action": "PROCESS_START",
                "requires": ["artifact-hash"],
                "required": True,
                "params": {"observation_seconds": 5},
            },
        ],
        "allowed_diagnostics": ["PROCESS_STATUS", "EVENT_LOG_QUERY"],
        "forbidden_actions": [
            "SOURCE_EDIT",
            "ARBITRARY_SHELL",
            "GIT_WRITE",
            "STORE_SUBMIT",
            "STORE_PUBLISH",
            "SECURITY_POLICY_CHANGE",
        ],
        "success_policy": {
            "required_steps_must_pass": True,
            "evidence_return_required": True,
            "product_e2e_authority": False,
            "release_authority": False,
            "store_authority": False,
        },
    }


def bound_plan(executable_sha: str):
    base = template(executable_sha)
    value = dict(base)
    value["schema_version"] = "windows-product-qa-plan-v1"
    value.update({
        "template_sha256": sha256(canonical(base)).hexdigest(),
        "source_repository": "https://github.com/owner/product",
        "source_sha": SOURCE,
        "package_sha256": PACKAGE,
        "executable_sha256": executable_sha,
        "identity": {
            "name": "OkinawaDesktopTools.Demo",
            "publisher": "CN=TEST",
            "version": "1.0.0.0",
        },
    })
    return value


class ProductQAPlanIntakeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.artifact = self.root / "demo.exe"
        self.artifact.write_bytes(b"exact executable bytes")
        self.exe_sha = sha256(self.artifact.read_bytes()).hexdigest()
        self.path = self.root / "qa-plan.json"
        self.path.write_text(
            json.dumps(bound_plan(self.exe_sha)), encoding="utf-8"
        )
        self.job = {
            "request_id": "product-plan-test",
            "slug": "demo-product",
            "product_type": "APP",
            "source_repository": "owner/product",
            "source_sha": SOURCE,
            "artifact_sha256": self.exe_sha,
            "package_sha256": PACKAGE,
        }

    def test_valid_plan_binds_to_exact_job_and_artifact(self):
        plan = load_bound_plan(self.path)
        result = verify_plan_for_job(
            plan, job=self.job, artifact_path=self.artifact,
            supported_test_ids={"ARTIFACT_HASH", "PROCESS_START"},
        )
        self.assertEqual(result["status"], "PRODUCT_QA_PLAN_READY")
        self.assertEqual(result["unsupported_required_actions"], [])

    def test_source_sha_mismatch_holds(self):
        plan = load_bound_plan(self.path)
        changed = dict(self.job)
        changed["source_sha"] = "c" * 40
        with self.assertRaisesRegex(ProductQAPlanHold, "source SHA"):
            verify_plan_for_job(
                plan, job=changed, artifact_path=self.artifact,
                supported_test_ids={"ARTIFACT_HASH", "PROCESS_START"},
            )

    def test_artifact_replacement_holds(self):
        plan = load_bound_plan(self.path)
        self.artifact.write_bytes(b"tampered executable")
        with self.assertRaisesRegex(ProductQAPlanHold, "executable SHA"):
            verify_plan_for_job(
                plan, job=self.job, artifact_path=self.artifact,
                supported_test_ids={"ARTIFACT_HASH", "PROCESS_START"},
            )

    def test_template_hash_tamper_holds(self):
        value = json.loads(self.path.read_text())
        value["steps"][1]["params"]["observation_seconds"] = 6
        self.path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ProductQAPlanHold, "template hash"):
            load_bound_plan(self.path)

    def test_store_authority_attempt_holds(self):
        value = json.loads(self.path.read_text())
        value["success_policy"]["store_authority"] = True
        base = {
            key: value[key] for key in (
                "product_slug", "product_type", "plan_version", "steps",
                "allowed_diagnostics", "forbidden_actions", "success_policy",
            )
        }
        base["schema_version"] = "windows-product-qa-plan-template-v1"
        value["template_sha256"] = sha256(canonical(base)).hexdigest()
        self.path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ProductQAPlanHold, "authority"):
            load_bound_plan(self.path)

    def test_unsupported_required_action_is_capability_hold(self):
        value = json.loads(self.path.read_text())
        value["steps"].append({
            "step_id": "main-window",
            "action": "UIA_FIND_WINDOW",
            "requires": ["artifact-hash", "process-start"],
            "required": True,
            "params": {"title_contains": "Demo"},
        })
        base = {
            key: value[key] for key in (
                "product_slug", "product_type", "plan_version", "steps",
                "allowed_diagnostics", "forbidden_actions", "success_policy",
            )
        }
        base["schema_version"] = "windows-product-qa-plan-template-v1"
        value["template_sha256"] = sha256(canonical(base)).hexdigest()
        self.path.write_text(json.dumps(value))
        plan = load_bound_plan(self.path)
        result = verify_plan_for_job(
            plan, job=self.job, artifact_path=self.artifact,
            supported_test_ids={"ARTIFACT_HASH", "PROCESS_START"},
        )
        self.assertEqual(result["status"], "PRODUCT_QA_PLAN_CAPABILITY_HOLD")
        self.assertEqual(result["unsupported_required_actions"], ["UIA_FIND_WINDOW"])

    def test_local_process_start_parameter_mismatch_holds(self):
        value = json.loads(self.path.read_text())
        value["steps"][1]["params"]["observation_seconds"] = 10
        base = {
            key: value[key] for key in (
                "product_slug", "product_type", "plan_version", "steps",
                "allowed_diagnostics", "forbidden_actions", "success_policy",
            )
        }
        base["schema_version"] = "windows-product-qa-plan-template-v1"
        value["template_sha256"] = sha256(canonical(base)).hexdigest()
        self.path.write_text(json.dumps(value))
        plan = load_bound_plan(self.path)
        with self.assertRaisesRegex(ProductQAPlanHold, "observation_seconds=5"):
            verify_plan_for_job(
                plan, job=self.job, artifact_path=self.artifact,
                supported_test_ids={"ARTIFACT_HASH", "PROCESS_START"},
            )

    def test_bound_plan_planner_follows_required_sequence(self):
        plan = load_bound_plan(self.path)
        planner = BoundProductPlanPlanner(
            plan, supported_test_ids={"ARTIFACT_HASH", "PROCESS_START"},
        )
        context = {"product_type": "APP"}

        first = planner.plan(
            context=context, catalog=[], evidence="", round_number=1,
            execution_history=[],
        )
        self.assertEqual(first.plan["selected_test_ids"], ["ARTIFACT_HASH"])

        second = planner.plan(
            context=context, catalog=[], evidence="", round_number=2,
            execution_history=[{
                "test_id": "ARTIFACT_HASH", "status": "TEST_PASS",
                "exit_code": 0, "timed_out": False,
            }],
        )
        self.assertEqual(second.plan["selected_test_ids"], ["PROCESS_START"])

        done = planner.plan(
            context=context, catalog=[], evidence="", round_number=3,
            execution_history=[
                {"test_id": "ARTIFACT_HASH", "status": "TEST_PASS",
                 "exit_code": 0, "timed_out": False},
                {"test_id": "PROCESS_START", "status": "TEST_PASS",
                 "exit_code": 0, "timed_out": False},
            ],
        )
        self.assertEqual(done.plan["selected_test_ids"], [])
        self.assertIsNotNone(done.plan["stop_reason"])


if __name__ == "__main__":
    unittest.main()
