# Microsoft Store pre-upload gate

`all_auto.store_preupload_gate` is the fail-closed boundary immediately before
an MSIX upload can be proposed for human approval. It is deliberately local
and read-only: evaluating the gate cannot open Partner Center, start a
submission, upload a package, change pricing, submit for certification, or
publish.

## Inputs and evidence

The input schema is `store-preupload-gate-input/2`. Every evaluation requires:

- the exact local package path and expected SHA-256;
- immutable Store ID, Identity, Publisher, Version, Architecture, source SHA,
  package SHA-256, and package file name;
- a read-only recovered-Draft receipt using
  `existing-store-initial-submission-reconcile-receipt/1`;
- explicit evidence that every required Partner Center section was inspected;
- an explicit Store-assets readiness decision.
- an exact confirmed JPY price value;
- a confirmed Private Audience Known User Group;
- owner confirmation of the personal-data and runFullTrust answers;
- a read-only reload reconciliation with no unexpected write observed.

The evaluator re-hashes the local package during each run. It never trusts a
previous hash receipt as a substitute for checking the bytes that would be
uploaded.

## Deterministic result priority

The first matching result is returned in this order:

1. `HOLD_LOCAL_MSIX_NOT_FOUND`
2. `HOLD_LOCAL_MSIX_SHA_MISMATCH`
3. `HOLD_SUBMISSION_RECONCILE_REQUIRED`
4. `HOLD_EXACT_PACKAGE_MISMATCH`
5. `HOLD_STORE_ASSETS`
6. `HOLD_EXACT_PRICE_TIER_UNCONFIRMED`
7. `HOLD_PRIVATE_AUDIENCE_GROUP_REQUIRED`
8. `HOLD_OWNER_SECURITY_CONFIRMATION_REQUIRED`
9. `HOLD_UNKNOWN_PARTNER_CENTER_STATE`
10. `READY_FOR_MSIX_UPLOAD_APPROVAL`

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

The output uses schema `store-preupload-gate-receipt/2`. Store the receipt
beside the product's other package-bound preflight evidence.

## Folder Automation Engine example

The 2026-11-17 read-only reconciliation found the existing Draft for Store ID
`9P99MJX1R4V6` and preserved its numeric Draft ID. The exact frozen
`FolderAutomationEngine_1.0.0.0_x64_StoreDraft_UNSIGNED.msix` re-hashed to the
expected SHA-256. Two deterministic application-window screenshot candidates
exist, but owner visual approval is false, so the gate correctly returns
`HOLD_STORE_ASSETS`. No Partner Center write is performed.

