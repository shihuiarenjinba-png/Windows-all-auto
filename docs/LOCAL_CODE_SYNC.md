# Local Factory source snapshot sync

Purpose: prove that exact Factory product source can be retrieved from GitHub onto
Windows for local Codex/QA work without modifying a development checkout.

The worker consumes a JSON object with `jobs` (or `items`) containing
`repository`, `branch`, `source_sha`, `slug`, and optional `request_id`.
It allowlists `shihuiarenjinba-png/*`, requires a `codex/*` branch, verifies the
remote branch HEAD equals the immutable 40-character SHA, then creates:

`<root>/<repository-name>/<first12(source_sha)>`

Each directory is a detached exact-SHA snapshot. Existing exact clean snapshots
are reused. Dirty, linked/junction, wrong-origin or wrong-SHA directories HOLD
instead of being reset. Product code is not executed.

Example:

```powershell
py -3 -m scripts.local_code_sync `
  --manifest "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\pre-identity-jobs.json" `
  --root "$env:LOCALAPPDATA\FactoryCodeMirror" `
  --receipt "$env:LOCALAPPDATA\FactoryCodeMirror\state\last-code-sync.json"
```

For the initial smoke test, `tests/fixtures/local_code_sync_targets.json` pins
three current real Factory products: Offline Notes Canary, Signal Sprint, and
Prism Route 3D. The Windows CI workflow downloads all three, verifies exact HEAD
SHA, then repeats the sync and requires idempotent reuse.

The optional Task Scheduler installer runs the same sync every 15 minutes with
`MultipleInstances IgnoreNew` and a 14-minute limit. It requires explicit
operator installation and existing `gh auth login`; it never stores GitHub
tokens in the manifest/receipt.

This worker is source retrieval only. It does not merge, edit source, run the
product, install packages, perform Identity CAS, build MSIX/GDK packages, or
submit to Microsoft Store. Codex should create a separate writable worktree or
working copy if edits are required; the managed snapshot is the immutable source
reference.

## Current target resolution (2026-11-26)

The current local-sync manifest is `tests/fixtures/local_code_sync_targets_20261126.json`.
It contains only two resolvable targets:

| Product | Source repository | Branch | Exact source SHA | Request |
|---|---|---|---|---|
| Signal Sprint | `shihuiarenjinba-png/AI-Game-Factory` | `codex/signal-sprint-frozen-source-ref-20261124` | `1a349faa41663c417c40710140a4d50c79b62b78` | `game-signal-sprint-1a349faa41663c417c40710140a4d50c79b62b78` |
| Prism Route 3D | `shihuiarenjinba-png/3d-game-factory` | `codex/prism-tower1-hud-clearance-fix-20261103` | `b03ce7b16c3f75c04fe20fdda224c45849eeba0d` | `3d-prism-route-3d-b03ce7b16c3f` |

Both remote branch refs were read directly and matched the pinned source SHA. The receipt now records, per product, `source_repository`, `source_branch`, `source_sha`, `remote_head_sha`, `local_head_sha`, and the explicit `three_sha_tuple`. All three values must be identical.

**Offline Notes Canary remains excluded**. Its Factory PR #14 is still titled as a research candidate and its body states `stage=research`, `slug=null`, and `active_product=null`; it has no immutable promoted product source, request ID, or EXE artifact. Its status is `HOLD_SOURCE_NOT_FIXED`, not a substitute target. The overall three-target operation remains HOLD until a valid source/request is fixed and every required physical user-PC receipt exists.

## User-PC execution sequence

Run these commands from a clean checkout of this PR's exact code (PR #23 HEAD `8fb30ea897e1263681732c709b71b21353a0ff95`). Keep the existing development checkout untouched; use a separate worktree if needed.

```powershell
$root = "$env:LOCALAPPDATA\FactoryCodeMirror"
$state = Join-Path $root "state"
New-Item -ItemType Directory -Force $state | Out-Null

# First exact-source retrieval; preserve this receipt separately.
py -3 -m scripts.local_code_sync --manifest tests/fixtures/local_code_sync_targets_20261126.json --root $root --receipt (Join-Path $state "first-run.json")
if ($LASTEXITCODE -ne 0) { throw "first local code sync HOLD" }

# Replay; every target must be REUSED_EXACT_SNAPSHOT.
py -3 -m scripts.local_code_sync --manifest tests/fixtures/local_code_sync_targets_20261126.json --root $root --receipt (Join-Path $state "second-run.json")
if ($LASTEXITCODE -ne 0) { throw "second local code sync HOLD" }

# Inspect second-run.json: status=PASS, snapshots=2, exact_three_sha_tuple_verified=true,
# idempotent_reuse_verified=true, and both product statuses=REUSED_EXACT_SNAPSHOT.

# Only after the first and second receipts pass, opt in to Task Scheduler.
.\scripts\register_local_code_sync.ps1 -Manifest tests/fixtures/local_code_sync_targets_20261126.json -Root $root -Receipt (Join-Path $state "task-run.json")

# After the scheduled run finishes with LastTaskResult=0, write the independent scheduler receipt.
.\scripts\verify_local_code_sync_task.ps1 -Receipt (Join-Path $state "task-run.json") -OutputReceipt (Join-Path $state "task-scheduler-receipt.json")
```

The verifier requires a successful `WindowsAllAuto-Factory-Code-Sync` Task Scheduler run correlated with the task receipt timestamps, exact source/remote/local three-SHA tuples, and replay reuse. Preserve `first-run.json`, `second-run.json`, `task-run.json`, and `task-scheduler-receipt.json` as separate evidence. Do not overwrite or replace an existing scheduled task; review it manually if it already exists.

A GitHub Actions Windows smoke is only `CLOUD_WINDOWS_EQUIVALENT_PASS`; it is not a physical user-PC receipt. No package install, product execution, Identity CAS, Store submission, certification, or publish is performed by this worker.
