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

## Process-scoped trusted UI Automation

Validated product plans may use these locally fixed implementations:

```text
UIA_FIND_WINDOW
UIA_FIND_CONTROL
UIA_INVOKE
UIA_READ_TEXT
UIA_SET_TEXT
```

The plan supplies only `action`, bounded `params`, and earlier `requires`
step IDs. It never supplies a command, executable path, PID, shell fallback,
or coordinate. `UIA_SET_TEXT` is limited to an exact named Edit control and at
most 4096 characters. Unknown fields, unknown control types, zero matches, and
multiple matches fail closed.

`scripts/trusted_product_qa_worker.py` starts only the already hash-verified
artifact, keeps its PID, and evaluates bound steps in dependency order. The
fixed C# helper verifies that PID still maps to the exact executable before
searching the process's single top-level window and descendants. Invoke, read,
and set operations use Windows UI Automation patterns; there is no desktop-wide
search, arbitrary click, or shell fallback. The product process is stopped in
a `finally` block.

The main `--product-qa-plan` path routes plans containing UIA actions through
this deterministic worker and copies its action journal into the durable
EvidenceStore before finalization. Missing screenshots or privacy review remain
explicitly `UNAVAILABLE`; GitHub readback may succeed while
`evidence_return_e2e_pass`, `product_e2e_pass`, `release_ready`, and
`store_submission_allowed` stay false.

AI-App-Factory PR #93 now carries the matching bounded `UIA_SET_TEXT`
schema/validator contract, so a verified Factory plan may emit it when tied to
a real Edit control.

## Received product plan: actual operation + Ollama supervision

For a bound product QA plan, the local machine is not a passive log reader.
The deterministic worker actually starts the exact received executable and
performs the plan's approved UI Automation actions against that exact process.

The authority split is:

```text
GitHub strong model
  -> authors product-specific required steps
  -> pre-authors optional read-only diagnostic steps
  -> binds source/package/EXE/Identity/Version

local trusted script
  -> verifies all immutable provenance
  -> starts exact product bytes
  -> performs required UIA actions
  -> records deterministic observations

Ollama local supervisor
  -> receives failure/history + only pre-authored optional diagnostics
  -> selects zero to three optional diagnostic step IDs
  -> never creates an action or parameter

local trusted script
  -> performs the selected diagnostic steps
  -> returns observations to EvidenceStore/GitHub
```

Optional diagnostics are executed only after a required step fails or is
blocked. The model can select only exact `step_id` values already present as
`required=false` in the verified bound plan and whose action also appears in
`allowed_diagnostics`. Runtime diagnostics are additionally limited to the
local read-only set:

```text
PROCESS_STATUS
UIA_FIND_WINDOW
UIA_FIND_CONTROL
UIA_READ_TEXT
```

`UIA_INVOKE` and `UIA_SET_TEXT` are never offered to Ollama as failure
diagnostics. They may still be required main-path actions when explicitly
authored by the GitHub QA plan.

Ollama unavailability, malformed output, hallucinated step IDs, cross-product
ownership, or unauthorized diagnostic selection cannot change deterministic
PASS/FAIL. A failed required step remains HOLD/FAIL even if all selected
diagnostics succeed. The diagnostics exist to collect better evidence for the
GitHub coding agent, not to override the gate.

The trusted GUI evidence entrypoint enables this advisory Ollama supervision
while the actual Windows operations remain in the deterministic executor.
