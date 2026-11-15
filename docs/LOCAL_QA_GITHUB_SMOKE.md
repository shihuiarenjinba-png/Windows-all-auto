# Local Windows ↔ GitHub evidence smoke

This smoke test proves the local QA evidence transport on a real Windows PC without
using a real product package or Store operation.

It is intentionally stacked on the evidence/product E2E split. Passing this smoke
means only:

```text
local Windows synthetic test
  -> durable raw evidence
  -> sanitization
  -> GitHub evidence branch write
  -> GitHub independent readback
  -> immutable request/source/payload correlation
  -> evidence_return_e2e_pass = true
```

It never proves product E2E, release readiness, Store readiness, user product
approval, or user price approval.

## What the script verifies

`scripts/local_qa_github_smoke.ps1` performs these checks:

1. Windows, `git`, `gh`, `py`, and authenticated GitHub access exist.
2. The working tree is clean.
3. The local branch HEAD exactly equals the corresponding GitHub branch HEAD.
4. The configured evidence branch is separate and uses the
   `codex/local-qa-evidence-*` namespace.
5. A synthetic trusted local test is executed by the existing
   `local_qa_evidence_worker`.
6. Raw local stdout contains a deliberately fake token-shaped marker.
7. Only the sanitized evidence envelope is written to GitHub.
8. GitHub readback verifies request ID, source SHA, and payload hash.
9. A second independent `gh api` fetch reads the remote evidence again.
10. The fake marker is present locally but absent remotely, with a redaction marker
    present in the returned evidence.
11. The retry queue entry is removed only after a durable GitHub acknowledgement.
12. The final local manifest has:

```text
TEST_PASS = true
evidence_return_e2e_pass = true
product_e2e_pass = false
e2e_pass = false
release_ready = false
store_submission_allowed = false
user_product_approval = false
user_price_approval = false
```

The script does not install an MSIX, register or replace a Scheduled Task, change
Partner Center, submit or publish a Store product, edit a price, or edit product
source.

## Local preparation

Use the stacked smoke branch when testing this exact implementation:

```powershell
git fetch origin
git switch codex/local-github-evidence-smoke-20261116
git pull --ff-only
```

Confirm that the checkout is clean before continuing.

The smoke script itself also compares the local commit with the current GitHub
branch head and fails closed on drift.

## Preflight only

The default invocation performs no GitHub write:

```powershell
pwsh -File scripts\local_qa_github_smoke.ps1
```

Expected result:

```text
status = PREFLIGHT_PASS
github_write_requested = false
store_operations = false
scheduled_task_changes = false
```

If `gh auth status` fails, repair the local GitHub CLI authentication before the
real smoke. Do not paste a GitHub token into logs, issues, or chat.

## Real sanitized round trip

A GitHub write is explicit:

```powershell
pwsh -File scripts\local_qa_github_smoke.ps1 -AllowGitHubWrite
```

The default remote destination is the dedicated evidence branch:

```text
codex/local-qa-evidence-smoke
```

The worker may create that evidence branch if it does not exist. Evidence paths
are content-addressed under `ops/local-qa-results/`.

Expected final status:

```text
LOCAL_GITHUB_EVIDENCE_SMOKE_PASS
```

and:

```text
github_ack = GITHUB_READBACK_VERIFIED
evidence_return_e2e_pass = true
product_e2e_pass = false
store_submission_allowed = false
```

The synthetic evidence is intentionally safe for repository return. It contains
no real credential. The token-shaped string exists only to prove that the raw
local log and sanitized remote evidence remain separated.

## Optional Ollama check

GitHub transport should first be proven without Ollama. After that, the same
round trip can include the optional derived analyzer:

```powershell
pwsh -File scripts\local_qa_github_smoke.ps1 -AllowGitHubWrite -EnableAI
```

Ollama remains advisory. AI failure must not change product, release, or Store
authority.

## Failure behavior

A failure is a HOLD, not a product failure and not a reason to weaken a gate.

Examples:

- `gh auth status` failure → repair local GitHub CLI authentication.
- local/remote HEAD mismatch → fetch/review before testing; do not force sync.
- dirty working tree → preserve/review local changes first.
- GitHub transport failure → evidence remains in the durable retry queue.
- readback mismatch → evidence-return E2E remains false.
- redaction assertion failure → stop; do not manually upload raw evidence.
- Ollama unavailable → GitHub evidence transport may continue; AI remains
  `AI_ANALYSIS_UNAVAILABLE`.

## After the smoke

Keep the generated local state until the acknowledgement and remote evidence have
been reviewed. The default root is:

```text
%LOCALAPPDATA%\WindowsAllAuto\QA-Evidence-Smoke
```

The smoke does not register the 15-minute pull or evidence-retry Scheduled Tasks.
Those remain separate, explicit opt-in steps.

Only after this synthetic GitHub round trip passes should a revision-specific real
product be selected for:

```text
GitHub artifact
 -> local pull
 -> checker
 -> physical GUI/runtime test
 -> durable evidence
 -> GitHub return
 -> repair handoff
```

Even that later product run must keep `product_e2e_pass=false` until every
product-specific gate is independently proven.
