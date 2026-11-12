"""Safety, failure-injection, and isolation tests for local Ollama analysis."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from all_auto.local_qa_evidence import EvidenceStore, process_retry_queue
from qa_ai.analyzer import (
    AnalysisEngine, AnalysisUnavailable, MAX_ANALYSIS_INPUT, analyze_run,
)
from qa_ai.rag import RepairHistory
from qa_ai.router import classify
from qa_ai.schemas import validate_analysis


SOURCE = "a" * 40
CONTEXT = {
    "target_repository": "owner/product", "source_sha": SOURCE,
    "request_id": "qa-ai-0001", "product_type": "APP",
}


def valid_analysis(evidence: str, *, classification: str = "UNKNOWN",
                   owner: str = "APP", excerpt: str | None = None) -> dict:
    observed = [] if excerpt is None else [{"fact": "Evidence was recorded.",
                                             "evidence_excerpt": excerpt}]
    return {
        "schema_version": "windows-qa-analysis-v1",
        "target_repository": CONTEXT["target_repository"],
        "source_sha": CONTEXT["source_sha"],
        "request_id": CONTEXT["request_id"],
        "classification": classification, "failure_class": classification,
        "severity": "MEDIUM", "observed": observed, "inference": [],
        "unknown": ["Root cause is not established"],
        "missing_evidence": ["Additional reproduction details"],
        "recommended_owner": owner,
        "recommended_action": "Review the preserved evidence",
        "suggested_fix_area": "Product or QA integration boundary",
        "regression_tests": ["Repeat the same sanitized test case"],
        "agent_dispatch_status": "AGENT_DISPATCH_PENDING",
        "e2e_pass_authority": False, "store_submission_allowed": False,
    }


class StaticClient:
    def __init__(self, value=None, error=None):
        self.value, self.error, self.prompt = value, error, None

    def generate(self, *, model, prompt):
        self.prompt = prompt
        if self.error:
            raise self.error
        return self.value, {"eval_count": 1}


class AckTransport:
    def put_and_readback(self, path):
        envelope = json.loads(path.read_text(encoding="utf-8"))
        return {"status": "GITHUB_READBACK_VERIFIED",
                "request_id": envelope["request_id"],
                "source_sha": envelope["source_sha"],
                "payload_sha256": envelope["payload_sha256"]}


class AnalysisSafetyTests(unittest.TestCase):
    def test_deterministic_router_handles_known_signatures(self):
        self.assertEqual(classify("TEST_TIMEOUT after 30 seconds").classification, "TIMEOUT")
        self.assertEqual(classify("hash verification mismatch").level, 0)
        self.assertEqual(classify("unstructured crash").classification, "UNKNOWN")

    def test_l0_artifact_failure_routes_to_windows_e2e_without_model(self):
        outcome = AnalysisEngine(client=StaticClient(error=AssertionError())).analyze(
            context=CONTEXT, evidence="artifact missing from workflow bundle")
        self.assertEqual(outcome.status, "RULE_ANALYSIS_VALID")
        self.assertEqual(outcome.analysis["recommended_owner"], "Windows-E2E")

    def test_model_missing_timeout_and_empty_response_are_non_authoritative(self):
        for error in (AnalysisUnavailable("model missing"), TimeoutError("late")):
            with self.subTest(error=type(error).__name__):
                outcome = AnalysisEngine(client=StaticClient(error=error)).analyze(
                    context=CONTEXT, evidence="ambiguous crash", force_model=True)
                self.assertEqual(outcome.status, "AI_ANALYSIS_UNAVAILABLE")
                self.assertIsNone(outcome.analysis)
                self.assertFalse(outcome.as_dict()["authoritative_test_result_changed"])

    def test_malformed_json_schema_violation_and_hallucination_are_rejected(self):
        malformed = AnalysisEngine(client=StaticClient("not-json"), model="test")
        self.assertEqual(malformed.analyze(context=CONTEXT, evidence="ambiguous",
                                           force_model=True).status,
                         "AI_ANALYSIS_UNAVAILABLE")
        extra = valid_analysis("ambiguous")
        extra["e2e_pass"] = True
        rejected = AnalysisEngine(client=StaticClient(json.dumps(extra))).analyze(
            context=CONTEXT, evidence="ambiguous", force_model=True)
        self.assertTrue(any("extra=" in item for item in rejected.errors))
        invented = valid_analysis("real evidence", excerpt="invented evidence")
        hallucinated = AnalysisEngine(client=StaticClient(json.dumps(invented))).analyze(
            context=CONTEXT, evidence="real evidence", force_model=True)
        self.assertTrue(any("not present" in item for item in hallucinated.errors))

    def test_giant_input_is_bounded_before_model_call(self):
        client = StaticClient(json.dumps(valid_analysis("A", excerpt="A")))
        outcome = AnalysisEngine(client=client).analyze(
            context=CONTEXT, evidence="A" * (MAX_ANALYSIS_INPUT + 4096),
            force_model=True)
        self.assertEqual(outcome.status, "AI_ANALYSIS_VALID")
        self.assertIn("[TRUNCATED_FOR_AI_ANALYSIS]", client.prompt)
        self.assertIn("DETERMINISTIC_SIGNATURE_CANDIDATE", client.prompt)
        self.assertLess(len(client.prompt), MAX_ANALYSIS_INPUT + 10000)

    def test_ai_cannot_claim_e2e_or_store_authority(self):
        value = valid_analysis("evidence")
        value["e2e_pass_authority"] = True
        value["store_submission_allowed"] = True
        errors = validate_analysis(value, context=CONTEXT, evidence_text="evidence")
        self.assertIn("AI cannot have E2E authority", errors)
        self.assertIn("AI cannot allow Store submission", errors)


class RepairHistoryTests(unittest.TestCase):
    def setUp(self):
        local_tmp = Path.cwd() / ".test-tmp"
        local_tmp.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=local_tmp)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.embed = lambda text: [1.0, 0.5]

    def record(self, **changes):
        value = {"failure_class": "TIMEOUT", "source_repository": "owner/product",
                 "product_type": "APP", "error_signature": "signature",
                 "symptoms": "window stopped responding", "root_cause": "verified cause",
                 "fix_summary": "verified fix", "fix_commit_sha": "b" * 40,
                 "regression_result": "PASS"}
        value.update(changes)
        return value

    def test_retrieval_rejects_failed_fix_and_excludes_cross_product_records(self):
        history = RepairHistory(self.root / "history.sqlite", embedder=self.embed)
        history.add_verified(self.record())
        with self.assertRaisesRegex(ValueError, "verified PASS"):
            history.add_verified(self.record(regression_result="FAIL",
                                             fix_commit_sha="c" * 40))
        history.add_verified(self.record(product_type="GAME", fix_commit_sha="d" * 40))
        found = history.search("timeout", source_repository="owner/product",
                               product_type="APP")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["fix_commit_sha"], "b" * 40)
        self.assertEqual(history.search("timeout", source_repository="other/repo",
                                        product_type="APP"), [])

    def test_embedding_indices_cannot_mix_models(self):
        path = self.root / "history.sqlite"
        RepairHistory(path, index_name="index-v1", embedding_model="nomic",
                      embedder=self.embed)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            RepairHistory(path, index_name="index-v1", embedding_model="other",
                          embedder=self.embed)

    def test_secret_like_history_is_rejected(self):
        history = RepairHistory(self.root / "history.sqlite", embedder=self.embed)
        with self.assertRaisesRegex(ValueError, "secret"):
            history.add_verified(self.record(symptoms="password=not-allowed"))

    def test_empty_history_does_not_load_embedding_model(self):
        def fail_if_called(_text):
            raise AssertionError("embedding should not run")
        history = RepairHistory(self.root / "history.sqlite", embedder=fail_if_called)
        self.assertEqual(history.search("unknown", source_repository="owner/product",
                                        product_type="APP"), [])


class EvidenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        local_tmp = Path.cwd() / ".test-tmp"
        local_tmp.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=local_tmp)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = EvidenceStore(self.root / "state")
        self.job = {"request_id": CONTEXT["request_id"], "product_type": "APP",
                    "source_repository": "owner/product", "source_branch": "codex/test",
                    "source_sha": SOURCE, "artifact_sha256": "b" * 64,
                    "test_suite_version": "qa-ai-v1"}

    @staticmethod
    def events(_start, _finish):
        return "<Events><Event>record</Event></Events>"

    def execute_run(self):
        command = [os.fspath(Path(os.sys.executable)), "-c",
                   "print('ambiguous application observation')"]
        return self.store.execute(self.job, command, cwd=self.root,
                                  timeout_seconds=5,
                                  event_log_collector=self.events)

    def test_analysis_is_derived_hashed_and_does_not_mutate_authoritative_files(self):
        result = self.execute_run()
        state_before = (result.run_directory / "state.json").read_bytes()
        manifest_before = (result.run_directory / "manifest.json").read_bytes()
        evidence = "ambiguous application observation"
        client = StaticClient(json.dumps(valid_analysis(evidence, excerpt=evidence)))
        outcome = analyze_run(self.store, result.run_directory,
                              engine=AnalysisEngine(client=client))
        self.assertEqual(outcome.status, "AI_ANALYSIS_VALID")
        self.assertEqual(state_before, (result.run_directory / "state.json").read_bytes())
        self.assertEqual(manifest_before, (result.run_directory / "manifest.json").read_bytes())
        derived = result.run_directory / "analysis" / "windows-qa-analysis.json"
        self.assertTrue(derived.is_file())
        envelope = json.loads((result.run_directory / "github-envelope.json").read_text())
        self.assertIn("analysis/windows-qa-analysis.json",
                      {item["path"] for item in envelope["payload"]["files"]})
        queued = json.loads(next(self.store.queue.glob("*.json")).read_text())
        self.assertEqual(queued["payload_sha256"], envelope["payload_sha256"])
        self.assertFalse(json.loads(manifest_before)["e2e_pass"])
        self.assertEqual(process_retry_queue(self.store, AckTransport())["verified"], 1)
        self.assertTrue(json.loads((result.run_directory / "manifest.json").read_text())["e2e_pass"])

    def test_ollama_failure_keeps_evidence_and_retry_queue(self):
        result = self.execute_run()
        outcome = analyze_run(
            self.store, result.run_directory,
            engine=AnalysisEngine(client=StaticClient(error=AnalysisUnavailable("offline"))))
        self.assertEqual(outcome.status, "AI_ANALYSIS_UNAVAILABLE")
        self.assertTrue((result.run_directory / "stdout.log").is_file())
        self.assertTrue((result.run_directory / "github-envelope.json").is_file())
        self.assertTrue(list(self.store.queue.glob("*.json")))
        manifest = json.loads((result.run_directory / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "TEST_PASS")
        self.assertFalse(manifest["e2e_pass"])

    def test_retry_worker_recovers_hash_after_interrupted_attachment(self):
        result = self.execute_run()
        queue_path = next(self.store.queue.glob("*.json"))
        queued = json.loads(queue_path.read_text())
        queued["payload_sha256"] = "0" * 64
        queue_path.write_text(json.dumps(queued), encoding="utf-8")
        self.assertEqual(process_retry_queue(self.store, AckTransport())["verified"], 1)
        events = (result.run_directory / "journal.jsonl").read_text()
        self.assertIn("RETRY_HASH_RECOVERED", events)


if __name__ == "__main__":
    unittest.main()
