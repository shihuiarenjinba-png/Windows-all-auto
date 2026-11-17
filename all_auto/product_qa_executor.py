"""Deterministic executor for a validated, provenance-bound product QA plan."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Callable

from all_auto.trusted_uia import TrustedUIAExecutor, TrustedUIAHold, UIA_ACTIONS


class ProductQAExecutionHold(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class ProductQAExecutionResult:
    status: str
    actions: tuple[dict[str, Any], ...]


def execute_bound_product_plan(
    plan: dict[str, Any], *, artifact_path: Path, action_log: Path,
    process_factory: Callable[..., Any] = subprocess.Popen,
    uia_executor: TrustedUIAExecutor | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    before_terminate: Callable[[Any, tuple[dict[str, Any], ...]], None] | None = None,
) -> ProductQAExecutionResult:
    """Run bound steps in order without accepting a command from the plan."""
    artifact = artifact_path.resolve()
    if (artifact_path.is_symlink() or not artifact.is_file() or
            _sha256_file(artifact) != plan.get("executable_sha256")):
        raise ProductQAExecutionHold("PRODUCT_QA_EXECUTION_HOLD: artifact mismatch")
    steps = plan.get("steps")
    if not isinstance(steps, list):
        raise ProductQAExecutionHold("PRODUCT_QA_EXECUTION_HOLD: invalid steps")
    uia_executor = uia_executor or TrustedUIAExecutor()
    process = None
    passed_steps: set[str] = set()
    actions: list[dict[str, Any]] = []

    def record(step: dict[str, Any], status: str, **details: Any) -> None:
        item = {
            "step_id": step["step_id"], "action": step["action"],
            "target": json.dumps(step.get("params", {}), ensure_ascii=False,
                                 sort_keys=True),
            "result": status, "details": details,
        }
        actions.append(item)
        action_log.parent.mkdir(parents=True, exist_ok=True)
        with action_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    try:
        for step in steps:
            if any(required not in passed_steps for required in step["requires"]):
                raise ProductQAExecutionHold(
                    "PRODUCT_QA_EXECUTION_HOLD: prerequisite not passed"
                )
            action = step["action"]
            if action == "ARTIFACT_HASH":
                actual = _sha256_file(artifact)
                if actual != plan["executable_sha256"]:
                    raise ProductQAExecutionHold(
                        "PRODUCT_QA_EXECUTION_HOLD: artifact changed"
                    )
                record(step, "PASS", executable_sha256=actual)
            elif action == "PROCESS_START":
                if process is not None:
                    raise ProductQAExecutionHold(
                        "PRODUCT_QA_EXECUTION_HOLD: process already started"
                    )
                try:
                    process = process_factory(
                        [str(artifact)], cwd=str(artifact.parent),
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except OSError as exc:
                    raise ProductQAExecutionHold(
                        "PRODUCT_QA_EXECUTION_HOLD: process start failed"
                    ) from exc
                seconds = int(step["params"].get("observation_seconds", 5))
                sleeper(seconds)
                if process.poll() is not None:
                    raise ProductQAExecutionHold(
                        "PRODUCT_QA_EXECUTION_HOLD: process exited during observation"
                    )
                record(step, "PASS", process_id=process.pid,
                       observation_seconds=seconds)
            elif action in UIA_ACTIONS:
                if process is None or process.poll() is not None:
                    raise ProductQAExecutionHold(
                        "PRODUCT_QA_EXECUTION_HOLD: product process unavailable"
                    )
                try:
                    observed = uia_executor.execute(
                        action=action, params=step["params"],
                        process_id=process.pid, artifact_path=artifact,
                        expected_sha256=plan["executable_sha256"],
                    )
                except TrustedUIAHold as exc:
                    record(step, "HOLD", reason=str(exc))
                    raise ProductQAExecutionHold(
                        "PRODUCT_QA_EXECUTION_HOLD: trusted UIA action failed"
                    ) from exc
                record(step, "PASS", observed=observed.get("observed", ""),
                       process_id=process.pid)
            elif step.get("required") is True:
                raise ProductQAExecutionHold(
                    "PRODUCT_QA_EXECUTION_HOLD: unsupported required action"
                )
            else:
                record(step, "SKIPPED_UNSUPPORTED_OPTIONAL")
            passed_steps.add(step["step_id"])
        frozen_actions = tuple(actions)
        if before_terminate is not None:
            if process is None or process.poll() is not None:
                raise ProductQAExecutionHold(
                    "PRODUCT_QA_EXECUTION_HOLD: product unavailable for evidence callback"
                )
            before_terminate(process, frozen_actions)
        return ProductQAExecutionResult("TEST_PASS", frozen_actions)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
