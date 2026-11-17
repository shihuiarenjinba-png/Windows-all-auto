from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from all_auto.product_qa_plan_intake import (
    ProductQAPlanIntakeError, canonical, load_handoff_bundle,
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
                "parameters":{"observation_seconds":5},"evidence":["exit_code"],
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
        self.package=b"example msix bytes"
        (self.bundle/"package.msix").write_bytes(self.package)
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
            "executable_sha256":"b"*64,
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

    def test_tampered_package_holds(self):
        (self.bundle/"package.msix").write_bytes(b"changed")
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

    def test_source_sha_is_not_inferred(self):
        self.handoff["source_sha"]="UNKNOWN"
        self.save_handoff()
        with self.assertRaisesRegex(ProductQAPlanIntakeError,"source SHA"):
            load_handoff_bundle(self.bundle)


if __name__=="__main__":
    unittest.main()
