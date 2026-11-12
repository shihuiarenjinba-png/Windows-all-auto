# Ollama Windows QA analysis

## Authority boundary

Ollama is a local, optional, derived-analysis service. The Windows runner,
durable evidence store, GitHub return/readback check, and existing E2E gate are
authoritative. An AI response cannot change `TEST_PASS`, `TEST_FAIL`,
`e2e_pass`, Store submission permission, Identity, Version, price, source code,
or the trusted command/profile.

If Ollama is missing, times out, returns empty or malformed JSON, violates the
schema, invents an evidence excerpt, or cannot embed a query, the status is
`AI_ANALYSIS_UNAVAILABLE`. Evidence return and ordinary QA continue. This is a
fail-open-to-QA policy, not a fail-open-to-release policy.

## Data flow

```text
trusted local profile -> Windows test -> raw durable evidence (local only)
                                      -> sanitized GitHub envelope
                                      -> L0 deterministic router
                                      -> optional isolated RAG lookup
                                      -> Ollama strict JSON analysis
                                      -> schema/evidence validation
                                      -> derived analysis file
                                      -> rebuilt hashed envelope
                                      -> GitHub return + readback gate
```

The analyzer reads only `github-envelope.json`; it never reads raw local logs
directly. `analysis/windows-qa-analysis.json` is redacted, size-bounded, and
included in the returned envelope hash. Attaching it does not modify
`state.json` or `manifest.json`. A crash between envelope and retry-queue
updates is recovered by validating the envelope's canonical payload hash before
transmission.

## L0/L2 routing

`qa_ai/router.py` classifies high-signal signatures such as timeout, process
start failure, hash/source/request conflicts, missing artifacts, Event Log
unavailability, and GitHub readback mismatch without loading an LLM. Ambiguous
UI, runtime, package, and unknown failures go to L2 only when AI analysis is
enabled. L0 and L2 both produce the same strict derived schema.

The dedicated model is created from `ollama/Modelfile.qa`:

```powershell
ollama create windows-qa-analyst -f ollama\Modelfile.qa
```

The worker is opt-in:

```powershell
py -3 -m scripts.local_qa_evidence_worker `
  --state-root "$env:LOCALAPPDATA\WindowsAllAuto\QA-Evidence" `
  --job C:\qa\jobs\job.json --profile C:\qa\trusted\profile.json `
  --enable-ai-analysis --ai-model windows-qa-analyst
```

## Strict output validation

`schemas/windows-qa-analysis-v1.schema.json` is closed to extra fields. The
runtime additionally checks immutable repository/request/source correlation and
requires every observed excerpt and every inference basis to be an exact
substring of the sanitized evidence. Dispatch remains
`AGENT_DISPATCH_PENDING`; output is advisory only.

## Repair-history RAG

`qa_ai/rag.py` stores only explicit repair records with a 40-hex fix commit and
a regression result. Retrieval requires the same source repository, the same
product type, the same named index and embedding model, and `PASS` regression
status. Cross-product records and failed/stale fixes are excluded. Embedding
failure returns zero history rather than blocking QA.

After a fix commit has actually passed regression testing, a trusted local
record can be added with `python -m scripts.qa_repair_history --db <path>
--record <json>`. Non-PASS records, invalid commit SHAs, extra/missing fields,
and secret-like content are rejected before embedding.

The baseline embedding model is `nomic-embed-text:latest`. Embedding model
changes require a new `index_name`; mixing vectors in an existing index is
rejected. Retrieved history is labeled non-authoritative and can support only a
hypothesis, never an observed fact.

An integration probe using the installed `nomic-embed-text:latest` inserted one
synthetic regression-verified repair, retrieved it for the same repository and
product type, and returned zero records for a different repository/product.
This proves the local embedding/search path, but not the quality of retrieval
over a production repair corpus.

## Resource and privacy controls

- one Ollama model is invoked at a time and each request uses `keep_alive: 0`;
- analysis input is capped at 512 KiB and output is capped before attachment;
- raw logs remain local; only the already-redacted envelope is analyzed;
- repair records with secret-like strings are rejected;
- no generated command is executed and no AI output selects an executable;
- the model service binds to loopback by default.

## Fault injection

`tests/test_qa_ai.py` covers missing model/service, timeout, malformed JSON,
schema violations, invented excerpts, giant logs, E2E/Store authority claims,
embedding-index mismatch, stale and cross-product history, secret rejection,
Ollama failure after evidence capture, immutable authoritative files, and
interrupted retry-hash recovery. The pre-existing normal/crash/start-failure/
timeout/network/restart tests remain in `tests/test_local_qa_evidence.py`.
