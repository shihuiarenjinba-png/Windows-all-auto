# GitHub-origin Prism Route 3D Identity reuse — local-only gate

This branch is stacked on PR #24. **Prism Route 3D already exists in Partner Center according to the user's manual screen observation. Do not create it again.** The manual reference is not automated capture evidence.

## What this implements

`scripts/github_partner_center_handoff.py` validates a **clean, exact-HEAD local checkout** of the central GitHub ledger against the live remote branch. It hashes the unique PRE_IDENTITY job, EXE SHA, Factory build HEAD, identity return target and creation-disabled flag into a queue digest. It rechecks the local immutable source snapshot and attaches:

- `job_origin=GITHUB_PRE_IDENTITY_QUEUE`
- `central_repository`, `central_branch`, `central_head_sha`
- `queue_job_digest`, `request_id`, `source_repository`, `source_branch`, `source_sha`
- `source_snapshot_path`, `source_snapshot_head`, `identity_return_target`

It does **not** control Edge, read cookies, create products, invoke CAS, upload packages, or submit to Store. A manual UI launch without the exact GitHub fields is **MANUAL_UI_TRIGGER_ONLY**, never GITHUB_TO_LOCAL_ROTATION_PASS.

## Physical Windows procedure

Use an independent checkout for central ledger, an independent PR #25 checkout for this worker, and immutable FactoryCodeMirror snapshots from the hardened PR #23 worker. The central checkout must have the exact HTTPS origin and be clean, with its HEAD matching the current remote `codex/e2e-belt-connection-20261027` branch.

From the PR #25 checkout:

```powershell
py -3 -m scripts.github_partner_center_handoff prepare `
  --central-checkout "C:\path\to\independent-central-checkout" `
  --sync-receipt "$env:LOCALAPPDATA\FactoryCodeMirror\state\last-code-sync.json" `
  --snapshot-root "$env:LOCALAPPDATA\FactoryCodeMirror" `
  --output "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\3d-prism-route-3d-15fdcb52e46e\github-operator-job.json"
```

**Existing-product path only:** In the already authenticated Partner Center Overview, search the exact name `Prism Route 3D`. Require exactly one result. Open that product, select **View product identity**, and capture all seven fields. The capture JSON uses the same schema as PR #24, with `creation_status=REUSED_EXISTING`, `overview_exact_match_count=1`, and `identity_details_observed=true`. Never click `+` or `Reserve product name` for this existing product. If Overview shows zero or multiple exact matches, HOLD; do not attempt another creation.

Then validate with the seven-field user-observed manual oracle:

```powershell
py -3 -m scripts.github_partner_center_handoff validate `
  --central-checkout "C:\path\to\independent-central-checkout" `
  --snapshot-root "$env:LOCALAPPDATA\FactoryCodeMirror" `
  --job "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\3d-prism-route-3d-15fdcb52e46e\github-operator-job.json" `
  --capture "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\3d-prism-route-3d-15fdcb52e46e\captured-identity.json" `
  --manual-reference "tests\fixtures\prism_route_3d_manual_reference.json" `
  --output "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\3d-prism-route-3d-15fdcb52e46e\validated-github-capture.json"
```

This only establishes **schema-correlated, locally attested capture matching the manual reference**. Browser capture PASS still requires actual independent UI execution evidence; the script itself does not create that evidence. `IDENTITY_ROUTED` requires the existing scheduler/Provisioner to consume a sanitized payload through its single-writer path. `CAS_READY` is not CAS applied: a request-specific explicit approval remains mandatory.

## Hold policy

Reject a dirty/linked central checkout, remote HEAD drift, missing source snapshot, mismatched source SHA, altered queue digest, unexpected identity return target, duplicate or cross-product request, any new Prism creation attempt, missing UI evidence, mismatched manual reference, duplicate JSON keys, or unexpected secret fields. Never store passwords, cookies, MFA material, tokens, raw HTML, or browser session data in receipts or GitHub. All private receipts are create-only and idempotent.

**Current real-world state:** The user manually observed the existing product's Identity values. Physical code sync receipt, automated browser capture, Identity route, CAS and package have not been independently verified here. CI contract tests cannot upgrade those gates to PASS.

For a future **new** APP product such as Focus Session Desk, creation is only permitted after its own immutable PRE_IDENTITY_READY request exists. That separate path must explicitly click **Reserve product name** after availability succeeds, wait for confirmation, re-search Overview on timeout before any retry, and refuse automatic alternative names. This Prism existing-product path must never be reused as a creation shortcut.

## Downstream compatibility gap discovered

At the inspected 2026-10-28 code heads, `scripts/local_identity_scheduler.py` accepts only `STORE_KNOWN_GOOD`, `GAME_SIGNAL_SPRINT`, and `APP_CANARY` job kinds, and delegates CAS only for Signal Sprint. It **does not yet route GAME_3D**. Do not report IDENTITY_ROUTED or CAS_READY from this new local receipt.

`Repository-Provisioner-3D/package_identity_provisioner.py` currently requires an operator evidence schema containing `authenticated_account`, `official_evidence_url`, `verified_at` and `version`, in addition to Identity fields. Those are **not** supplied by the seven-field Product Identity capture. Version must remain a separate explicit approval gate; never synthesize it or silently mix it into Identity capture. The 3D Provisioner owner must reconcile this contract before the single-writer return can proceed.

Until that downstream adapter is reviewed and the separate version/package approval exists, the result of this PR is only a locally verifiable **GitHub-origin + schema/manual-reference correlation gate**, not end-to-end Identity routing.

## 2026-10-28 source-branch drift detected

A later read of Factory PR #13 found its source branch HEAD at `11417b75636ee18816028ffd5221884c4c9a9836`, **one commit after** the pinned PRE_IDENTITY source SHA `15fdcb52e46e35e6de8e87c55af99719c21e09b9`. The new commit adds `products/prism-route-3d/store/approved-identity.json`, which includes the manually observed Store values and claims an Identity return. The GitHub Factory CI for the new HEAD succeeded, but that is **not** independent local UI capture or explicit CAS approval evidence.

Consequently the hardened exact-source sync must return **HOLD_REMOTE_HEAD_CONFLICT** against the original source branch pin. Do not silently update `source_sha`, weaken remote-HEAD checks, reset the Factory branch, or overwrite the Identity file. A separate, reviewed reconciliation must distinguish immutable source SHA from the observed post-Identity commit, confirm the request-scoped CAS approval/receipt, and verify any local capture evidence. Until then, no Identity-route or E2E PASS.
