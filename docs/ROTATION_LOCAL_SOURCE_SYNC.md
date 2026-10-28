# Rotation PRE_IDENTITY → local source sync (Draft)

This bridge reads the **36-minute writer's** central ledger, validates the
independent APP (up to five) and real 3D PRE_IDENTITY jobs through
`rotation_pre_identity_intake.project`, and emits a manifest for the existing
`local_code_sync.py` worker. It does not change the central ledger.

## Local Windows procedure

Use a reviewed isolated checkout of this Draft PR, not a mutable development
checkout. Confirm `gh auth status`, `git --version`, and `py -3 --version`.

```powershell
$root = Join-Path $env:LOCALAPPDATA "FactoryCodeMirror"
$manifest = Join-Path $root "state\rotation-source-targets.json"
$receipt = Join-Path $root "state\rotation-source-receipt.json"
New-Item -ItemType Directory -Force (Join-Path $root "state") | Out-Null

py -3 -m scripts.rotation_source_sync_plan --ledger ops/active_e2e_handoff.json --check-only
py -3 -m scripts.rotation_source_sync_plan --ledger ops/active_e2e_handoff.json --manifest $manifest
# Run only when the plan has at least one eligible job:
py -3 -m scripts.local_code_sync --manifest $manifest --root $root --receipt $receipt
```

A job whose observed branch HEAD differs from its immutable source SHA is
**excluded** and reported as `HOLD_SOURCE_BRANCH_HEAD_DRIFT`. Other independent
APP jobs remain eligible. `local_code_sync` must still verify each live remote
branch HEAD before cloning or reusing a snapshot. The plan is not a substitute
for that check. A pre-existing manifest with different content is never
overwritten; choose a new reviewed manifest path after a cohort change.

The generated `rotation_intake_digest` is only a projection digest. It is
**not** the historical `queue_job_digest` required to prove
`GITHUB_PRE_IDENTITY_QUEUE` provenance. The local operator must independently
verify the original central queue HEAD, digest, source snapshot HEAD and exact
request/return target before any Partner Center UI work.

## Current Prism Route 3D hold

Pinned source SHA: `15fdcb52e46e35e6de8e87c55af99719c21e09b9`.
The observed source branch advanced by one Identity-file commit to
`11417b75636ee18816028ffd5221884c4c9a9836`.
Do not silently repin the source SHA, reclassify the packaging type, treat the
Identity file as an approved CAS receipt, or bypass remote HEAD checks.
Prism's existing Partner Center product must be reused; no duplicate creation.
Manual seven-field Identity reference is not automated capture evidence.

`LOCAL_CODE_SYNC_PASS` requires an actual user-PC receipt, matching checked-out
`git rev-parse HEAD` for each eligible snapshot, and an idempotent rerun.
Only after those checks may the separate local Task Scheduler registration be
considered. Store submission, package upload, CAS, installation, and GUI QA
are outside this bridge.
