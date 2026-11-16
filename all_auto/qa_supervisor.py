"""Bounded Ollama supervision over a hash-pinned local QA test catalog."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable

from all_auto.local_qa_evidence import (
    EvidenceStore, atomic_json, process_retry_queue,
)
from qa_ai.analyzer import AnalysisEngine, analyze_run
from qa_ai.planner import PlannerEngine, PlannerOutcome


CATALOG_SCHEMA = "trusted-local-qa-catalog-v1"
SUPERVISOR_SCHEMA = "windows-qa-supervisor-v1"
# Updated only with an intentional catalog review. Product artifacts and model
# output cannot supply or replace this value.
DEFAULT_CATALOG_SHA256 = "a5794ce52bf5b581ac4bc3e4d6c5edbf887c15c833cf46911f066ba32a769541"
TEST_ID = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
TEMPLATE_FIELDS = {"{artifact_path}", "{artifact_sha256}"}
SPEC_KEYS = {
    "test_id", "description", "allowed_product_types", "executable",
    "arguments_template", "timeout_seconds", "expected_exit_codes",
    "completion_policy", "observation_seconds",
    "gui_test", "admin_required", "destructive", "side_effect_class",
    "resource_units", "max_retries", "supported_gui_operation",
    "evidence_requirements", "requires_test_passes",
}


class CatalogError(ValueError):
    pass


class PolicyViolation(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _has_symlink_component(path: Path, root: Path) -> bool:
    current = path
    while _is_within(current, root):
        if current.is_symlink():
            return True
        if current == root:
            break
        current = current.parent
    return False


@dataclass(frozen=True)
class TestDefinition:
    test_id: str
    description: str
    allowed_product_types: tuple[str, ...]
    executable: str
    arguments_template: tuple[str, ...]
    timeout_seconds: int
    expected_exit_codes: tuple[int, ...]
    completion_policy: str
    observation_seconds: int
    gui_test: bool
    admin_required: bool
    destructive: bool
    side_effect_class: str
    resource_units: int
    max_retries: int
    supported_gui_operation: str | None
    evidence_requirements: tuple[str, ...]
    requires_test_passes: tuple[str, ...]


class TrustedTestCatalog:
    def __init__(self, tests: dict[str, TestDefinition], *, digest: str,
                 path: Path):
        self.tests = tests
        self.digest = digest
        self.path = path

    @classmethod
    def load(cls, path: Path, *, expected_sha256: str,
             trusted_root: Path | None = None) -> "TrustedTestCatalog":
        if not SHA64.fullmatch(expected_sha256):
            raise CatalogError("trusted catalog requires a pinned SHA-256")
        trusted_root = (trusted_root or path.parent).resolve()
        if trusted_root.is_symlink():
            raise CatalogError("trusted catalog root may not be a symlink")
        resolved = path.resolve()
        if not _is_within(resolved, trusted_root):
            raise CatalogError("trusted catalog path escapes trusted root")
        if path.is_symlink() or _has_symlink_component(path.absolute(), trusted_root):
            raise CatalogError("trusted catalog may not use symlinks")
        if not resolved.is_file():
            raise CatalogError("trusted catalog is missing")
        try:
            value = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogError("trusted catalog is invalid JSON") from exc
        digest = hashlib.sha256(json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        if digest != expected_sha256:
            raise CatalogError("trusted catalog SHA-256 mismatch")
        if not isinstance(value, dict) or set(value) != {"schema_version", "tests"}:
            raise CatalogError("trusted catalog fields are invalid")
        if value.get("schema_version") != CATALOG_SCHEMA:
            raise CatalogError("trusted catalog schema mismatch")
        entries = value.get("tests")
        if not isinstance(entries, list) or not entries:
            raise CatalogError("trusted catalog must contain tests")
        tests: dict[str, TestDefinition] = {}
        for entry in entries:
            definition = cls._definition(entry)
            if definition.test_id in tests:
                raise CatalogError("duplicate trusted test ID")
            tests[definition.test_id] = definition
        for definition in tests.values():
            for required in definition.requires_test_passes:
                if required == definition.test_id:
                    raise CatalogError("trusted test may not depend on itself")
                if required not in tests:
                    raise CatalogError("trusted test dependency is missing: " + required)

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(test_id: str) -> None:
            if test_id in visiting:
                raise CatalogError("trusted test dependency cycle")
            if test_id in visited:
                return
            visiting.add(test_id)
            for required in tests[test_id].requires_test_passes:
                visit(required)
            visiting.remove(test_id)
            visited.add(test_id)

        for test_id in tests:
            visit(test_id)
        return cls(tests, digest=digest, path=resolved)

    @staticmethod
    def _definition(value: Any) -> TestDefinition:
        if not isinstance(value, dict) or set(value) != SPEC_KEYS:
            raise CatalogError("trusted test fields are invalid")
        test_id = value.get("test_id")
        if not isinstance(test_id, str) or not TEST_ID.fullmatch(test_id):
            raise CatalogError("invalid trusted test ID")
        executable = value.get("executable")
        if executable not in {"TRUSTED_PYTHON_QA_RUNNER", "TRUSTED_ARTIFACT_PROCESS"}:
            raise CatalogError("untrusted executable identifier")
        product_types = value.get("allowed_product_types")
        if not isinstance(product_types, list) or not product_types or any(
            item not in {"APP", "GAME", "GAME_3D"} for item in product_types
        ):
            raise CatalogError("invalid product type allowlist")
        arguments = value.get("arguments_template")
        if not isinstance(arguments, list) or not arguments or any(
            not isinstance(item, str) or not item for item in arguments
        ):
            raise CatalogError("invalid trusted argument template")
        for item in arguments:
            if item in TEMPLATE_FIELDS:
                continue
            if "{" in item or "}" in item or ".." in item or re.search(r"[;&|`]", item):
                raise CatalogError("argument template contains injection or traversal")
            if Path(item).is_absolute():
                raise CatalogError("argument template contains an absolute path")
        if (executable == "TRUSTED_ARTIFACT_PROCESS" and
                arguments != ["{artifact_path}"]):
            raise CatalogError("artifact process cannot receive arguments")
        timeout = value.get("timeout_seconds")
        completion_policy = value.get("completion_policy")
        observation_seconds = value.get("observation_seconds")
        resource = value.get("resource_units")
        retries = value.get("max_retries")
        exits = value.get("expected_exit_codes")
        if type(timeout) is not int or not 1 <= timeout <= 600:
            raise CatalogError("invalid timeout")
        if type(resource) is not int or not 1 <= resource <= 100:
            raise CatalogError("invalid resource units")
        if type(retries) is not int or not 0 <= retries <= 1:
            raise CatalogError("invalid retry ceiling")
        if (not isinstance(exits, list) or len(exits) != 1 or
                any(type(x) is not int for x in exits)):
            raise CatalogError("invalid expected exit codes")
        if completion_policy not in {
            "WAIT_FOR_EXIT", "PASS_IF_RUNNING_AFTER_OBSERVATION",
        }:
            raise CatalogError("invalid completion policy")
        if type(observation_seconds) is not int or not 0 <= observation_seconds <= 30:
            raise CatalogError("invalid observation seconds")
        if completion_policy == "WAIT_FOR_EXIT" and observation_seconds != 0:
            raise CatalogError("exit completion policy cannot observe a running process")
        if completion_policy == "PASS_IF_RUNNING_AFTER_OBSERVATION" and not (
            executable == "TRUSTED_ARTIFACT_PROCESS" and
            1 <= observation_seconds < timeout
        ):
            raise CatalogError("process start observation policy is invalid")
        for field in ("gui_test", "admin_required", "destructive"):
            if type(value.get(field)) is not bool:
                raise CatalogError("invalid boolean catalog field: " + field)
        if value.get("side_effect_class") not in {"READ_ONLY", "PROCESS_EXECUTION"}:
            raise CatalogError("invalid side-effect class")
        operation = value.get("supported_gui_operation")
        if operation is not None and (
            not isinstance(operation, str) or not TEST_ID.fullmatch(operation)
        ):
            raise CatalogError("invalid GUI operation")
        evidence = value.get("evidence_requirements")
        if not isinstance(evidence, list) or not evidence or any(
            not isinstance(item, str) or not item for item in evidence
        ):
            raise CatalogError("invalid evidence requirements")
        requirements = value.get("requires_test_passes")
        if (not isinstance(requirements, list) or
                any(not isinstance(item, str) or not TEST_ID.fullmatch(item)
                    for item in requirements) or
                len(requirements) != len(set(requirements))):
            raise CatalogError("invalid trusted test dependencies")
        description = value.get("description")
        if not isinstance(description, str) or not description.strip():
            raise CatalogError("test description is required")
        return TestDefinition(
            test_id=test_id, description=description,
            allowed_product_types=tuple(product_types),
            executable=value["executable"], arguments_template=tuple(arguments),
            timeout_seconds=timeout, expected_exit_codes=tuple(exits),
            completion_policy=completion_policy,
            observation_seconds=observation_seconds,
            gui_test=value["gui_test"], admin_required=value["admin_required"],
            destructive=value["destructive"],
            side_effect_class=value["side_effect_class"],
            resource_units=resource, max_retries=retries,
            supported_gui_operation=operation,
            evidence_requirements=tuple(evidence),
            requires_test_passes=tuple(requirements),
        )

    def planner_summary(self, product_type: str) -> list[dict[str, Any]]:
        return [
            {
                "test_id": item.test_id,
                "description": item.description,
                "gui_test": item.gui_test,
                "max_retries": item.max_retries,
                "evidence_requirements": list(item.evidence_requirements),
                "requires_test_passes": list(item.requires_test_passes),
            }
            for item in self.tests.values()
            if product_type in item.allowed_product_types
        ]


def load_default_catalog() -> TrustedTestCatalog:
    root = Path(__file__).resolve().parents[1]
    config = root / "config" / "trusted-local-qa-tests-v1.json"
    return TrustedTestCatalog.load(
        config, expected_sha256=DEFAULT_CATALOG_SHA256,
        trusted_root=config.parent,
    )


def require_new_source_sha(previous_handoff: Path,
                           new_job: dict[str, Any]) -> None:
    """Fail closed when a claimed repair reuses the previously tested SHA."""
    try:
        prior = json.loads(previous_handoff.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyViolation("previous repair handoff is unavailable") from exc
    old_sha = prior.get("source_sha")
    new_sha = new_job.get("source_sha")
    if (prior.get("schema_version") != "windows-qa-repair-handoff-v1" or
            not isinstance(old_sha, str) or not SHA40.fullmatch(old_sha)):
        raise PolicyViolation("previous repair handoff is invalid")
    if not isinstance(new_sha, str) or not SHA40.fullmatch(new_sha):
        raise PolicyViolation("new QA job source SHA is invalid")
    if new_sha == old_sha:
        raise PolicyViolation("repaired product retest requires a new source SHA")


@dataclass(frozen=True)
class ExecutionPolicy:
    max_planner_rounds: int = 5
    max_tests: int = 12
    max_total_runtime_seconds: int = 30 * 60
    max_identical_retry: int = 1
    max_resource_units: int = 24
    allow_admin: bool = False
    allow_destructive: bool = False
    supported_gui_operations: frozenset[str] = frozenset()


@dataclass(frozen=True)
class AuthorizedTest:
    definition: TestDefinition
    command: tuple[str, ...]
    cwd: Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class PolicyGuard:
    def __init__(self, catalog: TrustedTestCatalog,
                 policy: ExecutionPolicy | None = None):
        self.catalog = catalog
        self.policy = policy or ExecutionPolicy()

    def authorize(self, *, plan: dict[str, Any], job: dict[str, Any],
                  artifact_path: Path, intake_root: Path,
                  executions: list[dict[str, Any]],
                  resource_units_used: int) -> list[AuthorizedTest]:
        root = intake_root.resolve()
        artifact = artifact_path.resolve()
        if not root.is_dir() or not artifact.is_file() or not _is_within(artifact, root):
            raise PolicyViolation("artifact path escapes the trusted intake root")
        if artifact_path.is_symlink() or _has_symlink_component(
            artifact_path.absolute(), root
        ):
            raise PolicyViolation("artifact path contains a symlink")
        expected_artifact_sha = job.get("artifact_sha256")
        if (not isinstance(expected_artifact_sha, str) or
                not SHA64.fullmatch(expected_artifact_sha)):
            raise PolicyViolation("job artifact SHA-256 is invalid")
        if _sha256_file(artifact) != expected_artifact_sha:
            raise PolicyViolation("artifact SHA-256 changed after immutable intake")
        selected = plan.get("selected_test_ids")
        if not isinstance(selected, list):
            raise PolicyViolation("planner did not provide test IDs")
        if len(executions) + len(selected) > self.policy.max_tests:
            raise PolicyViolation("test count budget exceeded")
        counts: dict[str, int] = {}
        passed: set[str] = set()
        for result in executions:
            test_id = result.get("test_id")
            if isinstance(test_id, str):
                counts[test_id] = counts.get(test_id, 0) + 1
                if result.get("status") == "TEST_PASS":
                    passed.add(test_id)
        authorized: list[AuthorizedTest] = []
        planned_resource = resource_units_used
        planned_timeout = sum(int(item.get("timeout_seconds", 0)) for item in executions)
        for test_id in selected:
            definition = self.catalog.tests.get(test_id)
            if definition is None:
                raise PolicyViolation("unknown test ID")
            if job.get("product_type") not in definition.allowed_product_types:
                raise PolicyViolation("test is disallowed for this product type")
            missing_prerequisites = [
                required for required in definition.requires_test_passes
                if required not in passed
            ]
            if missing_prerequisites:
                raise PolicyViolation(
                    "required prerequisite tests have not passed: " +
                    ", ".join(missing_prerequisites)
                )
            if definition.admin_required and not self.policy.allow_admin:
                raise PolicyViolation("admin-only test is not approved")
            if definition.destructive and not self.policy.allow_destructive:
                raise PolicyViolation("destructive test is not approved")
            if definition.gui_test and definition.supported_gui_operation not in (
                self.policy.supported_gui_operations
            ):
                raise PolicyViolation("unsupported GUI operation")
            previous = counts.get(test_id, 0)
            if previous and plan.get("retry_policy") != "RETRY_FAILED_ONCE":
                raise PolicyViolation("retry was not explicitly requested")
            if previous >= 1 + definition.max_retries:
                raise PolicyViolation("retry ceiling exceeded")
            planned_resource += definition.resource_units
            planned_timeout += definition.timeout_seconds
            if planned_resource > self.policy.max_resource_units:
                raise PolicyViolation("resource budget exceeded")
            if planned_timeout > self.policy.max_total_runtime_seconds:
                raise PolicyViolation("runtime budget exceeded")
            mapping = {
                "{artifact_path}": str(artifact),
                "{artifact_sha256}": str(job.get("artifact_sha256", "")),
            }
            arguments = [mapping.get(item, item) for item in definition.arguments_template]
            if definition.executable == "TRUSTED_PYTHON_QA_RUNNER":
                trusted_runner = (
                    Path(__file__).resolve().parents[1] /
                    "scripts" / "trusted_qa_test_runner.py"
                )
                if not trusted_runner.is_file() or trusted_runner.is_symlink():
                    raise PolicyViolation("trusted QA runner is missing or linked")
                command = [sys.executable, str(trusted_runner), *arguments]
            elif artifact.suffix.lower() == ".py":
                command = [sys.executable, str(artifact)]
            else:
                command = [str(artifact)]
            authorized.append(AuthorizedTest(
                definition=definition,
                command=tuple(command),
                cwd=root,
            ))
            counts[test_id] = previous + 1
        return authorized


class SupervisorStateStore:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, request_id: str) -> Path:
        key = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        return self.root / (key + ".json")

    def checkpoint(self, path: Path, state: dict[str, Any]) -> None:
        atomic_json(path, state)

    def recover_interrupted(self) -> list[str]:
        recovered: list[str] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if state.get("status") != "RUNNING":
                continue
            state.update({
                "status": "INTERRUPTED_RESTART",
                "finished_at_utc": _utc_now(),
                "evidence_return_e2e_pass": False,
                "product_e2e_pass": False,
                "e2e_pass": False, "release_ready": False,
                "store_submission_allowed": False,
            })
            atomic_json(path, state)
            recovered.append(str(state.get("request_id")))
        return recovered


def _sanitized_run_summary(run_directory: Path) -> str:
    envelope = json.loads(
        (run_directory / "github-envelope.json").read_text(encoding="utf-8")
    )
    payload = envelope["payload"]
    chunks = ["MANIFEST\n" + json.dumps(
        payload.get("manifest", {}), ensure_ascii=False, sort_keys=True,
    )]
    for item in payload.get("files", []):
        if item.get("path") not in {
            "stdout.log", "stderr.log", "windows-event-log.xml",
            "windows-event-log.unavailable.txt", "uia-actions.jsonl",
            "analysis/windows-qa-analysis.json",
        }:
            continue
        try:
            text = base64.b64decode(item["content"]).decode("utf-8", errors="replace")
        except (KeyError, TypeError, ValueError):
            continue
        chunks.append("FILE " + item["path"] + "\n" + text)
    return "\n\n".join(chunks)


@dataclass(frozen=True)
class SupervisorResult:
    status: str
    state_path: Path
    run_ids: tuple[str, ...]
    test_status: str
    evidence_return_e2e_pass: bool
    product_e2e_pass: bool
    handoff_path: Path


class QASupervisor:
    def __init__(self, *, catalog: TrustedTestCatalog, store: EvidenceStore,
                 planner: PlannerEngine, guard: PolicyGuard | None = None,
                 transport: Any | None = None,
                 analyzer: AnalysisEngine | None = None,
                 event_log_collector: Callable[[str, str], str] | None = None,
                 monotonic: Callable[[], float] = time.monotonic):
        self.catalog = catalog
        self.store = store
        self.planner = planner
        self.guard = guard or PolicyGuard(catalog)
        self.transport = transport
        self.analyzer = analyzer
        self.event_log_collector = event_log_collector
        self.monotonic = monotonic
        self.states = SupervisorStateStore(store.root / "supervisor-state")
        self.handoffs = store.root / "repair-handoffs"
        self.handoffs.mkdir(parents=True, exist_ok=True)

    def run(self, *, job: dict[str, Any], artifact_path: Path,
            intake_root: Path) -> SupervisorResult:
        context = {
            "target_repository": str(job.get("source_repository", "")),
            "source_sha": str(job.get("source_sha", "")),
            "request_id": str(job.get("request_id", "")),
            "product_type": str(job.get("product_type", "")),
            "artifact_sha256": str(job.get("artifact_sha256", "")),
        }
        state_path = self.states.path_for(context["request_id"])
        state: dict[str, Any] = {
            "schema_version": SUPERVISOR_SCHEMA,
            "request_id": context["request_id"],
            "source_sha": context["source_sha"],
            "artifact_sha256": context["artifact_sha256"],
            "product_type": context["product_type"],
            "catalog_sha256": self.catalog.digest,
            "status": "RUNNING", "started_at_utc": _utc_now(),
            "finished_at_utc": None, "planner_rounds": [], "executions": [],
            "evidence_return_e2e_pass": False,
            "product_e2e_pass": False, "e2e_pass": False,
            "release_ready": False, "store_submission_allowed": False,
            "user_product_approval": False, "user_price_approval": False,
        }
        self.states.checkpoint(state_path, state)
        started = self.monotonic()
        evidence = "No trusted tests have executed yet."
        resource_used = 0
        last_fingerprint: str | None = None
        identical_repeats = 0
        final_status = "MAX_PLANNER_ROUNDS"
        missing_evidence: list[str] = []
        recommended_owner = context["product_type"]
        recommended_regressions: set[str] = set()
        analysis_failure_class = "UNKNOWN"

        for round_number in range(1, self.guard.policy.max_planner_rounds + 1):
            if self.monotonic() - started > self.guard.policy.max_total_runtime_seconds:
                final_status = "RUNTIME_BUDGET_EXCEEDED"
                break
            outcome: PlannerOutcome = self.planner.plan(
                context=context,
                catalog=self.catalog.planner_summary(context["product_type"]),
                evidence=evidence, round_number=round_number,
                execution_history=[
                    {key: item[key] for key in (
                        "test_id", "status", "exit_code", "timed_out",
                    )}
                    for item in state["executions"]
                ],
            )
            round_record = outcome.as_dict()
            state["planner_rounds"].append(round_record)
            self.states.checkpoint(state_path, state)
            if outcome.status != "AI_PLAN_VALID" or outcome.plan is None:
                final_status = "AI_PLANNER_UNAVAILABLE"
                break
            plan = outcome.plan
            missing_evidence = list(plan["missing_evidence"])
            recommended_owner = plan["recommended_owner"]
            recommended_regressions.update(plan["selected_test_ids"])
            if not plan["selected_test_ids"]:
                final_status = "SUPERVISOR_COMPLETE"
                break
            try:
                authorized = self.guard.authorize(
                    plan=plan, job=job, artifact_path=artifact_path,
                    intake_root=intake_root, executions=state["executions"],
                    resource_units_used=resource_used,
                )
            except PolicyViolation as exc:
                round_record["policy_error"] = str(exc)
                final_status = "POLICY_VIOLATION"
                self.states.checkpoint(state_path, state)
                break
            current_results: list[dict[str, Any]] = []
            summaries: list[str] = []
            for item in authorized:
                result = self.store.execute(
                    job, list(item.command), cwd=item.cwd,
                    timeout_seconds=item.definition.timeout_seconds,
                    expected={
                        "exit_code": item.definition.expected_exit_codes[0],
                        "completion_policy": item.definition.completion_policy,
                        "observation_seconds": item.definition.observation_seconds,
                    },
                    gui_test=item.definition.gui_test,
                    event_log_collector=self.event_log_collector,
                    pass_if_running_after_seconds=(
                        item.definition.observation_seconds
                        if item.definition.completion_policy ==
                        "PASS_IF_RUNNING_AFTER_OBSERVATION" else None
                    ),
                )
                analysis_status = "DISABLED"
                if self.analyzer is not None:
                    analysis = analyze_run(
                        self.store, result.run_directory, engine=self.analyzer,
                    )
                    analysis_status = analysis.status
                    if analysis.analysis is not None:
                        analysis_failure_class = str(
                            analysis.analysis.get("failure_class", "UNKNOWN")
                        )
                record = {
                    "test_id": item.definition.test_id,
                    "run_id": result.run_id, "status": result.status,
                    "exit_code": result.exit_code, "timed_out": result.timed_out,
                    "timeout_seconds": item.definition.timeout_seconds,
                    "resource_units": item.definition.resource_units,
                    "analysis_status": analysis_status,
                }
                state["executions"].append(record)
                current_results.append(record)
                resource_used += item.definition.resource_units
                summaries.append(_sanitized_run_summary(result.run_directory))
                self.states.checkpoint(state_path, state)
            fingerprint = hashlib.sha256(json.dumps(
                {
                    "selected": plan["selected_test_ids"],
                    "results": [
                        {key: item[key] for key in (
                            "test_id", "status", "exit_code", "timed_out",
                        )}
                        for item in current_results
                    ],
                },
                sort_keys=True,
            ).encode("utf-8")).hexdigest()
            if fingerprint == last_fingerprint:
                identical_repeats += 1
                if identical_repeats > self.guard.policy.max_identical_retry:
                    final_status = "REPEATED_IDENTICAL_RESULT"
                    break
            else:
                identical_repeats = 0
            last_fingerprint = fingerprint
            evidence = "\n\n--- NEXT TRUSTED TEST RESULT ---\n\n".join(summaries)
        if self.transport is not None:
            state["github_return"] = process_retry_queue(
                self.store, self.transport, max_items=self.guard.policy.max_tests,
            )
        else:
            state["github_return"] = {
                "verified": 0, "failed": 0, "deferred": 0, "locked": 0,
            }
        manifests = []
        for record in state["executions"]:
            path = self.store.runs / record["run_id"] / "manifest.json"
            manifests.append(json.loads(path.read_text(encoding="utf-8")))
        test_status = (
            "TEST_PASS" if manifests and all(
                item.get("status") == "TEST_PASS" for item in manifests
            ) else "TEST_FAIL"
        )
        evidence_pass = bool(manifests) and all(
            item.get("evidence_return_e2e_pass") is True for item in manifests
        )
        failed_ids = [
            item["test_id"] for item in state["executions"]
            if item["status"] != "TEST_PASS"
        ]
        handoff = {
            "schema_version": "windows-qa-repair-handoff-v1",
            "source_sha": context["source_sha"],
            "request_id": context["request_id"],
            "artifact_sha256": context["artifact_sha256"],
            "failed_test_ids": failed_ids,
            "failure_class": analysis_failure_class,
            "observed_evidence": [
                {"test_id": item["test_id"], "status": item["status"],
                 "exit_code": item["exit_code"], "timed_out": item["timed_out"]}
                for item in state["executions"]
            ],
            "missing_evidence": missing_evidence,
            "recommended_owner": recommended_owner,
            "recommended_regression_test_ids": sorted(
                recommended_regressions & set(self.catalog.tests)
            ),
            "agent_dispatch_status": "AGENT_DISPATCH_PENDING",
            "source_edit_authority": False,
            "retest_requires_new_source_sha": True,
            "product_e2e_pass": False,
            "release_ready": False,
            "store_submission_allowed": False,
        }
        handoff_path = self.handoffs / (
            hashlib.sha256(context["request_id"].encode("utf-8")).hexdigest() + ".json"
        )
        atomic_json(handoff_path, handoff)
        if final_status == "SUPERVISOR_COMPLETE" and not manifests:
            final_status = "NO_TESTS_EXECUTED"
        state.update({
            "status": final_status, "finished_at_utc": _utc_now(),
            "test_status": test_status,
            "evidence_return_e2e_pass": evidence_pass,
            "product_e2e_pass": False, "e2e_pass": False,
            "release_ready": False, "store_submission_allowed": False,
            "user_product_approval": False, "user_price_approval": False,
            "handoff": str(handoff_path.relative_to(self.store.root)),
        })
        self.states.checkpoint(state_path, state)
        return SupervisorResult(
            status=final_status, state_path=state_path,
            run_ids=tuple(item["run_id"] for item in state["executions"]),
            test_status=test_status,
            evidence_return_e2e_pass=evidence_pass,
            product_e2e_pass=False, handoff_path=handoff_path,
        )
