# Cloud Auto Uploader — existing Partner Center browser route

## Current behavior

The upload method is inherited from the successful Store Draft operations already recorded in this repository; it does **not** assume an API. The browser uploads the exact `.msix` through the Partner Center Packages file input, observes Microsoft analysis, presses Packages `Save`, and confirms Overview `Validated / Complete` after reload before it can report success.

## Success evidence used as the implementation contract

These are separate live Partner Center observations recorded by the existing automation project:

| Product route | Evidence | Replayed behavior |
|---|---|---|
| Folio AI, `msix_pwa_app` | `docs/PARTNER_CENTER_MSIX_APP_FOLIO_UPLOAD_20261112.md`, `docs/PARTNER_CENTER_MAP.json`, and `tests/fixtures/partner_center_msix_pwa_app_folio_postupload_presave.json` in the `Windows-Automator` project | exact existing Product/Draft URL, `input[name='fileuploader'][type='file'][multiple]`, `Uploading` → `Analyzing package`, exact warning classification, `Save`, Overview `Validated / Complete`, reload/reopen retention |
| Daymark AI, `msix_pwa_app` | `docs/PARTNER_CENTER_MAP.json` (`observation_scope` says 2 independent products) | Same App package route and warning state, separately bound Store ID, Draft ID, and package |
| STRATEGY MARKET US and JP, `msix_pwa_game` | `docs/PARTNER_CENTER_MAP.json`, game observation/save docs and fixtures in `Windows-Automator` | Same high-level browser package flow, but product-specific Game route and full section completion; Game values are not copied into App jobs |
| Folder Automation Engine, `msix_pwa_app` | `ops/folder_engine_partner_center_teacher_20261118.json` and `ops/folder_engine_package_upload_receipt_20261119.json` | One exact upload; Microsoft states `Uploading` → `Analyzing package` → `Validated`; known `runFullTrust` warning only; Save; same Draft reload; package/version/architecture/Desktop retained |

The Folder receipt is the closest reusable template for this uploader and its observed control was the visible Browse link's file input. The older App route mapping records the exact CSS selector and post-save reconciliation. The new adapter combines these proven actions while binding every write to the configured Product ID, existing Submission ID, manifest Identity, Publisher, Version, Architecture, package SHA, and exact filename. A simulator test replays the Folder transition sequence and duplicate-write refusal.

The historical receipts prove successful **package upload and draft save**, not by themselves Certification or public publication. Those remain separate workflow states and this uploader has no controls for either.

## Browser authentication and cloud execution

`uploader.partner_center_browser` connects Playwright to exactly one already-authenticated Partner Center tab over Chromium CDP, matching the prior automation route. It does not automate Microsoft login, MFA, CAPTCHA, or authentication challenges. GitHub Actions can run the worker on a hosted Ubuntu runner when `PARTNER_CENTER_CDP_URL` points to an operator-approved remote browser session; a compatible remote-browser endpoint may have its own cost and must be provisioned by the owner. No service is provisioned or billed by this repository. If the endpoint/session is absent or expired, the job fails closed.

This is not yet an always-available unattended cloud service: GitHub Actions is event-driven and the configured browser endpoint must be online and authenticated when the event runs. Repository dispatch can enqueue a ready-product event; unsupported product keys are rejected. A strict zero-queue SLA requires the browser endpoint's availability and an operational monitor; neither is claimed by this MVP.

An API is not used for this route. The proven browser interaction is the chosen compatibility path for existing MSIX app Drafts. An API can be evaluated later only if it reproduces the exact existing-Draft binding and observable postconditions without creating a new submission.

## Local Windows execution — existing authenticated Edge session

The local route uses the existing Partner Center Edge session when local CDP is already enabled. If no local CDP endpoint is available, `scripts/start_partner_center_edge_cdp.ps1` starts a dedicated Edge profile on loopback port 9223; the owner signs in manually and completes MFA in that local window. No billed remote-browser service or Microsoft Store API is required. The existing Playwright/CDP adapter connects only to the loopback endpoint.

### 1. Read-only preflight for the full fleet

Run from the repository root after downloading the seven Actions artifacts. Scope the scan to the current `attempt-20261125` folder so older attempts with the same filename cannot make the lookup ambiguous:

```powershell
python scripts/preflight_store_fleet.py `
  --package-root "C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\attempt-20261125" `
  --output "C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\store-fleet-preflight.json"
```

The preflight recursively locates each exact registered filename and requires exactly one match. It verifies the package SHA-256 and manifest Identity, Publisher, Version, and Architecture. A missing or duplicated filename is a HOLD, never an arbitrary selection. It does not open Partner Center, upload, Save, start certification, or publish. Workflow Automation Hub is separately reported as `NO_EXISTING_SUBMISSION` because it has no existing Draft in the recorded snapshot.

### 2. Prepare the isolated Python runtime

```powershell
.\scripts\bootstrap_store_uploader.ps1
```

This creates `.venv-store-uploader` in the repository and installs the pinned Playwright Python client from `requirements-store-uploader.txt`. It does not install another browser; the uploader attaches to the installed Microsoft Edge by local CDP. The upload wrapper prefers this isolated environment when present.

### 3. Start or connect to local Edge CDP

Run from the repository root:

```powershell
.\scripts\start_partner_center_edge_cdp.ps1
```

The script is pinned to the approved DCA Packages route:

`https://partner.microsoft.com/en-us/dashboard/products/9PDL4ZWSB45P/submissions/1152921505702212222/packages`

- If no Edge CDP is listening, it starts a dedicated Edge profile under `%LOCALAPPDATA%\\PartnerCenterUploaderEdge`, binds CDP to `127.0.0.1:9223`, and opens that exact Draft URL.
- If Edge CDP is already listening, it verifies that the endpoint is Microsoft Edge. When the exact DCA Draft tab is absent, it opens one new tab at that exact URL through the local CDP target endpoint. It does not close, replace, or navigate existing tabs.
- If multiple exact DCA Draft tabs already exist, it does not create more tabs. Doctor must be allowed to report the ambiguity; remove the duplicate manually only after confirming which tab is safe to close.
- The script never reads credentials, cookies, tokens, or local storage. Sign in and complete MFA manually in the Edge window associated with port 9223.

After sign-in, run the read-only Browser Doctor:

```powershell
& .\.venv-store-uploader\Scripts\python.exe scripts\partner_center_browser_doctor.py `
  --product data-contract-auditor `
  --cdp-url http://127.0.0.1:9223
```

For this DCA operation, proceed only when the result is exactly `READY_EXACT_DRAFT_TAB`, with Product ID `9PDL4ZWSB45P` and Draft ID `1152921505702212222`. Do not treat a generic `READY_UNIQUE_PARTNER_CENTER_TAB` or `READY_UNIQUE_PRODUCT_TAB` as sufficient for this one-time operation. Any `HOLD_*`, authentication hold, or duplicate target stops the process. Doctor reports Edge version, context/page counts, sanitized page metadata and the selected page. It never navigates, clicks, selects a file, saves, or closes browser pages. The upload path uses the same selector and performs a read-only Product/Identity/Draft/package-row preflight before reserving an upload attempt.

### 4. One product dry run

```powershell
.\scripts\upload_store_msix.ps1 `
  -Product ai-upload-guard `
  -Package "C:\path\to\AIUploadGuard_QA_UNSIGNED_1.0.60.0_x64.msix"
```

Dry-run is the default. It verifies the exact configured filename, SHA-256, and manifest and writes a product-isolated execution receipt under `.uploader-run\\<product-key>` without touching Partner Center.

### 5. Existing-Draft package upload and Save

**One currently authorized live package write:** Data Contract Auditor only. Its job file binds the 1.0.0.0 candidate to SHA-256 `e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05`, Product `9PDL4ZWSB45P`, and the historical existing Draft `1152921505702212222`. The script rechecks the current Partner Center Identity and exact Draft route before it will write.

`scripts/upload_authorized_dca_package.ps1` is a guarded shortcut that searches the current attempt folder for the exact registered filename and refuses to proceed unless it finds exactly one file. Run it first as a dry-run:

```powershell
.\scripts\upload_authorized_dca_package.ps1
```

After confirming the dry-run receipt and signing in to the dedicated local Edge window, run the one-time authorized upload:

```powershell
.\scripts\upload_authorized_dca_package.ps1 -Execute
```

The shortcut uses the default package root `C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\attempt-20261125`. Use `-PackageRoot <path>` only if the current attempt directory is elsewhere. It requires exactly one file with the registered name and validates its frozen SHA/Manifest in dry-run first.

This authorization is limited to one SHA-bound package upload/Save/reload against the existing Draft. It does not authorize certification or publication. The artifact currently reports `certification_ready: false` and `sales_release: HOLD`, with a commercial-license evidence warning. Other five products remain dry-run only until their owner-approved version/artwork or runtime/source integration blockers are resolved.



```powershell
.\scripts\upload_store_msix.ps1 `
  -Product <registered-product-key> `
  -Package "C:\path\to\exact-registered-package.msix" `
  -Execute
```

`-Execute` is only for a product whose job config has `upload_approved: true` and a pinned 64-character `expected_sha256`. The script checks that local Edge CDP is responding at `http://127.0.0.1:9223/json/version` before attaching. CDP is restricted to loopback addresses for this route. CDP connection, authenticated session, exact Product/Draft route and existing package rows are verified before the SQLite upload attempt counter is incremented. A local connection/tab/preflight failure writes a separate receipt but consumes no remote upload attempt. Existing `receipt.json` is never replaced; later runs get unique `receipt-<id>.json` files. No Microsoft username, password, MFA code, browser cookie, or access token is placed in a command line or log.

The existing browser adapter then re-reads the exact Product Identity and configured Draft Packages route, checks existing package rows and Windows Desktop selection, uploads the exact MSIX, waits for Microsoft package validation, presses Packages `Save`, reloads Overview, and reopens Packages to confirm retention. Unknown warnings, validation errors, changed UI, ambiguous package rows, or timeouts stop for reconciliation; never blindly retry.

**Important boundary:** this script only uploads/saves the package in the existing Draft. It does not click `Submit to the Store`, start Certification, create a new Submission, change price or markets, or publish. Microsoft Store signing of MSIX/AppX happens after certification during publishing; no pre-upload CA certificate is required. Certification and publishing must be handled as a distinct approval step. Microsoft defaults to publishing immediately after certification; before any future certification submission, choose `Don't publish this submission until I select Publish now` under Submission options and verify that the manual hold is retained. See [Microsoft submission options](https://learn.microsoft.com/en-us/windows/apps/publish/publish-your-app/msix/manage-submission-options).

### Current registered-product holds

The six existing-Draft job files are registered with exact package filenames and builder/local SHA values. **Data Contract Auditor is the only job currently approved for one exact package upload/Save to its existing Draft** (`upload_approved: true`, exact SHA and filename pinned, approval recorded from the owner's 2026-11-25 instruction). Its `certification_submission_authorized` and `publish_authorized` values remain false. The other five jobs remain `upload_approved: false` with the product-specific hold reasons recorded in their config files. The uploader re-reads the configured Product and Draft and refuses unexpected package rows; it never submits for Certification or publishes.

Workflow Automation Hub deliberately has no existing-Draft job file because the latest read-only Partner Center observation showed no Submission. It must follow an owner-approved initial-Submission route rather than the existing-Draft uploader.

## Setup

1. Configure the repository and product job JSON from the example.
2. Pin `ref` to a full commit SHA for release uploads. Set an expected SHA-256 from the validated package receipt.
3. For private GitHub source, add `GH_READ_TOKEN` as a fine-grained Actions secret with Contents: read on that one source repository. Public source needs no token.
4. For a cloud live run, configure `PARTNER_CENTER_CDP_URL` as a GitHub Actions secret containing the approved remote browser connection endpoint. Keep the browser session authenticated outside this code; do not store Microsoft username/password or MFA secrets here.
5. Dry-run is default. A live write also requires a per-product frozen `expected_sha256`, exact Identity/Publisher/Version/Architecture, an exact existing Draft ID, and `upload_approved: true` in that product's job file. Product-specific approval must never be generalized to other products.
6. Dispatch `Store cloud uploader` for the registered product. `repository_dispatch` accepts `store-package-ready` with `client_payload.product` set to an allowlisted key.

## Registering a job

Add one `<product-key>.job.json` file under `uploader/config/`, use a lowercase hyphenated product key, unique Product and Submission IDs, set `destination` to `microsoft_partner_center_existing_draft`, choose the verified route, and pin an exact source ref and SHA-256. Provide the Identity, Publisher, Version, Architecture, and exact known warning allowlist for that product. The workflow resolves the key to that file without product-specific Python changes. Unknown destinations, route names, warnings and missing product files fail closed. Do not register certification or publish operations.

## Errors and retry

Errors have stable codes such as `AUTH_FAILED`, `PERMISSION_DENIED`, `FILE_NOT_FOUND`, `INVALID_FILE_FORMAT`, `FILE_SIZE_LIMIT`, `HASH_MISMATCH`, `PACKAGE_IDENTITY_MISMATCH`, `UNKNOWN_WARNING`, `PARTNER_CENTER_VALIDATION_FAILED`, `RECONCILE_REQUIRED`, and `UPLOAD_RESULT_UNKNOWN`. SQLite plus a per-product Actions cache prevents ordinary duplicate attempts; Partner Center is also checked for existing package rows before writing. A non-empty or ambiguous Draft is never blindly retried. Explicit failed jobs are capped at three attempts. Microsoft validation errors, unknown warnings, login challenges, target mismatches and changed UI selectors are quarantined for reconciliation.

## History and monitoring

The SQLite file is a retry/idempotency cache, not the durable source of truth. Each run writes a structured JSON receipt with Product ID, Submission ID, package filename, local SHA-256, UTC execution time, result, and Partner Center confirmation state. A short-lived Actions artifact (30 days) is only run evidence. The workflow separately appends receipts to the data-only `store-uploader-ledger-<ProductID>` branch using a writer job with `contents:write`; that product-specific branch is restored before processing and is the durable idempotency journal. Writers for the same product are serialized by the workflow concurrency key; different products use separate branches and can proceed independently. Branch updates are non-force. The Partner Center UI does not expose the uploaded binary SHA, so a prior receipt can bind the SHA sent by the automation to the same Product/Draft/filename, but the receipt never claims Microsoft independently computed that SHA.

If the durable ledger cannot be read completely, the worker fails closed. If the Actions cache is evicted but the durable receipt exists, the exact job is treated as already confirmed and is not uploaded again. If the UI shows an existing filename but no matching SHA-bound receipt exists, reconciliation stops rather than treating the UI as proof of binary identity. A contractual zero-backlog service objective still requires an operational monitor and an available authenticated browser endpoint.

## Tests

`python -m unittest tests.test_cloud_uploader tests.test_partner_center_browser -v`

## Not supported yet

- A real cloud Partner Center write for Data Contract Auditor (formal package and local UI QA gates are not ready).
- A managed or billed remote browser endpoint; `PARTNER_CENTER_CDP_URL` must point to one supplied by the operator.
- Creating a Store product or a Submission.
- Certification, publishing, price or market edits.
- Guaranteed always-zero backlog; GitHub Actions queued/running jobs are not an always-on daemon.
- A verified GitHub Actions CDP connection or live Data Contract Auditor upload.


## Latest verification checkpoint — 2026-11-26

- Updated branch HEAD: `f582aebeca84db1296b35aa709bf6393856ea5da`.
- Windows and Ubuntu Actions: 405 tests PASS on each runner; Windows also passed PowerShell parsing, wrapper forwarding, and Playwright bootstrap. Run: https://github.com/shihuiarenjinba-png/Windows-all-auto/actions/runs/45652446260
- Local full suite: 405 tests PASS (2 existing skips); compileall PASS; PowerShell Parser PASS for all 8 scripts; pinned Playwright 1.56.0 Bootstrap PASS.
- The exact DCA MSIX local hash and Manifest match the registered tuple; isolated dry-run returned `DRY_RUN`. Browser Doctor returned `HOLD_CDP_OR_CONFIG` because `127.0.0.1:9223` was unavailable. No upload attempt or Packages Save was performed.
- Start/activate the manually authenticated local Edge CDP session and rerun Doctor. Package-specific install/runtime verification remains unresolved; do not claim Partner Center upload or Packages Save until a later local run confirms it.
