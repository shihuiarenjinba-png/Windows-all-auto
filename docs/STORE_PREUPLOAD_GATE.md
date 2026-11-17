# Microsoft Store pre-upload gate

`all_auto.store_preupload_gate` is the fail-closed boundary immediately before
an MSIX upload can be proposed for human approval. It is deliberately local
and read-only: evaluating the gate cannot open Partner Center, start a
submission, upload a package, change pricing, submit for certification, or
publish.

## Inputs and evidence

The input schema is `store-preupload-gate-input/1`. Every evaluation requires:

- the exact local package path and expected SHA-256;
- immutable Store ID, Identity, Publisher, Version, Architecture, source SHA,
  package SHA-256, and package file name;
- a read-only recovered-Draft receipt using
  `existing-store-initial-submission-reconcile-receipt/1`;
- explicit evidence that every required Partner Center section was inspected;
- an explicit Store-assets readiness decision.

The evaluator re-hashes the local package during each run. It never trusts a
previous hash receipt as a substitute for checking the bytes that would be
uploaded.

If merely opening/rendering a Partner Center section changes its Overview state
(for example Pricing becoming `In progress` without an explicit Save), the input
must set `store_fields.read_only_ui_state_changed=true`. The gate then remains
fail-closed until a reload/reopen reconciliation proves the read-only observation
did not become an unintended persisted write by setting
`store_fields.read_only_reload_reconciled=true`. A visual state change alone is
never treated as proof of a write or proof of a successful Save.

## Deterministic result priority

The first matching result is returned in this order:

1. `HOLD_LOCAL_MSIX_NOT_FOUND`
2. `HOLD_LOCAL_MSIX_SHA_MISMATCH`
3. `HOLD_SUBMISSION_RECONCILE_REQUIRED`
4. `HOLD_EXACT_PACKAGE_MISMATCH`
5. `HOLD_STORE_ASSETS`
6. `HOLD_UNKNOWN_PARTNER_CENTER_STATE`
7. `READY_FOR_MSIX_UPLOAD_APPROVAL`

`READY_FOR_MSIX_UPLOAD_APPROVAL` is an approval boundary, not upload
authorization. A separate authorized workflow must still perform the upload
and verify its postconditions.

Every receipt records these safety invariants:

- Start submission: `NOT_REPEATED`
- package upload: `NOT_EXECUTED`
- certification: `NOT_EXECUTED`
- publish: `NOT_EXECUTED`
- `write_performed: false`

## Command

```powershell
python scripts/evaluate_store_preupload_gate.py `
  --input C:\path\to\store-preupload-gate-input.json `
  --output C:\path\to\store-preupload-gate-receipt.json
```

The output uses schema `store-preupload-gate-receipt/1`. Store the receipt
beside the product's other package-bound preflight evidence.

## One-command local conveyor receipt

On Windows, `scripts/run_store_preupload_readiness.ps1` is the generic local
entrypoint. It first performs the cheap frozen-file/Draft check, then unpacks
the same MSIX and verifies its Manifest Identity and main EXE SHA. Finally,
`scripts/finalize_store_preupload_receipt.py` binds both results into
`store-preupload-readiness.json`.

The final receipt includes `immutable_binding`, `static_preflight`, and
`store_actions`. `READY_FOR_MSIX_UPLOAD_APPROVAL` is emitted only when the
same machine-readable receipt proves that the package was not rebuilt, no
security bypass was used, and upload/certification/publish were not executed.
For a frozen source followed only by metadata commits, pass
`-SourceCheckoutMode ContainedCommit`. Do not pass `-RunSelfTest` for a product
whose exact unsigned executable already has a recorded Application Control
block.

## Folder Automation Engine example

The 2026-11-17 read-only reconciliation found the existing Draft for Store ID
`9P99MJX1R4V6` and preserved its numeric Draft ID. The exact frozen
`FolderAutomationEngine_1.0.0.0_x64_StoreDraft_UNSIGNED.msix` re-hashed to the
expected SHA-256. Two deterministic application-window screenshot candidates
exist, but owner visual approval is false, so the gate correctly returns
`HOLD_STORE_ASSETS`. No Partner Center write is performed.

