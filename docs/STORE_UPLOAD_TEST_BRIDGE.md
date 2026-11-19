# Store upload test bridge

## Purpose

This bridge handles the stage after a GitHub product is fully ready for Store
upload testing.

It is deliberately separate from Folio/post-release regression. A product
becomes eligible only after its own final QA and evidence gates pass.

```text
Factory / GitHub artifact
-> exact artifact intake
-> Windows local product E2E
-> Evidence return + ACK
-> Windows-checker READY
-> official Partner Center Identity re-verification
-> owner security confirmation
-> listing assets ready
-> Store upload-test batch
-> Windows-Automator dry-run
-> action-time owner approval
-> Partner Center package upload + Save draft
-> reload/readback
-> DRAFT_SAVED
```

Certification submission and publication are outside this bridge.

## Candidate gate

Every candidate must satisfy exactly:

```text
test_status = TEST_PASS
evidence_return_e2e_pass = true
product_e2e_pass = true
checker_verdict = READY_CANDIDATE_NOT_CERTIFIED
official_identity_reverified = true
security_owner_confirmed = true
listing_assets_ready = true
```

The Windows-Automator input must also be bound to the same Store Product ID,
source SHA, package SHA, Identity Name, Publisher, Version, and security
confirmation package SHA.

A GitHub-provided local package path is rejected. The bridge downloads the
exact Actions artifact itself, re-verifies archive/MSIX/EXE provenance and
injects the verified local package path.

The current bridge accepts exact `.msix` package candidates. MSIXUPLOAD,
bundle, GDK/MSIXVC and EXE/MSI routes remain separate until their exact intake
contracts are implemented and tested.

## Windows-Automator pin

The batch pins an exact Windows-Automator repository, codex branch and commit.
The local checkout must match the pinned commit and origin before any
Windows-Automator process is started.

At implementation time the validated target is:

```text
repository: shihuiarenjinba-png/Windows-Automator
branch: codex/msix-commercial-contract-20261115
commit: d3b8ed4ae7762a69d3fe2a90b64aa86ee938259b
```

Do not silently update this pin. A newer Automator HEAD must be reviewed and
placed in a new batch.

## Dry run

Dry run performs no Partner Center write.

```powershell
python .\scripts\store_upload_test_bridge.py `
  --batch .\path\to\store-upload-test-batch.json `
  --automator-checkout C:\path\to\Windows-Automator `
  --workspace .\.test-tmp\store-upload-dry-run `
  --execution-mode dry_run
```

Success requires every product to return `DONE` and the aggregate result
is `UPLOAD_TEST_DRY_RUN_PASS`. Otherwise it remains
`UPLOAD_TEST_DRY_RUN_HOLD`.

## Live draft upload test

Live mode requires a fresh action-time confirmation and an already-authenticated
Partner Center browser CDP endpoint.

```powershell
python .\scripts\store_upload_test_bridge.py `
  --batch .\path\to\store-upload-test-batch.json `
  --automator-checkout C:\path\to\Windows-Automator `
  --workspace .\.test-tmp\store-upload-live `
  --execution-mode live `
  --confirm-live-draft `
  --cdp-url http://127.0.0.1:<port>
```

The bridge delegates only to Windows-Automator's reviewed live-draft path.
It may verify the exact product/draft, upload the exact package, wait for
Microsoft validation, Save the draft, reload/reconcile it, verify required
sections, and capture evidence. It does not submit certification or publish.

A full batch succeeds only when every result is `DRAFT_SAVED`.

## UNKNOWN

If a remote write outcome is ambiguous, the result is
`UPLOAD_TEST_UNKNOWN_HOLD`. UNKNOWN is never automatically retried. The draft
must first be reconciled in Partner Center.

## Batch result

The bridge reports aggregate counts for total, dry_run_done, draft_saved,
hold, unknown, and error, and permanently reports:

```text
store_submission_allowed = false
certification_allowed = false
publish_allowed = false
automatic_retry_unknown = false
```

## Multi-product operation

A single batch may contain up to 20 unique candidates. Duplicate request IDs
and duplicate Store IDs are rejected before artifact download. Each candidate
is independently re-verified before the Automator queue is created.

## Required separation

Do not collapse these states:

```text
GitHub artifact READY
Windows local QA PASS
Product E2E PASS
Store upload dry-run PASS
Partner Center DRAFT_SAVED
Certification submitted
Published
```

Each is a separate gate.

Folio AI is already sold and is used for regression of the local QA machinery.
It is not itself the fresh unsold candidate used to prove this Store upload-test
promotion gate.
