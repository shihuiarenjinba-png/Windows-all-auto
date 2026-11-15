# Windows local QA evidence return

This component extends the existing pull/checker path. It does not replace the
00/12/24/36/48 GitHub rotations, `local_handoff_pull.py`, or
`local_checker_queue.py`, and it never edits product source.

## Evidence-return E2E gate

`evidence_return_e2e_pass` is possible only when all of these are true for the same immutable
`request_id` and `source_sha`:

1. the test result is `TEST_PASS`;
2. required stdout, stderr, exit code, Windows Event Log, expectations and
   actual results were durably recorded (plus UIA actions and a privacy-reviewed
   screenshot for GUI tests);
3. the local manifest was written and read back successfully;
4. the sanitized envelope was written to the configured GitHub evidence branch;
5. GitHub content was downloaded again and its request ID, source SHA and
   `payload_sha256` matched.

This means only that the evidence-return pipeline completed end to end. It is
not a product E2E result. A successful `print("ok")` plus GitHub readback has:

```text
evidence_return_e2e_pass = true
product_e2e_pass = false
e2e_pass = false  # deprecated product-E2E compatibility field
release_ready = false
store_submission_allowed = false
user_product_approval = false
user_price_approval = false
```

This local evidence component has no authority to set `product_e2e_pass` true.
Its manifest records product-specific tests, physical GUI QA, package QA,
Identity, Version, artifact/package SHA correlation, and product regression as
unverified. A separate product authority must verify every product gate before
any future product-E2E promotion. Product E2E still would not imply Store
submission, release readiness, product approval, or price approval.

## Legacy `e2e_pass` consumer audit

Repository-wide consumers were classified before this change:

- `all_auto/local_qa_evidence.py`, its worker, schema, and tests previously used
  `e2e_pass` for evidence-return completion. They now use
  `evidence_return_e2e_pass`; their legacy field is retained as deprecated and
  always false.
- `ops/active_e2e_handoff.json` and its regression tests use `e2e_pass` for the
  broader physical/product handoff. They remain unchanged and fail-closed.
- `scripts/local_checker_queue.py` uses `e2e_pass` for the checker/product path,
  not the evidence-return transport. It remains unchanged and false.

No repository-wide product consumer is promoted from evidence return alone.

## Durable layout

The default root is `%LOCALAPPDATA%\WindowsAllAuto\QA-Evidence`:

```text
runs/<run-id>/state.json                 crash-recovery state
runs/<run-id>/journal.jsonl              fsync'd lifecycle journal
runs/<run-id>/stdout.log / stderr.log    bounded process output
runs/<run-id>/windows-event-log.xml      best-effort Application log
runs/<run-id>/uia-actions.jsonl          GUI driver action/result history
runs/<run-id>/screenshots/               local originals
runs/<run-id>/manifest.json              evidence-return and fail-closed product gates
runs/<run-id>/github-envelope.json       sanitized return payload
runs/<run-id>/analysis/windows-qa-analysis.json optional derived analysis
retry-queue/<run-id>.json                exponential-backoff retry state
github-acks/<run-id>.json                verified GitHub readback receipt
```

The worker applies a 30-day / 5 GiB default retention policy after retrying.
Only runs with a durable GitHub acknowledgement and no retry-queue entry can be
removed. Pending, failed, interrupted, unacknowledged, or malformed evidence is
never selected by automatic retention.

Every missing item is reported as `UNAVAILABLE`,
`UNAVAILABLE_PROCESS_RESTART`, or `UNAVAILABLE_PRIVACY_REVIEW`; it is never
silently omitted. Text is redacted before return. A screenshot stays local
unless the GUI driver/operator explicitly marks it privacy-reviewed and
shareable. A GUI test without a shareable screenshot cannot make
`evidence_return_e2e_pass` true. Even complete GUI evidence does not establish
`product_e2e_pass` without the remaining product gates.

## Trusted job and profile

The job is immutable handoff metadata. The profile is a local trusted file and
must never come from a downloaded artifact. This prevents a GitHub handoff or a
local LLM from choosing arbitrary commands.

Example job:

```json
{
  "request_id": "app-example-0001",
  "product_type": "APP",
  "source_repository": "owner/product",
  "source_branch": "codex/product-revision",
  "source_sha": "0000000000000000000000000000000000000000",
  "artifact_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "test_suite_version": "windows-local-v1",
  "github_actions_run_id": 123,
  "github_artifact_id": 456
}
```

Example local profile:

```json
{
  "allowed_executables": ["C:\\qa\\trusted\\run-app-qa.cmd"],
  "command": ["C:\\qa\\trusted\\run-app-qa.cmd", "--machine-json"],
  "cwd": "C:\\qa\\trusted",
  "timeout_seconds": 900,
  "expected": {"exit_code": 0},
  "gui_test": true
}
```

Run one job and immediately attempt queued returns:

```powershell
py -3 -m scripts.local_qa_evidence_worker `
  --state-root "$env:LOCALAPPDATA\WindowsAllAuto\QA-Evidence" `
  --job C:\qa\jobs\job.json --profile C:\qa\trusted\profile.json
```

Retry only:

```powershell
py -3 -m scripts.local_qa_evidence_worker `
  --state-root "$env:LOCALAPPDATA\WindowsAllAuto\QA-Evidence" --retry-only
```

Optional local Ollama analysis is documented in
[`OLLAMA_QA_ARCHITECTURE.md`](OLLAMA_QA_ARCHITECTURE.md). It reads only the
sanitized envelope and cannot change the authoritative test, evidence-return
E2E, or product E2E result.
It has no authority over evidence-return E2E, product E2E, release, Store,
Identity, Version, price, source SHA, or package SHA.

Registration is opt-in. The script refuses to replace an existing task and
uses the current user with limited privileges:

```powershell
pwsh -File scripts\register_local_qa_evidence_retry.ps1
pwsh -File scripts\local_qa_evidence_status.ps1
```

The retry task must not be registered until `gh auth status` succeeds and the
evidence branch/repository permissions have been reviewed. Raw logs and
screenshots must not be placed in public repositories manually.

## Fault injection

`tests/test_local_qa_evidence.py` covers normal completion, non-zero exit,
process start failure, timeout, transport outage, GitHub readback mismatch,
restart recovery, Event Log denial, missing GUI evidence, secret/PII redaction,
and a complete GUI evidence/readback path. These use synthetic programs and can
establish only evidence-return E2E; they do not establish a real product E2E
pass.

The manifest routes APP/GAME/GAME_3D back to the corresponding Factory, but the
current repositories expose no verified development-agent dispatch contract.
The status therefore remains `AGENT_DISPATCH_PENDING`; an uploaded evidence
file or Issue must not be described as an automatically executed repair.
