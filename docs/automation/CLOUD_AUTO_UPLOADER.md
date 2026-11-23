# Cloud Auto Uploader MVP

## Current behavior

The GitHub Actions workflow runs on Ubuntu and downloads one configured `.msix` from an exact Git ref. The worker checks repository, product ID, existing Submission ID, version, extension, size and SHA-256, then records an idempotency key in SQLite. Dry-run is the default. A Partner Center write is not enabled: the current API adapter intentionally fails closed for MSIX until an existing-draft API contract is confirmed. HTTP acceptance alone never counts as success; a live adapter must return `partner_center_confirmed: true`.

The official Microsoft Store Submission API uses Microsoft Entra ID. Microsoft's [current submission API reference](https://learn.microsoft.com/en-us/windows/apps/publish/store-submission-api) documents the newer API for MSI/EXE products; the UWP service API can create submissions and therefore is not used here because this job must bind to an existing draft and must not create or commit a submission. Microsoft also documents that the UWP API's create-submission call opens a new in-progress submission ([Create an app submission](https://learn.microsoft.com/en-us/windows/uwp/monetize/create-an-app-submission)). The exact API operation for an existing MSIX draft remains a compatibility gate.

## Setup

1. Configure the repository and product job JSON from the example.
2. Pin `ref` to a full commit SHA for release uploads. Set an expected SHA-256 from the validated package receipt.
3. For private GitHub source, add `GH_READ_TOKEN` as a fine-grained Actions secret with Contents: read on that one source repository. Public source needs no token.
4. Do not add Entra client secrets until the existing-MSIX-draft API adapter is enabled and the Partner Center application permission has been verified. Never print or commit credentials.
5. Run locally or dispatch `Store cloud uploader`; dispatch currently performs validation and dry-run only.

## Registering a job

Add one JSON file under `uploader/config/`, use unique product and Submission IDs, set `destination` to `microsoft_partner_center_existing_draft`, and pin exact source ref and expected hash. Unknown fields and destinations fail closed. Do not register certification or publish operations.

## Errors and retry

Errors have stable codes such as `AUTH_FAILED`, `PERMISSION_DENIED`, `FILE_NOT_FOUND`, `INVALID_FILE_FORMAT`, `FILE_SIZE_LIMIT`, `HASH_MISMATCH`, `TIMEOUT`, `API_UNSUPPORTED`, and `UPLOAD_RESULT_UNKNOWN`. SQLite prevents duplicate attempts. A running or ambiguous operation becomes `RECONCILE_REQUIRED` / `UNKNOWN`; it is not retried automatically. The MVP caps safe retry starts at three. Exponential backoff belongs in the remote adapter after it classifies explicit transient responses; ambiguous writes must be reconciled first.

## History and monitoring

The workflow emits a run artifact and SQLite ledger. For persistent multi-run history, use an external durable database or an immutable receipt artifact retention policy; the GitHub runner filesystem is ephemeral. The ledger exposes status, attempts and target identifiers; add operational dashboards before declaring a zero-backlog service-level objective.

## Tests

`python -m unittest tests.test_cloud_uploader -v`

## Not supported yet

- Live MSIX package writes to Partner Center.
- Creating a Store product or a Submission.
- Certification, publishing, price or market edits.
- Guaranteed always-zero backlog; GitHub Actions queued/running jobs are not an always-on daemon.
- Cross-run SQLite persistence beyond archived workflow artifacts.
