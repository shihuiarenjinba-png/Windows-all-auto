# Signal Sprint: local-only official Identity CAS worker

This is a **local Windows operator** command, not a GitHub Actions step.
Do not upload Partner Center evidence, tokens, PFX files, cookies or the raw
Provisioner result to GitHub. This worker does not build MSIX or certify E2E PASS.

## Pinned input

- E2E ledger: Windows-all-auto / codex/e2e-belt-connection-20261027 / ops/active_e2e_handoff.json
- Active product: GAME / signal-sprint; new_product_allowed=false
- Factory: shihuiarenjinba-png/AI-Game-Factory
- Factory branch: codex/game-signal-sprint-undo-20261027
- Immutable source_sha: c058cbf7fe38e02d929c67d047d717ff74bd522e
- request_id: game-signal-sprint-c058cbf7fe38e02d929c67d047d717ff74bd522e
- Provisioner-game restart-safe branch: codex/game-identity-idempotency-20261027 (Draft PR #9)
- Reviewed current Provisioner HEAD: 93eb34f32339f18fd05d3028f8ef0e76172ac077 (CI 40489763401 SUCCESS; docs-only successor to locally exercised 5c1db9820bac68c59cc7eb6ca5921e22a5bb3913)
- For this stacked recovery path use the reviewed PR #17 ledger with `--ledger-ref` and the *current* `--ledger-sha` from GitHub. The central PR #14 ledger remains the primary recovery index.

The integration ledger remains the default authority. A reviewed `codex/*`
ledger branch may be used only with both `--ledger-ref` and its exact current
`--ledger-sha`. The worker verifies that GitHub still reports that branch at
the supplied SHA, then reads the ledger by immutable commit. A moved branch is
`CONFLICT`; a non-default branch without a SHA is `HOLD`. This permits review
of a stacked Provisioner fix without silently bypassing the GitHub ledger.

## Windows local procedure

Use an authenticated GitHub CLI session with access to both repositories.
Review Partner Center Identity manually and save its authenticated operator
export only at
`%LOCALAPPDATA%\FactoryIdentityWorker\secure\<request_id>\official-identity.json`.
Never commit or upload this file. Required fields are defined by Provisioner-game
OfficialIdentityProvider; Store ID, Name, Publisher, Version, PFN and SID
must come from the authenticated account, not this document.

Check that C:\src\Repository-Provisioner-game is on the exact branch and SHA
above. From the Windows-all-auto checkout, run the **check-only** command:

~~~powershell
$ledgerSha = gh api repos/shihuiarenjinba-png/Windows-all-auto/git/ref/heads/codex/local-identity-qa-safety-20261027 --jq .object.sha
py -3 -m scripts.local_identity_return --ledger-ref "codex/local-identity-qa-safety-20261027" --ledger-sha "$ledgerSha" --provisioner-root "C:\src\Repository-Provisioner-game" --provisioner-branch "codex/game-identity-idempotency-20261027" --provisioner-sha "93eb34f32339f18fd05d3028f8ef0e76172ac077" --provisioner-result "C:\qa\signal-sprint\provisioner-live-result.json" --source-branch "codex/game-signal-sprint-undo-20261027" --source-sha "c058cbf7fe38e02d929c67d047d717ff74bd522e" --request-id "game-signal-sprint-c058cbf7fe38e02d929c67d047d717ff74bd522e"
~~~

When running inside a packaged desktop host, `%LOCALAPPDATA%` can resolve to a
long virtualized path. Use explicit short, dedicated paths such as
`--local-dir "C:\qa\signal-sprint\identity-return"` and
`--work-dir "C:\qa\signal-sprint\identity-work"`; the evidence must then be
exactly `<local-dir>\official-identity.json`. Do not place either path in a Git
checkout.

Even with missing evidence, check-only delegates an EXE build/inspection to the
pinned Provisioner and requires the bytes, SHA-256 and signature state recorded
in the ledger. It then checkpoints
`WAITING_OFFICIAL_IDENTITY / EXTERNAL_IDENTITY`. Repeating the same request
resumes that checkpoint without rebuilding the same EXE. A changed request,
source, package or Factory HEAD fails closed.

Present evidence is checked only for local JSON shape, immutable bindings and
an authenticated Partner Center URL. Check-only then returns
`READY_FOR_LOCAL_CAS_APPROVAL / IDENTITY_READY` with the explicit marker
`LOCAL_FORMAT_AND_BINDING_CHECKED_NOT_AUTHENTICITY_VERIFIED`. This is not proof
that Partner Center authenticity was independently verified.
Reconcile CONFLICT; never force-push the source branch.

Only after reviewing authenticated evidence and explicitly approving CAS,
rerun the same command with the two additional arguments:

~~~text
--apply --confirm-request-id "game-signal-sprint-c058cbf7fe38e02d929c67d047d717ff74bd522e"
~~~

The worker re-inspects the exact previously accepted local EXE through
Provisioner `--resume-result` without an unnecessary nondeterministic rebuild,
requiring the pinned SHA-256, byte count and signature state from the ledger. It rechecks the
Factory source HEAD, then invokes Provisioner --official-identity --apply.
Provisioner performs expectedHeadOid CAS on approved-identity.json.
The worker verifies the returned commit against the Factory HEAD.

Local-only outputs are `worker-state.json`, `provisioner-result.json` and
`identity-return-receipt.json` under the secure request directory. The latter omits Store ID,
operator account, evidence URL, tokens and cookies. Never upload the raw
result or evidence. Only safe metadata (request_id, source_sha,
factory_return_commit_sha, EXE SHA and status) may be added to the E2E
ledger after verification.

## After verified CAS

Create a separate codex/* Factory MSIX integration branch from the actual
returned commit; integrate reviewed AI-Game-Factory PR #11 there. Preserve
source_sha and use factory_head_sha for the later build commit. Require real
MakeAppx MSIX, manifest/Identity/package SHA checks, Windows-all-auto intake,
local pull, Windows-checker, GUI/install QA. Until all evidence exists,
e2e_pass=false. Store submission is a separate authorization.

GitHub-side MSIX QA backlog may be retained for 30 days. The local inbox
remains capped at 20 packages / 2 GiB; do not force downloads when full.

The central ledger now indexes the current Provisioner PR #9 for the next reviewed local check-only; the old PR #16 checkpoint remains historical. The stacked
`codex/game-identity-idempotency-20261027` recovery change must have green CI
and be explicitly pinned in either the central ledger or an immutable reviewed
`codex/*` ledger checkpoint before an apply run uses it. For the latter, first
read the current Windows-all-auto branch HEAD from GitHub and pass the same
value as `--ledger-sha`; do not reuse it after the branch moves.
That change permits a read-before-retry `EXISTING_VERIFIED` result after an
ambiguous successful CAS response; it does not weaken the original expected
HEAD gate for a missing Identity file.

## 2026-10-27 local check-only evidence

Draft PR #17 was exercised on local Windows against Provisioner-game Draft PR
#9 and the immutable Signal Sprint source. The exact prior EXE was re-inspected
at SHA-256 `e8517df8cd31a40e5ce72afdd4e6a4d63626fb99f7ff8a4fa3296ff8deef05f4`
(11,387,518 bytes, `NOTSIGNED`). With no official Identity file, the worker
reached `WAITING_OFFICIAL_IDENTITY / EXTERNAL_IDENTITY`; a second invocation
left the Provisioner result timestamp and hash unchanged. Factory HEAD remained
`c058cbf7fe38e02d929c67d047d717ff74bd522e` and approved Identity remained
absent. This is not an Identity verification, real MSIX, or E2E PASS.

## Current reviewed SHA checkpoint

The local check-only evidence above was collected using Provisioner `5c1db9820bac68c59cc7eb6ca5921e22a5bb3913`. The branch has since advanced to `93eb34f32339f18fd05d3028f8ef0e76172ac077` by a documentation-only commit, with Actions `40489763401` SUCCESS. This is **not** a new local run or an official Identity verification. The reviewed PR #17 ledger pins the current SHA for the next run; re-read the ledger HEAD immediately before use, and never apply CAS without authenticated Partner Center evidence and explicit approval.
