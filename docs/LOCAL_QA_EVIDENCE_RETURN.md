# Windows local QA evidence return

This component extends the existing pull/checker path. It does not replace the
00/12/24/36/48 GitHub rotations, `local_handoff_pull.py`, or
`local_checker_queue.py`, and it never edits product source.

## Hard E2E gate

`E2E_PASS` is possible only when all of these are true for the same immutable
`request_id` and `source_sha`:

1. the test result is `TEST_PASS`;
2. required stdout, stderr, exit code, Windows Event Log, expectations and
   actual results were durably recorded (plus UIA actions and a privacy-reviewed
   screenshot for GUI tests);
3. the local manifest was written and read back successfully;
4. the sanitized envelope was written to the configured GitHub evidence branch;
5. GitHub content was downloaded again and its request ID, source SHA and
   `payload_sha256` matched.

Store submission remains false even after E2E pass. Package, Identity, pricing,
release review and user approval are separate gates.

## Durable layout

The default root is `%LOCALAPPDATA%\WindowsAllAuto\QA-Evidence`:

```text
runs/<run-id>/state.json                 crash-recovery state
runs/<run-id>/journal.jsonl              fsync'd lifecycle journal
runs/<run-id>/stdout.log / stderr.log    bounded process output
runs/<run-id>/windows-event-log.xml      best-effort Application log
runs/<run-id>/uia-actions.jsonl          GUI driver action/result history
runs/<run-id>/screenshots/               local originals
runs/<run-id>/manifest.json              final local result and E2E gate
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
shareable. A GUI test without a shareable screenshot cannot become E2E pass.

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
sanitized envelope and cannot change the authoritative test or E2E result.

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
and a complete GUI evidence/readback path. These use synthetic programs and do
not establish a real product E2E pass.

The manifest routes APP/GAME/GAME_3D back to the corresponding Factory, but the
current repositories expose no verified development-agent dispatch contract.
The status therefore remains `AGENT_DISPATCH_PENDING`; an uploaded evidence
file or Issue must not be described as an automatically executed repair.
