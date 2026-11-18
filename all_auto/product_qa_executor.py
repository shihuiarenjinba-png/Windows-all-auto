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


READ_ONLY_DIAGNOSTIC_ACTIONS = {
    "PROCESS_STATUS",
    "UIA_FIND_WINDOW",
    "UIA_FIND_CONTROL",
    "UIA_READ_TEXT",
}


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
    ai_diagnostic_decision: dict[str, Any] | None = None


def execute_bound_product_plan(
    plan: dict[str, Any], *, artifact_path: Path, action_log: Path,
    process_factory: Callable[..., Any] = subprocess.Popen,
    uia_executor: TrustedUIAExecutor | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    before_terminate: Callable[[Any, tuple[dict[str, Any], ...]], None] | None = None,
    diagnostic_planner: Any | None = None,
) -> ProductQAExecutionResult:
    """Run bound steps without accepting executable text from the plan or model.

    With a diagnostic planner, required GitHub-authored steps remain the main
    path. Optional read-only diagnostic steps are not run automatically. If a
    required step fails, Ollama may select only already-authored optional step
    IDs; the deterministic executor performs those exact steps and the failed
    required step still remains a HOLD.
    """
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
    attempted_steps: set[str] = set()
    actions: list[dict[str, Any]] = []
    ai_decision: dict[str, Any] | None = None
    callback_called = False

    def append_item(item: dict[str, Any]) -> None:
        actions.append(item)
        action_log.parent.mkdir(parents=True, exist_ok=True)
        with action_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    def record(step: dict[str, Any], status: str, **details: Any) -> None:
        append_item({
            "step_id": step["step_id"],
            "action": step["action"],
            "target": json.dumps(
                step.get("params", {}), ensure_ascii=False, sort_keys=True,
            ),
            "result": status,
            "details": details,
        })

    def record_ai_decision(decision: dict[str, Any]) -> None:
        append_item({
            "step_id": "ollama-diagnostic-decision",
            "action": "AI_DIAGNOSTIC_DECISION",
            "target": "",
            "result": decision.get("status", "UNKNOWN"),
            "details": decision,
        })

    def execute_step(step: dict[str, Any], *, diagnostic: bool = False) -> None:
        nonlocal process
        if any(required not in passed_steps for required in step["requires"]):
            raise ProductQAExecutionHold(
                "PRODUCT_QA_EXECUTION_HOLD: prerequisite not passed"
            )
        action = step["action"]
        attempted_steps.add(step["step_id"])
        if action == "ARTIFACT_HASH":
            actual = _sha256_file(artifact)
            if actual != plan["executable_sha256"]:
                raise ProductQAExecutionHold(
                    "PRODUCT_QA_EXECUTION_HOLD: artifact changed"
                )
            record(step, "PASS", executable_sha256=actual, diagnostic=diagnostic)
        elif action == "PROCESS_START":
            if diagnostic:
                raise ProductQAExecutionHold(
                    "PRODUCT_QA_EXECUTION_HOLD: diagnostic cannot start product"
                )
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
            record(
                step, "PASS", process_id=process.pid,
                observation_seconds=seconds, diagnostic=diagnostic,
            )
        elif action == "PROCESS_STATUS":
            if process is None:
                record(
                    step, "PASS", process_state="NOT_STARTED",
                    process_id=None, diagnostic=diagnostic,
                )
            else:
                code = process.poll()
                record(
                    step, "PASS",
                    process_state="RUNNING" if code is None else "EXITED",
                    process_id=process.pid, exit_code=code,
                    diagnostic=diagnostic,
                )
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
                record(
                    step, "HOLD", reason=str(exc),
                    process_id=process.pid, diagnostic=diagnostic,
                )
                raise ProductQAExecutionHold(
                    "PRODUCT_QA_EXECUTION_HOLD: trusted UIA action failed"
                ) from exc
            record(
                step, "PASS", observed=observed.get("observed", ""),
                process_id=process.pid, diagnostic=diagnostic,
            )
        elif step.get("required") is True:
            raise ProductQAExecutionHold(
                "PRODUCT_QA_EXECUTION_HOLD: unsupported required action"
            )
        else:
            record(step, "SKIPPED_UNSUPPORTED_OPTIONAL", diagnostic=diagnostic)
        passed_steps.add(step["step_id"])

    def available_optional_diagnostics() -> list[dict[str, Any]]:
        allowed_actions = set(plan.get("allowed_diagnostics") or [])
        result: list[dict[str, Any]] = []
        for step in steps:
            if step.get("required") is not False:
                continue
            if step.get("step_id") in attempted_steps:
                continue
            if step.get("action") not in allowed_actions:
                continue
            if step.get("action") not in READ_ONLY_DIAGNOSTIC_ACTIONS:
                continue
            if any(required not in passed_steps for required in step.get("requires", [])):
                continue
            result.append({
                "step_id": step["step_id"],
                "action": step["action"],
                "params": step.get("params", {}),
                "requires": list(step.get("requires", [])),
            })
        return result

    def run_diagnostics(failed_step: dict[str, Any], failure: Exception) -> None:
        nonlocal ai_decision
        if diagnostic_planner is None:
            return
        available = available_optional_diagnostics()
        if not available:
            ai_decision = {
                "status": "NO_AVAILABLE_OPTIONAL_DIAGNOSTICS",
                "decision": None,
                "errors": [],
                "model": None,
                "source_edit_authority": False,
                "command_execution_authority": False,
            }
            record_ai_decision(ai_decision)
            return
        decision = diagnostic_planner.decide(
            product_type=str(plan.get("product_type", "")),
            failed_step={
                "step_id": failed_step.get("step_id"),
                "action": failed_step.get("action"),
                "failure": str(failure)[:1000],
            },
            execution_history=list(actions),
            available_optional_steps=available,
        )
        ai_decision = decision.as_dict()
        record_ai_decision(ai_decision)
        if decision.status != "AI_DIAGNOSTIC_VALID" or decision.decision is None:
            return
        selected = decision.decision.get("selected_optional_step_ids")
        if not isinstance(selected, list):
            return
        by_id = {
            step["step_id"]: step for step in steps
            if step.get("required") is False
        }
        allowed_ids = {item["step_id"] for item in available}
        for step_id in selected:
            if step_id not in allowed_ids:
                raise ProductQAExecutionHold(
                    "PRODUCT_QA_EXECUTION_HOLD: AI selected unauthorized diagnostic"
                )
            step = by_id[step_id]
            try:
                execute_step(step, diagnostic=True)
            except ProductQAExecutionHold as exc:
                record(
                    step, "DIAGNOSTIC_HOLD",
                    reason=str(exc), diagnostic=True,
                )

    try:
        for step in steps:
            if diagnostic_planner is not None and step.get("required") is False:
                continue
            try:
                execute_step(step)
            except ProductQAExecutionHold as exc:
                if step.get("required") is True:
                    run_diagnostics(step, exc)
                if (before_terminate is not None and process is not None and
                        process.poll() is None and not callback_called):
                    before_terminate(process, tuple(actions))
                    callback_called = True
                raise
        if before_terminate is not None:
            if process is None or process.poll() is not None:
                raise ProductQAExecutionHold(
                    "PRODUCT_QA_EXECUTION_HOLD: product unavailable for evidence callback"
                )
            before_terminate(process, tuple(actions))
            callback_called = True
        return ProductQAExecutionResult(
            "TEST_PASS", tuple(actions), ai_diagnostic_decision=ai_decision,
        )
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
