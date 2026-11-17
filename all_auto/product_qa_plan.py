"""Consume Factory-authored, provenance-bound Windows product QA plans.

The GitHub-side model decides the product-specific QA recipe.  Local Windows
re-validates provenance and authority, then exposes only action IDs that exist
in the local trusted catalog.  Unknown required actions are a HOLD, never a
reason to execute arbitrary command text.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from qa_ai.planner import PlannerOutcome

BOUND_SCHEMA = "windows-product-qa-plan-v1"
TEMPLATE_SCHEMA = "windows-product-qa-plan-template-v1"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
STEP_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
BOUND_KEYS = {
    "schema_version", "product_slug", "product_type", "plan_version",
    "steps", "allowed_diagnostics", "forbidden_actions", "success_policy",
    "template_sha256", "source_repository", "source_sha", "package_sha256",
    "executable_sha256", "identity",
}
STEP_KEYS = {"step_id", "action", "requires", "required", "params"}
SUCCESS_KEYS = {
    "required_steps_must_pass", "evidence_return_required",
    "product_e2e_authority", "release_authority", "store_authority",
}
IDENTITY_KEYS = {"name", "publisher", "version"}
FORBIDDEN_ACTIONS = [
    "SOURCE_EDIT",
    "ARBITRARY_SHELL",
    "GIT_WRITE",
    "STORE_SUBMIT",
    "STORE_PUBLISH",
    "SECURITY_POLICY_CHANGE",
]


class ProductQAPlanHold(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _fail(reason: str) -> None:
    raise ProductQAPlanHold("PRODUCT_QA_PLAN_HOLD: " + reason)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalized_repo(value: str) -> str:
    prefix = "https://github.com/"
    if value.startswith(prefix):
        value = value[len(prefix):]
    return value.removesuffix(".git")


def _template_from_bound(value: dict[str, Any]) -> dict[str, Any]:
    template = {
        key: deepcopy(value[key])
        for key in (
            "product_slug", "product_type", "plan_version", "steps",
            "allowed_diagnostics", "forbidden_actions", "success_policy",
        )
    }
    template["schema_version"] = TEMPLATE_SCHEMA
    return template


def load_bound_plan(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        _fail("plan is missing, linked, or oversized")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductQAPlanHold("PRODUCT_QA_PLAN_HOLD: invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != BOUND_KEYS:
        _fail("bound plan fields are invalid")
    if value.get("schema_version") != BOUND_SCHEMA:
        _fail("schema mismatch")
    slug = value.get("product_slug")
    if not isinstance(slug, str) or not re.fullmatch(r"^[a-z][a-z0-9-]{3,39}$", slug):
        _fail("invalid product slug")
    if value.get("product_type") not in {"APP", "GAME", "GAME_3D"}:
        _fail("invalid product type")
    if value.get("plan_version") != 1:
        _fail("unsupported plan version")
    for field in ("source_sha",):
        if not isinstance(value.get(field), str) or not SHA40.fullmatch(value[field]):
            _fail("invalid source SHA")
    for field in ("package_sha256", "executable_sha256", "template_sha256"):
        if not isinstance(value.get(field), str) or not SHA64.fullmatch(value[field]):
            _fail("invalid SHA-256 field")
    if not isinstance(value.get("source_repository"), str):
        _fail("invalid source repository")
    identity = value.get("identity")
    if not isinstance(identity, dict) or set(identity) != IDENTITY_KEYS or any(
        not isinstance(identity[k], str) or not identity[k] for k in IDENTITY_KEYS
    ):
        _fail("invalid identity binding")

    success = value.get("success_policy")
    if not isinstance(success, dict) or set(success) != SUCCESS_KEYS:
        _fail("invalid success policy")
    if (success.get("required_steps_must_pass") is not True or
            success.get("evidence_return_required") is not True or
            success.get("product_e2e_authority") is not False or
            success.get("release_authority") is not False or
            success.get("store_authority") is not False):
        _fail("plan attempts to grant authority")
    if value.get("forbidden_actions") != FORBIDDEN_ACTIONS:
        _fail("forbidden action contract changed")

    steps = value.get("steps")
    if not isinstance(steps, list) or not 2 <= len(steps) <= 32:
        _fail("invalid step count")
    seen: set[str] = set()
    for step in steps:
        if not isinstance(step, dict) or set(step) != STEP_KEYS:
            _fail("step fields are invalid")
        step_id = step.get("step_id")
        if not isinstance(step_id, str) or not STEP_ID.fullmatch(step_id):
            _fail("invalid step_id")
        if step_id in seen:
            _fail("duplicate step_id")
        requires = step.get("requires")
        if (not isinstance(requires, list) or len(requires) != len(set(requires)) or
                any(not isinstance(item, str) or item not in seen for item in requires)):
            _fail("step dependencies must reference earlier steps")
        if not isinstance(step.get("action"), str):
            _fail("invalid action")
        if type(step.get("required")) is not bool or not isinstance(step.get("params"), dict):
            _fail("invalid step data")
        seen.add(step_id)

    template = _template_from_bound(value)
    if sha256(canonical(template)).hexdigest() != value["template_sha256"]:
        _fail("template hash mismatch")
    return value


def verify_plan_for_job(plan: dict[str, Any], *, job: dict[str, Any],
                        artifact_path: Path,
                        supported_test_ids: set[str]) -> dict[str, Any]:
    artifact = artifact_path.resolve()
    if not artifact.is_file() or artifact_path.is_symlink():
        _fail("artifact is missing or linked")
    if _sha256_file(artifact) != plan["executable_sha256"]:
        _fail("local artifact does not match bound executable SHA")
    if job.get("artifact_sha256") != plan["executable_sha256"]:
        _fail("job artifact SHA differs from plan")
    if job.get("source_sha") != plan["source_sha"]:
        _fail("job source SHA differs from plan")
    if _normalized_repo(str(job.get("source_repository", ""))) != _normalized_repo(
        plan["source_repository"]
    ):
        _fail("job source repository differs from plan")
    if job.get("product_type") != plan["product_type"]:
        _fail("job product type differs from plan")
    slug = job.get("slug")
    if isinstance(slug, str) and slug and slug != plan["product_slug"]:
        _fail("job product slug differs from plan")
    if "package_sha256" in job and job["package_sha256"] != plan["package_sha256"]:
        _fail("job package SHA differs from plan")

    required_actions = {
        step["action"] for step in plan["steps"] if step["required"] is True
    }
    unsupported_required = sorted(required_actions - supported_test_ids)
    return {
        "status": (
            "PRODUCT_QA_PLAN_READY"
            if not unsupported_required
            else "PRODUCT_QA_PLAN_CAPABILITY_HOLD"
        ),
        "unsupported_required_actions": unsupported_required,
        "required_actions": sorted(required_actions),
        "source_sha": plan["source_sha"],
        "executable_sha256": plan["executable_sha256"],
        "package_sha256": plan["package_sha256"],
        "product_slug": plan["product_slug"],
        "product_type": plan["product_type"],
        "template_sha256": plan["template_sha256"],
    }


@dataclass
class BoundProductPlanPlanner:
    """Feed the required GitHub-authored action order into QASupervisor.

    Only action IDs already present in the local trusted catalog are emitted.
    This is intentionally not a shell-command planner.
    """
    plan: dict[str, Any]
    supported_test_ids: set[str]

    def __post_init__(self) -> None:
        required = {
            step["action"] for step in self.plan["steps"] if step["required"] is True
        }
        unsupported = sorted(required - self.supported_test_ids)
        if unsupported:
            _fail("unsupported required actions: " + ", ".join(unsupported))

    def plan(self, *, context: dict[str, str], catalog: list[dict[str, Any]],
             evidence: str, round_number: int,
             execution_history: list[dict[str, Any]] | None = None) -> PlannerOutcome:
        del catalog, evidence, round_number
        history = execution_history or []
        passed = {
            item["test_id"] for item in history
            if item.get("status") == "TEST_PASS"
        }
        failed = {
            item["test_id"] for item in history
            if item.get("status") != "TEST_PASS"
        }
        if failed:
            return PlannerOutcome(
                "AI_PLAN_VALID",
                {
                    "schema_version": "windows-qa-plan-v1",
                    "selected_test_ids": [],
                    "reason": "GitHub-authored required QA step failed.",
                    "missing_evidence": [],
                    "expected_signal": [],
                    "retry_policy": "NO_RETRY",
                    "stop_reason": "Required product QA step failed; return evidence for repair.",
                    "recommended_owner": context["product_type"],
                },
                (), "github-product-qa-plan", {},
            )

        step_id_to_action = {
            step["step_id"]: step["action"] for step in self.plan["steps"]
        }
        for step in self.plan["steps"]:
            if step["required"] is not True:
                continue
            action = step["action"]
            if action in passed:
                continue
            required_actions = [step_id_to_action[item] for item in step["requires"]]
            if any(item not in passed for item in required_actions):
                continue
            return PlannerOutcome(
                "AI_PLAN_VALID",
                {
                    "schema_version": "windows-qa-plan-v1",
                    "selected_test_ids": [action],
                    "reason": "Execute next required GitHub-authored sale-preflight step.",
                    "missing_evidence": ["result for " + step["step_id"]],
                    "expected_signal": ["deterministic " + action + " result"],
                    "retry_policy": "NO_RETRY",
                    "stop_reason": None,
                    "recommended_owner": context["product_type"],
                },
                (), "github-product-qa-plan", {},
            )

        return PlannerOutcome(
            "AI_PLAN_VALID",
            {
                "schema_version": "windows-qa-plan-v1",
                "selected_test_ids": [],
                "reason": "All locally supported required GitHub-authored QA steps passed.",
                "missing_evidence": [],
                "expected_signal": [],
                "retry_policy": "NO_RETRY",
                "stop_reason": "Required structured product QA plan completed.",
                "recommended_owner": context["product_type"],
            },
            (), "github-product-qa-plan", {},
        )
