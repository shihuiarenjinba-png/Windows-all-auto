from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from all_auto.product_qa_plan_intake import (
    GitHubProductQAPlanner, ProductQAPlanIntakeError, canonical,
    job_from_handoff, load_handoff_bundle,
)


def plan():
    return {
        "schema_version":"windows-product-qa-plan-v1",
        "product":{"slug":"demo-product","kind":"app"},
        "intent":"Final pre-sale local Windows QA for the exact generated product.",
        "steps":[
            {
                "step_id":"artifact_hash","test_id":"ARTIFACT_HASH","required":True,
                "requires":[],"purpose":"Verify exact artifact bytes.",
                "parameters":{},"evidence":["artifact_sha256"],"on_fail":"STOP_AND_RETURN"
            },
            {
                "step_id":"process_start","test_id":"PROCESS_START","required":True,
                "requires":["artifact_hash"],"purpose":"Launch exact product.",
                "parameters":{},"evidence":["exit_code"],
                "on_fail":"STOP_AND_RETURN"
            },
            {
                "step_id":"settings_visible","test_id":"UIA_FIND_CONTROL","required":True,
                "requires":["process_start"],"purpose":"Find the Settings control.",
                "parameters":{"target_name":"Settings","locale":"en-US"},
                "evidence":["uia_control"],"on_fail":"STOP_AND_RETURN"
            }
        ],
        "allowed_diagnostics":["EVENT_LOG_QUERY","PROCESS_STATUS","WINDOW_ENUMERATION"],
        "success_criteria":["All required steps pass and Evidence is returned."]
    }


class ProductQAPlanIntakeTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.bundle=Path(t.name)
        self.executable=b"example executable bytes"
        package_path=self.bundle/"package.msix"
        manifest=(
            '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
            '<Identity Name="Demo" Publisher="CN=TEST" Version="1.0.0.0"/>'
            '<Applications><Application Id="App" Executable="demo.exe"/></Applications>'
            '</Package>'
        )
        with zipfile.ZipFile(package_path,"w") as archive:
            archive.writestr("AppxManifest.xml",manifest)
            archive.writestr("AppxBlockMap.xml","<BlockMap/>")
            archive.writestr("[Content_Types].xml","<Types/>")
            archive.writestr("demo.exe",self.executable)
        self.package=package_path.read_bytes()
        self.plan=plan()
        (self.bundle/"qa-plan.json").write_text(json.dumps(self.plan),encoding="utf-8")
        self.handoff={
            "schema_version":1,
            "source_repository":"https://github.com/shihuiarenjinba-png/AI-App-Factory",
            "source_sha":"a"*40,
            "source_branch":"codex/factory-qa-plan-test",
            "type":"app",
            "slug":"demo-product",
            "package":"package.msix",
            "status":"QA_UNSIGNED",
            "package_sha256":sha256(self.package).hexdigest(),
            "package_bytes":len(self.package),
            "executable_sha256":sha256(self.executable).hexdigest(),
            "executable_path":"demo.exe",
            "application_id":"App",
            "identity":{"name":"Demo","publisher":"CN=TEST","version":"1.0.0.0"},
            "qa_plan":"qa-plan.json",
            "qa_plan_schema":"windows-product-qa-plan-v1",
            "qa_plan_sha256":sha256(canonical(self.plan)).hexdigest(),
        }
        self.save_handoff()

    def save_handoff(self):
        (self.bundle/"handoff.json").write_text(
            json.dumps(self.handoff),encoding="utf-8"
        )

    def test_accepts_correlated_factory_bundle(self):
        result=load_handoff_bundle(self.bundle)
        self.assertEqual(result.slug,"demo-product")
        self.assertEqual(result.product_type,"APP")
        self.assertEqual(result.source_branch,"codex/factory-qa-plan-test")
        self.assertEqual(result.plan["steps"][2]["test_id"],"UIA_FIND_CONTROL")

    def test_tampered_plan_hash_holds(self):
        self.plan["steps"][2]["parameters"]["target_name"]="Different"
        (self.bundle/"qa-plan.json").write_text(json.dumps(self.plan),encoding="utf-8")
        with self.assertRaisesRegex(ProductQAPlanIntakeError,"plan hash"):
            load_handoff_bundle(self.bundle)

    def test_package_byte_count_mismatch_holds(self):
        self.handoff["package_bytes"] += 1
        self.save_handoff()
        with self.assertRaisesRegex(ProductQAPlanIntakeError,"byte count"):
            load_handoff_bundle(self.bundle)

    def test_invalid_source_branch_holds(self):
        self.handoff["source_branch"]="../bad"
        self.save_handoff()
        with self.assertRaisesRegex(ProductQAPlanIntakeError,"source branch"):
            load_handoff_bundle(self.bundle)

    def test_tampered_package_holds(self):
        original=(self.bundle/"package.msix").read_bytes()
        self.assertGreater(len(original),0)
        tampered=bytes([original[0] ^ 1]) + original[1:]
        self.assertEqual(len(tampered),len(original))
        (self.bundle/"package.msix").write_bytes(tampered)
        with self.assertRaisesRegex(ProductQAPlanIntakeError,"package hash"):
            load_handoff_bundle(self.bundle)

    def test_raw_command_in_plan_holds(self):
        self.plan["steps"][2]["purpose"]="run powershell -Command whoami"
        (self.bundle/"qa-plan.json").write_text(json.dumps(self.plan),encoding="utf-8")
        self.handoff["qa_plan_sha256"]=sha256(canonical(self.plan)).hexdigest()
        self.save_handoff()
        with self.assertRaisesRegex(ProductQAPlanIntakeError,"command-like"):
            load_handoff_bundle(self.bundle)

    def test_process_start_without_hash_dependency_holds(self):
        self.plan["steps"][1]["requires"]=[]
        (self.bundle/"qa-plan.json").write_text(json.dumps(self.plan),encoding="utf-8")
        self.handoff["qa_plan_sha256"]=sha256(canonical(self.plan)).hexdigest()
        self.save_handoff()
        with self.assertRaisesRegex(ProductQAPlanIntakeError,"PROCESS_START"):
            load_handoff_bundle(self.bundle)

    def test_github_plan_planner_emits_only_trusted_test_id(self):
        accepted=load_handoff_bundle(self.bundle)
        planner=GitHubProductQAPlanner(accepted.plan)
        catalog=[
            {"test_id":"ARTIFACT_HASH"},
            {"test_id":"PROCESS_START"},
        ]
        first=planner.plan(
            context={"product_type":"APP"},catalog=catalog,evidence="",
            round_number=1,execution_history=[],
        )
        self.assertEqual(first.status,"QA_PLAN_VALID")
        self.assertEqual(first.plan["selected_test_ids"],["ARTIFACT_HASH"])
        second=planner.plan(
            context={"product_type":"APP"},catalog=catalog,evidence="",
            round_number=2,execution_history=[{
                "test_id":"ARTIFACT_HASH","status":"TEST_PASS",
                "exit_code":0,"timed_out":False,
            }],
        )
        self.assertEqual(second.status,"QA_PLAN_VALID")
        self.assertEqual(second.plan["selected_test_ids"],["PROCESS_START"])

    def test_unsupported_required_product_check_holds(self):
        self.plan["steps"][2]["required"]=True
        (self.bundle/"qa-plan.json").write_text(json.dumps(self.plan),encoding="utf-8")
        self.handoff["qa_plan_sha256"]=sha256(canonical(self.plan)).hexdigest()
        self.save_handoff()
        accepted=load_handoff_bundle(self.bundle)
        planner=GitHubProductQAPlanner(accepted.plan)
        history=[
            {"test_id":"ARTIFACT_HASH","status":"TEST_PASS","exit_code":0,"timed_out":False},
            {"test_id":"PROCESS_START","status":"TEST_PASS","exit_code":0,"timed_out":False},
        ]
        outcome=planner.plan(
            context={"product_type":"APP"},
            catalog=[{"test_id":"ARTIFACT_HASH"},{"test_id":"PROCESS_START"}],
            evidence="",round_number=3,execution_history=history,
        )
        self.assertEqual(outcome.status,"QA_PLAN_CAPABILITY_HOLD")
        self.assertIn("UIA_FIND_CONTROL",outcome.errors[0])

    def test_job_is_bound_to_factory_revision(self):
        accepted=load_handoff_bundle(self.bundle)
        job=job_from_handoff(accepted,request_id="final-sale-qa-0001")
        self.assertEqual(job["source_sha"],"a"*40)
        self.assertEqual(job["source_branch"],"codex/factory-qa-plan-test")
        self.assertEqual(
            job["artifact_sha256"],sha256(self.executable).hexdigest()
        )
        self.assertEqual(job["factory_package_sha256"],self.handoff["package_sha256"])
        self.assertEqual(job["factory_qa_plan_sha256"],self.handoff["qa_plan_sha256"])

    def test_source_sha_is_not_inferred(self):
        self.handoff["source_sha"]="UNKNOWN"
        self.save_handoff()
        with self.assertRaisesRegex(ProductQAPlanIntakeError,"source SHA"):
            load_handoff_bundle(self.bundle)


if __name__=="__main__":
    unittest.main()
