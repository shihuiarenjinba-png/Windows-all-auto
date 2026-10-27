# Local multi-product Identity scheduler (independent stacked branch)

This is a local-only orchestration layer on PR #17. It does not replace
scripts/local_identity_return.py, implement CAS, submit to Store, download
the MSIX backlog, or authenticate to Partner Center. The unpushed local
Codex implementation is untouched and can be compared later.

## Verified source repositories

The scheduler reads each product's actual remote HEAD and
store/unsigned_msix_submission_inputs.json from the same immutable commit:

| Repository | Branch |
| --- | --- |
| -AI-Upload-Guard-AI- | codex/store-p1-ai-upload-guard-20261023 |
| -Excel-CSV-Privacy-Cleaner | codex/store-p1-excel-csv-privacy-20261023 |
| -Screenshot-Image-Privacy-Cleaner | codex/store-p1-image-privacy-20261023 |

It discovers existing_msix_builder per product, not a hard-coded builder.
GAME Signal Sprint is bound to the current central active_e2e_handoff.json.
APP canary remains HOLD until the 00 APP owner supplies a promoted product,
real EXE, immutable request_id/source_sha and an official Identity reference.

## Private local job input

Place the following JSON **outside all Git checkouts**. All placeholder
values must be replaced using the live GitHub refs and real local EXE.
Never commit local job, evidence, state or receipt files.

~~~json
{
  "jobs": [
    {
      "kind": "STORE_KNOWN_GOOD",
      "request_id": "operator-supplied-immutable-request-id",
      "repository": "shihuiarenjinba-png/-Excel-CSV-Privacy-Cleaner",
      "branch": "codex/store-p1-excel-csv-privacy-20261023",
      "source_sha": "REPLACE_WITH_LIVE_40_CHARACTER_SHA",
      "package_path": "C:\\private-qa\\excel\\actual.exe",
      "package_sha256": "REPLACE_WITH_REAL_64_CHARACTER_SHA256",
      "evidence_path": "C:\\private-qa\\excel\\operator-observation.json"
    }
  ]
}
~~~

The private operator-observation.json must have exactly these keys:
observation (LOCAL_OPERATOR_OBSERVED_MATCH), request_id, source_sha,
store_id, reserved_display_name, identity_name, publisher,
publisher_display_name, package_family_name, package_sid. All identity
fields are compared against the separately retrieved known-good reference.
This is **not** independent authenticated Partner Center proof and does
not set IDENTITY_AUTHENTICATION_PASS.

Do not put tokens, passwords, cookies, MFA, private keys, PFX, raw HTML,
authenticated URLs or screenshots into the input or receipts.

~~~powershell
py -3 -m scripts.local_identity_scheduler --jobs-file "C:\private-qa\identity-jobs.json" --state-dir "C:\private-qa\identity-scheduler-state"
~~~

Exactly one job is processed per invocation with round-robin cursor.
The state directory has an exclusive lock, atomic receipts and immutable
binding. Protect it using Windows user-only ACLs. After a crash, inspect
the orphaned lock and any CAS receipt before manually clearing the lock.
Do not run two instances on the same state directory.

For GAME, the scheduler only delegates to the original PR #17 worker
when both request-specific approval flags are supplied, the original
EXE hash and central ledger match, and the local Provisioner inputs
are provided. The worker itself verifies the official Identity and
performs the only GitHub CAS.

~~~powershell
py -3 -m scripts.local_identity_scheduler --jobs-file "C:\private-qa\identity-jobs.json" --state-dir "C:\private-qa\identity-scheduler-state" --apply-request-id "<exact GAME request_id>" --confirm-request-id "<same GAME request_id>" --provisioner-root "C:\src\Repository-Provisioner-game" --provisioner-result "C:\private-qa\signal-sprint\result.json"
~~~

Never blindly repeat a CAS after an uncertain outcome. Reconcile via
the existing dedicated worker's private receipt and Factory HEAD.

## Explicit HOLD gates

- STORE: local operator-observed identity match is not authentication;
  product-specific CAS is not yet connected. No Store CAS is attempted.
- MSIX: even after Identity, approved_store_version must be a reviewed
  four-part version, package_version_approval and brand_assets_approval
  must both be APPROVED. Current known-good references are null/UNKNOWN.
  No guessed version or artwork approval is written.
- Windows-data PR #1 remains the Identity/MSIX parser and builder.
  This scheduler does not duplicate it.
- Backlog: verified-msix-local-qa artifact, 30-day target retention,
  local 20 packages/2 GiB and HOLD_LOCAL_CAPACITY remain separate.
  This branch does not change any backlog workflow or limits. Verify
  actual integration workflow retention before claiming backlog PASS.
- Checker and Windows GUI/install QA remain unverified until real MSIX
  and real-device evidence are obtained. CI is not UI PASS.

Identity discovery, authentication, return, MSIX build, GitHub backlog,
local pull, Checker, GUI QA and E2E PASS are separate verdicts.
