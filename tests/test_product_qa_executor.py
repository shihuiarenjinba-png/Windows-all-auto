from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from all_auto.product_qa_executor import (
    ProductQAExecutionHold, execute_bound_product_plan,
)
from all_auto.trusted_uia import TrustedUIAHold


class FakeProcess:
    def __init__(self, *, exit_code=None):
        self.pid = 4321
        self.exit_code = exit_code
        self.terminated = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        self.exit_code = 0

    def wait(self, timeout=None):
        return self.exit_code

    def kill(self):
        self.exit_code = -9


class FakeUIA:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise TrustedUIAHold("ambiguous")
        return {
            "status": "UIA_PASS", "action": kwargs["action"],
            "process_id": kwargs["process_id"], "observed": "ok",
        }


class ProductQAExecutorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.artifact = self.root / "product.exe"
        self.artifact.write_bytes(b"exact")
        self.digest = sha256(self.artifact.read_bytes()).hexdigest()
        self.log = self.root / "actions.jsonl"
        self.plan = {
            "executable_sha256": self.digest,
            "steps": [
                {"step_id": "hash", "action": "ARTIFACT_HASH", "requires": [],
                 "required": True, "params": {}},
                {"step_id": "start", "action": "PROCESS_START", "requires": ["hash"],
                 "required": True, "params": {"observation_seconds": 5}},
                {"step_id": "window", "action": "UIA_FIND_WINDOW",
                 "requires": ["hash", "start"], "required": True,
                 "params": {"title_contains": "Folio AI"}},
                {"step_id": "set", "action": "UIA_SET_TEXT",
                 "requires": ["hash", "start", "window"], "required": True,
                 "params": {"name": "Search", "control_type": "Edit", "value": "token"}},
            ],
        }

    def test_executes_bound_steps_and_stops_process(self):
        process = FakeProcess()
        uia = FakeUIA()
        result = execute_bound_product_plan(
            self.plan, artifact_path=self.artifact, action_log=self.log,
            process_factory=lambda *_args, **_kwargs: process,
            uia_executor=uia, sleeper=lambda _seconds: None,
        )
        self.assertEqual(result.status, "TEST_PASS")
        self.assertEqual([item["action"] for item in result.actions], [
            "ARTIFACT_HASH", "PROCESS_START", "UIA_FIND_WINDOW", "UIA_SET_TEXT",
        ])
        self.assertEqual([item["action"] for item in uia.calls], [
            "UIA_FIND_WINDOW", "UIA_SET_TEXT",
        ])
        self.assertTrue(process.terminated)
        self.assertEqual(len(self.log.read_text(encoding="utf-8").splitlines()), 4)

    def test_dependency_artifact_and_ambiguous_uia_fail_closed(self):
        changed = dict(self.plan)
        changed["executable_sha256"] = "0" * 64
        with self.assertRaisesRegex(ProductQAExecutionHold, "artifact mismatch"):
            execute_bound_product_plan(
                changed, artifact_path=self.artifact, action_log=self.log,
                sleeper=lambda _seconds: None,
            )
        with self.assertRaisesRegex(ProductQAExecutionHold, "trusted UIA"):
            execute_bound_product_plan(
                self.plan, artifact_path=self.artifact, action_log=self.log,
                process_factory=lambda *_args, **_kwargs: FakeProcess(),
                uia_executor=FakeUIA(fail=True), sleeper=lambda _seconds: None,
            )

    def test_early_process_exit_holds(self):
        with self.assertRaisesRegex(ProductQAExecutionHold, "exited"):
            execute_bound_product_plan(
                self.plan, artifact_path=self.artifact, action_log=self.log,
                process_factory=lambda *_args, **_kwargs: FakeProcess(exit_code=17),
                uia_executor=FakeUIA(), sleeper=lambda _seconds: None,
            )


if __name__ == "__main__":
    unittest.main()
