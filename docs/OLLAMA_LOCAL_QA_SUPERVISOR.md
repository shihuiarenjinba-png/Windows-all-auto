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

Each catalog item can also declare `requires_test_passes`. The dependency graph
is hash-pinned with the rest of the catalog, rejects missing/self/cyclic
dependencies, and is enforced deterministically by the policy guard. A dependent
test may run only after every prerequisite has already completed as
`TEST_PASS` in a previous execution. Prerequisites and dependents are not
trusted merely because the model selected them in the same round.

The policy guard also recomputes the current artifact SHA-256 before authorizing
every planner round. If the artifact differs from the immutable
`job.artifact_sha256`, execution stops before any dependent process is started.
The initial dependency is:

```text
ARTIFACT_HASH TEST_PASS
        ↓
PROCESS_START
```

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

When a product test fails after its evidence and ACK were returned, the
supervisor records `evidence_return_status=GITHUB_READBACK_VERIFIED` separately
while retaining `evidence_return_e2e_pass=false`. It returns the durable repair
handoff under `ops/local-qa-repairs/` and independently reads back the
request/source/artifact/repair hashes. The repair request still has
`source_edit_authority=false`; only a separate GitHub-side coding agent may
change product source.

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

## Bound package intake

`--product-qa-plan` also requires `--package`. Before any trusted action is
authorized, local Windows independently re-hashes the package, parses its
untrusted `AppxManifest.xml`, re-hashes the manifest-selected executable member,
and compares package SHA, executable SHA, Identity, Version, repository, source
SHA, slug, product type, template SHA, and authority flags with both the bound
plan and immutable job. A mismatch is `PRODUCT_QA_PLAN_HOLD`.
