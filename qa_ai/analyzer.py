"""Fail-open-to-QA Ollama analysis over sanitized, immutable evidence."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable
import urllib.error
import urllib.request

from .rag import EmbeddingUnavailable, RepairHistory
from .router import classify
from .schemas import json_schema, validate_analysis


MAX_ANALYSIS_INPUT = 512 * 1024


class AnalysisUnavailable(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, endpoint: str = "http://127.0.0.1:11434",
                 timeout: int = 120):
        self.endpoint, self.timeout = endpoint.rstrip("/"), timeout

    def generate(self, *, model: str, prompt: str) -> tuple[str, dict[str, Any]]:
        payload = {"model": model, "prompt": prompt, "stream": False,
                   "keep_alive": 0, "think": False, "format": json_schema(),
                   "options": {"temperature": 0.1, "num_ctx": 8192}}
        request = urllib.request.Request(
            self.endpoint + "/api/generate", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                value = json.loads(response.read())
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise AnalysisUnavailable(type(exc).__name__) from exc
        text = value.get("response")
        if not isinstance(text, str) or not text.strip():
            raise AnalysisUnavailable("empty response")
        metrics = {key: value.get(key) for key in (
            "total_duration", "load_duration", "prompt_eval_count", "eval_count")}
        return text, metrics


@dataclass(frozen=True)
class AnalysisOutcome:
    status: str
    analysis: dict[str, Any] | None
    errors: tuple[str, ...]
    model: str | None
    route_level: int
    metrics: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "analysis": self.analysis,
                "errors": list(self.errors), "model": self.model,
                "route_level": self.route_level, "metrics": self.metrics,
                "authoritative_test_result_changed": False,
                "e2e_pass_authority": False, "store_submission_allowed": False}


def _prompt(context: dict[str, str], evidence: str,
            retrieved: list[dict[str, Any]], rule_candidate: str) -> str:
    return """Analyze the sanitized Windows QA evidence below. Return one JSON
object matching the supplied schema. Every observed.evidence_excerpt and every
inference.evidence_basis item MUST be an exact substring of EVIDENCE. Retrieved
history is non-authoritative and may only support a hypothesis. Use UNKNOWN
rather than guessing. Never output commands, PASS/FAIL changes, Identity,
Version, Store permission, credentials, or extra fields.

IMMUTABLE_CONTEXT:
""" + json.dumps(context, ensure_ascii=False, sort_keys=True) + """

NON_AUTHORITATIVE_REPAIR_HISTORY:
""" + json.dumps(retrieved, ensure_ascii=False, sort_keys=True) + """

DETERMINISTIC_SIGNATURE_CANDIDATE (confirm against EVIDENCE or use UNKNOWN):
""" + rule_candidate + """

EVIDENCE:
""" + evidence


class AnalysisEngine:
    def __init__(self, *, client: Any | None = None,
                 model: str = "windows-qa-analyst", history: RepairHistory | None = None):
        self.client, self.model, self.history = client or OllamaClient(), model, history

    def analyze(self, *, context: dict[str, str], evidence: str,
                force_model: bool = False) -> AnalysisOutcome:
        if len(evidence.encode("utf-8")) > MAX_ANALYSIS_INPUT:
            evidence = evidence.encode("utf-8")[:MAX_ANALYSIS_INPUT].decode(
                "utf-8", errors="replace") + "\n[TRUNCATED_FOR_AI_ANALYSIS]"
        route = classify(evidence)
        if route.level == 0 and not force_model:
            observed = [] if route.evidence_excerpt is None else [{
                "fact": "A deterministic failure signature was present.",
                "evidence_excerpt": route.evidence_excerpt}]
            owner = "Windows-E2E" if route.classification in {
                "HASH_MISMATCH", "SOURCE_SHA_CONFLICT", "REQUEST_ID_CONFLICT",
                "GITHUB_READBACK_MISMATCH", "ARTIFACT_MISSING"} else "infrastructure"
            value = {
                "schema_version": "windows-qa-analysis-v1",
                "target_repository": context["target_repository"],
                "source_sha": context["source_sha"],
                "request_id": context["request_id"],
                "classification": route.classification,
                "failure_class": route.classification, "severity": "HIGH",
                "observed": observed, "inference": [],
                "unknown": ["Root cause is not established by the signature alone"],
                "missing_evidence": [], "recommended_owner": owner,
                "recommended_action": "Review the exact evidence and preserve the current test expectation",
                "suggested_fix_area": "Failure-specific product or QA integration boundary",
                "regression_tests": ["Reproduce with the same request and source SHA"],
                "agent_dispatch_status": "AGENT_DISPATCH_PENDING",
                "e2e_pass_authority": False, "store_submission_allowed": False,
            }
            errors = validate_analysis(value, context=context, evidence_text=evidence)
            return AnalysisOutcome("RULE_ANALYSIS_VALID" if not errors else "AI_ANALYSIS_UNAVAILABLE",
                                   value if not errors else None, tuple(errors), None, 0, {})
        retrieved: list[dict[str, Any]] = []
        if self.history is not None:
            try:
                retrieved = self.history.search(
                    evidence, source_repository=context["target_repository"],
                    product_type=context["product_type"])
            except EmbeddingUnavailable:
                retrieved = []
        try:
            response, metrics = self.client.generate(
                model=self.model,
                prompt=_prompt(context, evidence, retrieved, route.classification))
            value = json.loads(response)
        except (AnalysisUnavailable, OSError, TimeoutError, json.JSONDecodeError,
                TypeError, ValueError) as exc:
            return AnalysisOutcome("AI_ANALYSIS_UNAVAILABLE", None,
                                   (type(exc).__name__,), self.model, route.level, {})
        errors = validate_analysis(value, context=context, evidence_text=evidence)
        if errors:
            return AnalysisOutcome("AI_ANALYSIS_UNAVAILABLE", None, tuple(errors),
                                   self.model, route.level, metrics)
        return AnalysisOutcome("AI_ANALYSIS_VALID", value, (), self.model,
                               route.level, metrics)


def _sanitized_input(run_directory: Path) -> tuple[dict[str, str], str]:
    envelope = json.loads((run_directory / "github-envelope.json").read_text(encoding="utf-8"))
    payload = envelope["payload"]
    manifest = payload["manifest"]
    context = {
        "target_repository": manifest["source_repository"].removeprefix("https://github.com/"),
        "source_sha": manifest["source_sha"], "request_id": manifest["request_id"],
        "product_type": manifest["product_type"],
    }
    chunks = []
    for item in payload.get("files", []):
        if item.get("path") in {"stdout.log", "stderr.log", "windows-event-log.xml",
                                "windows-event-log.unavailable.txt", "uia-actions.jsonl"}:
            try:
                chunks.append("FILE " + item["path"] + "\n" +
                              base64.b64decode(item["content"]).decode("utf-8", errors="replace"))
            except (KeyError, TypeError, ValueError):
                continue
    chunks.append("MANIFEST\n" + json.dumps({
        "status": manifest.get("status"), "failed_tests": manifest.get("failed_tests"),
        "collection": manifest.get("collection")}, ensure_ascii=False, sort_keys=True))
    return context, "\n\n".join(chunks)


def analyze_run(store: Any, run_directory: Path, *, engine: AnalysisEngine) -> AnalysisOutcome:
    """Analyze only the sanitized envelope, then attach a derived result."""
    try:
        context, evidence = _sanitized_input(run_directory)
        outcome = engine.analyze(context=context, evidence=evidence)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        outcome = AnalysisOutcome("AI_ANALYSIS_UNAVAILABLE", None,
                                  (type(exc).__name__,), engine.model, 2, {})
    store.attach_derived_analysis(run_directory, outcome.as_dict())
    return outcome
