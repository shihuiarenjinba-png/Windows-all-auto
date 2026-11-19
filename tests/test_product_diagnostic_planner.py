from __future__ import annotations

import json
import unittest

from qa_ai.product_diagnostic_planner import (
    ProductDiagnosticPlanner, validate_decision,
)


class FakeClient:
    def __init__(self, value):
        self.value = value
        self.prompts = []

    def generate(self, *, model, prompt):
        self.prompts.append((model, prompt))
        return json.dumps(self.value), {"eval_count": 1}


def valid(step_ids):
    return {
        "schema_version": "windows-product-diagnostic-decision-v1",
        "selected_optional_step_ids": step_ids,
        "reason": "Collect bounded read-only evidence.",
        "stop_reason": None,
        "recommended_owner": "APP",
    }


class ProductDiagnosticPlannerTests(unittest.TestCase):
    def test_selects_only_pre_authored_optional_steps(self):
        client = FakeClient(valid(["inspect-search"]))
        planner = ProductDiagnosticPlanner(client=client, model="test-model")
        outcome = planner.decide(
            product_type="APP",
            failed_step={"step_id": "required-search", "action": "UIA_READ_TEXT"},
            execution_history=[],
            available_optional_steps=[{
                "step_id": "inspect-search",
                "action": "UIA_FIND_CONTROL",
                "params": {"name": "Search", "control_type": "Edit"},
                "requires": ["start"],
            }],
        )
        self.assertEqual(outcome.status, "AI_DIAGNOSTIC_VALID")
        self.assertEqual(
            outcome.decision["selected_optional_step_ids"], ["inspect-search"],
        )
        self.assertFalse(outcome.as_dict()["command_execution_authority"])
        self.assertIn("UIA_FIND_CONTROL", client.prompts[0][1])

    def test_hallucinated_step_is_rejected(self):
        errors = validate_decision(
            valid(["invented-step"]),
            allowed_step_ids={"inspect-search"},
            product_type="APP",
        )
        self.assertTrue(any("unknown diagnostic" in item for item in errors))

    def test_cross_lane_owner_is_rejected(self):
        value = valid([])
        value["recommended_owner"] = "GAME"
        errors = validate_decision(
            value, allowed_step_ids=set(), product_type="APP",
        )
        self.assertTrue(any("crosses product lane" in item for item in errors))

    def test_extra_command_field_is_rejected(self):
        value = valid([])
        value["command"] = "powershell.exe"
        errors = validate_decision(
            value, allowed_step_ids=set(), product_type="APP",
        )
        self.assertTrue(any("fields" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
