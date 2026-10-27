# Signal Sprint: local-only official Identity CAS worker (Draft PR #16)

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
- Provisioner-game safety branch: codex/game-msix-package-safety-20261027-1510
- Reviewed Provisioner HEAD: 66fc66b0e2a58dba2a9023f7e7fbbd6e5803d857 (verify latest ledger before running)

## Windows local procedure

Use an authenticated GitHub CLI session with access to both repositories.
Review Partner Center Identity manually and save its authenticated operator
export at C:\qa\signal-sprint\official-identity-private.json. Never commit
this file. Required fields are defined by Provisioner-game
OfficialIdentityProvider; Store ID, Name, Publisher, Version, PFN and SID
must come from the authenticated account, not this document.

Check that C:\src\Repository-Provisioner-game is on the exact branch and SHA
above. From the Windows-all-auto checkout, run the **check-only** command:

~~~powershell
py -3 -m scripts.local_identity_return --provisioner-root "C:\src\Repository-Provisioner-game" --provisioner-branch "codex/game-msix-package-safety-20261027-1510" --provisioner-sha "66fc66b0e2a58dba2a9023f7e7fbbd6e5803d857" --local-dir "C:\qa\signal-sprint\identity-return" --official-identity "C:\qa\signal-sprint\official-identity-private.json" --source-branch "codex/game-signal-sprint-undo-20261027" --source-sha "c058cbf7fe38e02d929c67d047d717ff74bd522e" --request-id "game-signal-sprint-c058cbf7fe38e02d929c67d047d717ff74bd522e"
~~~

Missing local evidence returns HOLD / OFFICIAL_IDENTITY_NOT_AVAILABLE.
Valid evidence returns READY_FOR_LOCAL_CAS_APPROVAL without mutation.
Reconcile CONFLICT; never force-push the source branch.

Only after reviewing authenticated evidence and explicitly approving CAS,
rerun the same command with the two additional arguments:

~~~text
--apply --confirm-request-id "game-signal-sprint-c058cbf7fe38e02d929c67d047d717ff74bd522e"
~~~

The worker first rebuilds and inspects the actual local EXE without
mutation, requiring the pinned SHA-256 from the ledger. It rechecks the
Factory source HEAD, then invokes Provisioner --official-identity --apply.
Provisioner performs expectedHeadOid CAS on approved-identity.json.
The worker verifies the returned commit against the Factory HEAD.

Local-only outputs are identity-return\provisioner-result.json and
identity-return\identity-return-receipt.json. The latter omits Store ID,
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
