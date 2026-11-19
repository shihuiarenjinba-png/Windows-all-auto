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
import xml.etree.ElementTree as ET
import zipfile

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
ACTIONS = {
    "ARTIFACT_HASH", "PROCESS_START", "PROCESS_STATUS", "EVENT_LOG_QUERY",
    "UIA_FIND_WINDOW", "UIA_FIND_CONTROL", "UIA_INVOKE", "UIA_READ_TEXT",
    "UIA_SET_TEXT",
}
DIAGNOSTICS = {
    "PROCESS_STATUS", "EVENT_LOG_QUERY", "UIA_FIND_WINDOW",
    "UIA_FIND_CONTROL", "UIA_READ_TEXT",
}
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


def _inspect_package(path: Path) -> dict[str, Any]:
    """Independently bind an intake package to its Identity and executable.

    This intentionally does not reuse Factory code.  Local Windows treats the
    package as untrusted ZIP input and derives all provenance again.
    """
    package = path.resolve()
    if (path.is_symlink() or not package.is_file() or
            not 0 < package.stat().st_size <= 300 * 1024 * 1024):
        _fail("package is missing, linked, empty, or oversized")
    try:
        with zipfile.ZipFile(package) as archive:
            entries = archive.infolist()
            if not 2 <= len(entries) <= 2000:
                _fail("unsafe package file count")
            names: dict[str, zipfile.ZipInfo] = {}
            for entry in entries:
                name = entry.filename.replace("\\", "/")
                parts = name.split("/")
                if (name.startswith("/") or any(
                        not part or part in {".", ".."} or
                        part.endswith((" ", ".")) or ":" in part or
                        any(ord(character) < 32 or ord(character) == 127
                            for character in part)
                        for part in parts)):
                    _fail("unsafe package member path")
                if (entry.file_size > 300 * 1024 * 1024 or
                        (entry.compress_size and
                         entry.file_size > 100 * entry.compress_size)):
                    _fail("unsafe package member size")
                folded = name.casefold()
                if folded in names:
                    _fail("duplicate package member name")
                names[folded] = entry
            manifest_entry = names.get("appxmanifest.xml")
            if manifest_entry is None or not 0 < manifest_entry.file_size <= 2 * 1024 * 1024:
                _fail("package manifest missing or oversized")
            root = ET.fromstring(archive.read(manifest_entry))
            if root.tag.rsplit("}", 1)[-1] != "Package":
                _fail("package manifest root invalid")
            identities = [
                element for element in root.iter()
                if element.tag.rsplit("}", 1)[-1] == "Identity"
            ]
            applications = [
                element for element in root.iter()
                if element.tag.rsplit("}", 1)[-1] == "Application"
            ]
            if len(identities) != 1 or len(applications) != 1:
                _fail("package must contain one Identity and one Application")
            identity = {
                "name": identities[0].attrib.get("Name"),
                "publisher": identities[0].attrib.get("Publisher"),
                "version": identities[0].attrib.get("Version"),
            }
            if any(not isinstance(value, str) or not value for value in identity.values()):
                _fail("package identity fields incomplete")
            executable = applications[0].attrib.get("Executable")
            if not isinstance(executable, str) or not executable:
                _fail("package executable path missing")
            executable_name = executable.replace("\\", "/")
            executable_entry = names.get(executable_name.casefold())
            if (executable_entry is None or executable_entry.is_dir() or
                    not 0 < executable_entry.file_size <= 300 * 1024 * 1024):
                _fail("package executable payload missing or empty")
            executable_digest = sha256()
            with archive.open(executable_entry) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    executable_digest.update(block)
    except ProductQAPlanHold:
        raise
    except (OSError, KeyError, RuntimeError, ET.ParseError,
            zipfile.BadZipFile) as exc:
        raise ProductQAPlanHold(
            "PRODUCT_QA_PLAN_HOLD: invalid package container: " + type(exc).__name__
        ) from exc
    return {
        "package_sha256": _sha256_file(package),
        "executable_sha256": executable_digest.hexdigest(),
        "identity": identity,
    }


def _validate_params(action: str, params: Any) -> None:
    if not isinstance(params, dict):
        _fail("params must be an object")
    if action == "ARTIFACT_HASH":
        if params:
            _fail("ARTIFACT_HASH takes no parameters")
        return
    if action == "PROCESS_START":
        if set(params) - {"observation_seconds"}:
            _fail("PROCESS_START has unknown parameters")
        seconds = params.get("observation_seconds", 5)
        if type(seconds) is not int or not 1 <= seconds <= 60:
            _fail("invalid PROCESS_START observation_seconds")
        return
    if action == "PROCESS_STATUS":
        if params:
            _fail("PROCESS_STATUS takes no parameters")
        return
    if action == "EVENT_LOG_QUERY":
        if set(params) - {"lookback_seconds"}:
            _fail("EVENT_LOG_QUERY has unknown parameters")
        seconds = params.get("lookback_seconds", 300)
        if type(seconds) is not int or not 1 <= seconds <= 900:
            _fail("invalid EVENT_LOG_QUERY lookback_seconds")
        return
    if action == "UIA_FIND_WINDOW":
        if set(params) != {"title_contains"}:
            _fail("UIA_FIND_WINDOW requires title_contains only")
        title = params["title_contains"]
        if not isinstance(title, str) or not 1 <= len(title) <= 120:
            _fail("invalid UIA window title")
        return
    if action in {
            "UIA_FIND_CONTROL", "UIA_INVOKE", "UIA_READ_TEXT",
            "UIA_SET_TEXT"}:
        allowed = {"name", "control_type"}
        if action == "UIA_SET_TEXT":
            allowed.add("value")
        if set(params) - allowed or "name" not in params:
            _fail(action + " requires name and optional control_type")
        name = params["name"]
        if not isinstance(name, str) or not 1 <= len(name) <= 120:
            _fail("invalid UIA control name")
        control = params.get("control_type")
        if control is not None and control not in {
            "Button", "Edit", "Text", "CheckBox", "ComboBox", "ListItem",
            "TabItem", "Document", "Group", "Pane",
        }:
            _fail("unsupported UIA control_type")
        if action == "UIA_SET_TEXT":
            if "value" not in params:
                _fail("UIA_SET_TEXT requires value")
            value = params["value"]
            if not isinstance(value, str) or len(value) > 4096:
                _fail("invalid UIA_SET_TEXT value")
            if control not in {None, "Edit"}:
                _fail("UIA_SET_TEXT control_type must be Edit")
        return
    _fail("unsupported action")


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
    if (not isinstance(value.get("source_repository"), str) or
            not value["source_repository"].startswith("https://github.com/")):
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
    step_by_id: dict[str, dict[str, Any]] = {}
    actions: list[str] = []
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
        action = step.get("action")
        if action not in ACTIONS:
            _fail("unsupported action")
        if type(step.get("required")) is not bool:
            _fail("invalid step required flag")
        _validate_params(action, step.get("params"))
        seen.add(step_id)
        step_by_id[step_id] = step
        actions.append(action)
    if actions[0] != "ARTIFACT_HASH":
        _fail("first step must be ARTIFACT_HASH")
    hash_step = steps[0]["step_id"]
    for step in steps[1:]:
        if step["action"] != "ARTIFACT_HASH" and hash_step not in step["requires"]:
            _fail("every executable/diagnostic step must require ARTIFACT_HASH")
    process_ids = [
        step["step_id"] for step in steps if step["action"] == "PROCESS_START"
    ]
    if len(process_ids) != 1:
        _fail("exactly one PROCESS_START step is required")
    process_id = process_ids[0]
    if hash_step not in step_by_id[process_id]["requires"]:
        _fail("PROCESS_START must require ARTIFACT_HASH")
    for step in steps:
        if step["action"].startswith("UIA_") and process_id not in step["requires"]:
            _fail("UIA steps must require PROCESS_START")
    diagnostics = value.get("allowed_diagnostics")
    if (not isinstance(diagnostics, list) or
            len(diagnostics) != len(set(diagnostics)) or
            any(item not in DIAGNOSTICS for item in diagnostics)):
        _fail("invalid allowed diagnostics")

    template = _template_from_bound(value)
    if sha256(canonical(template)).hexdigest() != value["template_sha256"]:
        _fail("template hash mismatch")
    return value


def verify_plan_for_job(plan: dict[str, Any], *, job: dict[str, Any],
                        artifact_path: Path, package_path: Path,
                        supported_test_ids: set[str]) -> dict[str, Any]:
    artifact = artifact_path.resolve()
    if not artifact.is_file() or artifact_path.is_symlink():
        _fail("artifact is missing or linked")
    if _sha256_file(artifact) != plan["executable_sha256"]:
        _fail("local artifact does not match bound executable SHA")
    package = _inspect_package(package_path)
    if package["package_sha256"] != plan["package_sha256"]:
        _fail("local package does not match bound package SHA")
    if package["executable_sha256"] != plan["executable_sha256"]:
        _fail("package executable does not match bound executable SHA")
    if package["identity"] != plan["identity"]:
        _fail("package Identity or Version differs from plan")
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
    if job.get("package_sha256") != plan["package_sha256"]:
        _fail("job package SHA differs from plan")
    if job.get("identity") != plan["identity"]:
        _fail("job Identity or Version differs from plan")

    for step in plan["steps"]:
        if step["action"] == "ARTIFACT_HASH" and step["params"] != {}:
            _fail("local ARTIFACT_HASH does not accept parameters")
        if (step["action"] == "PROCESS_START" and
                step["params"] != {"observation_seconds": 5}):
            _fail("local PROCESS_START currently requires observation_seconds=5")
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
        "identity": dict(plan["identity"]),
    }


@dataclass
class BoundProductPlanPlanner:
    """Feed the required GitHub-authored action order into QASupervisor.

    Only action IDs already present in the local trusted catalog are emitted.
    This is intentionally not a shell-command planner.
    """
    bound_plan: dict[str, Any]
    supported_test_ids: set[str]

    def __post_init__(self) -> None:
        required = {
            step["action"] for step in self.bound_plan["steps"] if step["required"] is True
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
            step["step_id"]: step["action"] for step in self.bound_plan["steps"]
        }
        for step in self.bound_plan["steps"]:
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
