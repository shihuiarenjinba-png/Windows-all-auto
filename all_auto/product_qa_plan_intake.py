"""Fail-closed intake for GitHub-generated final product QA plans."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

PLAN_SCHEMA = "windows-product-qa-plan-v1"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA64 = re.compile(r"^[0-9a-f]{64}$")
BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
SLUG = re.compile(r"^[a-z][a-z0-9-]{3,39}$")
STEP_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
TEST_ID = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
FORBIDDEN_TEXT = re.compile(
    r"(?i)(powershell|pwsh|cmd\.exe|\bgit\s+(?:add|commit|push|merge|reset)|"
    r"\b(?:curl|wget)\s|(?:^|\s)(?:python|py)\.exe\s|[;&|])"
)
TOP_KEYS = {
    "schema_version", "product", "intent", "steps",
    "allowed_diagnostics", "success_criteria",
}
STEP_KEYS = {
    "step_id", "test_id", "required", "requires", "purpose",
    "parameters", "evidence", "on_fail",
}
PARAM_KEYS = {
    "target_name", "expected_text", "expected_state", "file_role",
    "observation_seconds", "locale", "dpi_percent",
}


class ProductQAPlanIntakeError(ValueError):
    pass


def _hold(reason: str) -> None:
    raise ProductQAPlanIntakeError("PRODUCT_QA_PLAN_INTAKE_HOLD: " + reason)


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        _hold(field + " is invalid")
    if FORBIDDEN_TEXT.search(value):
        _hold(field + " contains command-like text")
    return value


def validate_plan(value: Any, *, slug: str, kind: str) -> None:
    if not isinstance(value, dict) or set(value) != TOP_KEYS:
        _hold("plan fields are invalid")
    if value.get("schema_version") != PLAN_SCHEMA:
        _hold("plan schema mismatch")
    product = value.get("product")
    if (not isinstance(product, dict) or set(product) != {"slug", "kind"} or
            product.get("slug") != slug or product.get("kind") != kind):
        _hold("plan product binding mismatch")
    _text(value.get("intent"), "intent", 1000)
    steps = value.get("steps")
    if not isinstance(steps, list) or not 2 <= len(steps) <= 24:
        _hold("plan step count is invalid")
    seen: set[str] = set()
    hash_step: str | None = None
    process_start: dict[str, Any] | None = None
    for step in steps:
        if not isinstance(step, dict) or set(step) != STEP_KEYS:
            _hold("step fields are invalid")
        step_id = step.get("step_id")
        test_id = step.get("test_id")
        if not isinstance(step_id, str) or not STEP_ID.fullmatch(step_id) or step_id in seen:
            _hold("step_id is invalid")
        if not isinstance(test_id, str) or not TEST_ID.fullmatch(test_id):
            _hold("test_id is invalid")
        if type(step.get("required")) is not bool:
            _hold("required flag is invalid")
        requires = step.get("requires")
        if (not isinstance(requires, list) or
                any(not isinstance(x, str) or x not in seen for x in requires) or
                len(requires) != len(set(requires))):
            _hold("step dependency is invalid")
        _text(step.get("purpose"), "purpose", 800)
        params = step.get("parameters")
        if not isinstance(params, dict) or set(params) - PARAM_KEYS:
            _hold("parameters are invalid")
        for key, item in params.items():
            if key in {"observation_seconds", "dpi_percent"}:
                if type(item) is not int:
                    _hold("numeric parameter is invalid")
                if key == "observation_seconds" and not 0 <= item <= 120:
                    _hold("observation_seconds out of range")
                if key == "dpi_percent" and item not in {100,125,150,175,200}:
                    _hold("dpi_percent is invalid")
            else:
                _text(item, "parameter", 200)
                if key == "locale" and item not in {"ja-JP","en-US"}:
                    _hold("locale is invalid")
        evidence = step.get("evidence")
        if (not isinstance(evidence, list) or not evidence or len(evidence) > 12 or
                any(not isinstance(x, str) or not x.strip() or len(x) > 80
                    or FORBIDDEN_TEXT.search(x) for x in evidence)):
            _hold("evidence declaration is invalid")
        if step.get("on_fail") not in {"STOP_AND_RETURN","CONTINUE_DIAGNOSTICS"}:
            _hold("on_fail is invalid")
        if test_id == "ARTIFACT_HASH":
            if hash_step is not None or step.get("required") is not True:
                _hold("ARTIFACT_HASH binding is invalid")
            hash_step = step_id
        if test_id == "PROCESS_START":
            if process_start is not None or step.get("required") is not True:
                _hold("PROCESS_START binding is invalid")
            process_start = step
        seen.add(step_id)
    if steps[0].get("test_id") != "ARTIFACT_HASH" or hash_step is None:
        _hold("ARTIFACT_HASH must be the first required step")
    if process_start is None or hash_step not in process_start.get("requires", []):
        _hold("PROCESS_START must depend on ARTIFACT_HASH")
    diagnostics = value.get("allowed_diagnostics")
    if (not isinstance(diagnostics, list) or len(diagnostics)>16 or
            len(diagnostics)!=len(set(diagnostics)) or
            any(not isinstance(x,str) or not TEST_ID.fullmatch(x) for x in diagnostics)):
        _hold("allowed_diagnostics are invalid")
    criteria = value.get("success_criteria")
    if (not isinstance(criteria,list) or not 1<=len(criteria)<=12 or
            any(not isinstance(x,str) or not x.strip() or len(x)>240
                or FORBIDDEN_TEXT.search(x) for x in criteria)):
        _hold("success_criteria are invalid")


@dataclass(frozen=True)
class AcceptedProductQAPlan:
    source_repository: str
    source_sha: str
    source_branch: str
    product_type: str
    slug: str
    package_sha256: str
    executable_sha256: str
    qa_plan_sha256: str
    plan: dict[str, Any]


def load_handoff_bundle(bundle: Path) -> AcceptedProductQAPlan:
    if bundle.is_symlink() or not bundle.is_dir():
        _hold("bundle directory is invalid")
    handoff_path = bundle / "handoff.json"
    plan_path = bundle / "qa-plan.json"
    package_path = bundle / "package.msix"
    for path in (handoff_path, plan_path, package_path):
        if path.is_symlink() or not path.is_file():
            _hold("required handoff file is missing or linked")
    try:
        handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductQAPlanIntakeError(
            "PRODUCT_QA_PLAN_INTAKE_HOLD: invalid handoff JSON"
        ) from exc

    required = {
        "schema_version","source_repository","source_sha","source_branch","type","slug",
        "package","status","package_sha256","package_bytes","executable_sha256",
        "identity","qa_plan","qa_plan_schema","qa_plan_sha256",
    }
    if not isinstance(handoff, dict) or set(handoff) != required:
        _hold("handoff fields are invalid")
    if handoff.get("schema_version") != 1 or handoff.get("status") != "QA_UNSIGNED":
        _hold("handoff state is invalid")
    source_sha = handoff.get("source_sha")
    source_branch = handoff.get("source_branch")
    package_sha = handoff.get("package_sha256")
    exe_sha = handoff.get("executable_sha256")
    plan_sha = handoff.get("qa_plan_sha256")
    if not isinstance(source_sha,str) or not SHA40.fullmatch(source_sha):
        _hold("source SHA is invalid")
    if (not isinstance(source_branch,str) or not BRANCH.fullmatch(source_branch) or
            source_branch.startswith("/") or source_branch.endswith("/") or
            ".." in source_branch):
        _hold("source branch is invalid")
    for name,value in (
        ("package SHA",package_sha),("executable SHA",exe_sha),("QA plan SHA",plan_sha)
    ):
        if not isinstance(value,str) or not SHA64.fullmatch(value):
            _hold(name+" is invalid")
    if handoff.get("package")!="package.msix" or handoff.get("qa_plan")!="qa-plan.json":
        _hold("handoff filenames are invalid")
    if handoff.get("qa_plan_schema") != PLAN_SCHEMA:
        _hold("handoff QA plan schema mismatch")
    slug=handoff.get("slug")
    kind=handoff.get("type")
    if not isinstance(slug,str) or not SLUG.fullmatch(slug) or kind not in {"app","game"}:
        _hold("product identity binding is invalid")
    validate_plan(plan,slug=slug,kind=kind)
    actual_plan_sha=sha256(canonical(plan)).hexdigest()
    if actual_plan_sha != plan_sha:
        _hold("QA plan hash mismatch")
    digest=sha256()
    with package_path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            digest.update(block)
    if digest.hexdigest()!=package_sha:
        _hold("package hash mismatch")
    source_repository=handoff.get("source_repository")
    if (not isinstance(source_repository,str) or
            not source_repository.startswith("https://github.com/")):
        _hold("source repository is invalid")
    return AcceptedProductQAPlan(
        source_repository=source_repository,
        source_sha=source_sha,
        source_branch=source_branch,
        product_type="APP" if kind=="app" else "GAME",
        slug=slug,
        package_sha256=package_sha,
        executable_sha256=exe_sha,
        qa_plan_sha256=plan_sha,
        plan=plan,
    )
