# Ollama local Windows QA supervisor

## Boundary

The supervisor automates test selection and evidence analysis, not source
repair. Ollama receives immutable job context, a description-only catalog, and
sanitized evidence. It returns a closed JSON object containing test IDs. It
cannot provide a command, executable, argument, path, script, patch, Git
operation, PASS/FAIL result, E2E state, release state, Store authority,
Identity, Version, price, or source/package hash.

```text
immutable intake
  -> strict planner JSON
  -> deterministic policy guard
  -> hash-pinned trusted catalog expansion
  -> deterministic executor
  -> durable EvidenceStore run
  -> optional non-authoritative analysis
  -> bounded next planner round
  -> GitHub evidence readback
  -> separate immutable ACK receipt
  -> advisory repair handoff (AGENT_DISPATCH_PENDING)
```

## Trusted catalog

`config/trusted-local-qa-tests-v1.json` is loaded only when its canonical JSON SHA-256
matches the constant reviewed in `all_auto/qa_supervisor.py`. A product
artifact, job document, or model response cannot replace the catalog path or
digest. The initial Phase 1 catalog contains:

- `ARTIFACT_HASH`: recompute the immutable artifact hash;
- `PROCESS_START`: start the exact artifact without model-provided arguments.

The executable identifier is mapped locally to the current trusted Python
runtime. Template placeholders are limited to the already validated artifact
path and artifact SHA. Unknown fields, absolute/traversing template paths,
shell metacharacters, symlinks, admin tests, destructive tests, and unsupported
GUI operations fail closed.

## Iteration and recovery

Defaults are five planner rounds, twelve tests, thirty minutes, twenty-four
resource units, one catalog-approved retry, and one identical-result retry.
Each round and execution is written atomically under `supervisor-state`.
Interrupted `RUNNING` states recover as `INTERRUPTED_RESTART`; no E2E, release,
or Store field is promoted.

Planner timeout, offline service, empty response, malformed JSON, extra fields,
unknown test IDs, executable text, or product-lane conflict becomes
`AI_PLANNER_UNAVAILABLE` or `POLICY_VIOLATION`. Existing evidence and retry
queue entries remain intact.

## Evidence and acknowledgement

The evidence envelope remains the immutable pre-upload snapshot and therefore
records `github_return=QUEUED`. After GitHub evidence readback and
request/source/payload correlation, the transport writes and reads back a
separate `local-qa-github-ack-v1` receipt under `ops/local-qa-acks/`.

The receipt can assert `evidence_return_e2e_pass=true` only when the
deterministic test passed and evidence collection/persistence were complete.
It always records these fields false:

```text
product_e2e_pass
e2e_pass
release_ready
store_submission_allowed
```

## Repair handoff

The local handoff includes immutable source/request/artifact hashes, failed
test IDs, deterministic observations, analysis classification when valid,
missing evidence, recommended owner, and allowlisted regression IDs. It has
`source_edit_authority=false`, `AGENT_DISPATCH_PENDING`, and
`retest_requires_new_source_sha=true`. GitHub-side coding automation remains a
separate authority.

Phase 1 uses only a synthetic artifact. Phase 2 requires an explicitly selected
stable real APP artifact and privacy-reviewed GUI/package policy. No product,
Identity, Version, package, Store, or release claim is implied by Phase 1.
