# Store product handoff v2

`store-product-handoff/2` is the post-build/post-QA commercial contract between
Windows-all-auto and Windows-Automator. It does not replace the Factory MSIX
transport contract and it never authorizes Partner Center writes by itself.

## Separation of responsibilities

1. Product repository / Factory: build and identify exact package bytes.
2. Product CI: emit `store-product-handoff.json` bound to exact source/MSIX/EXE SHA.
3. Local Windows QA: download those exact bytes, test without rebuilding, and emit
   `local-final-qa-receipt/1`.
4. Windows-all-auto: bind the local QA receipt plus live identity/commercial evidence.
5. Windows-Automator: apply the validated product-specific choices to the current
   Partner Center form and save a draft/package only under the relevant approval.
6. Certification submission and Publish remain separate owner gates.

## Required sections

- product: immutable product route, repository and source SHA
- package: exact MSIX type/file/SHA and artifact provenance
- identity: Store ID, package identity, publisher, version, architecture and
  live Partner Center re-verification state
- commercial: free or paid-one-time model, currency, exact Partner Center price
  choice, free-trial choice and approvals, manual publishing hold
- distribution: Private audience or Public release
- assets: visual approval state
- security: package-SHA-bound human security confirmation
- approvals: draft / certification / publish gates
- qa (when present): exact-head CI, local final QA, and later Store-signed install state

Generated handoffs for Group B standard products intentionally start HOLD. CI proves
engineering/package identity; it does not impersonate live Partner Center state or
human approvals.

## Exact-package local QA

When a handoff contains `qa`, `qa.local_final_pass=true` is required before the
handoff can become ready for Windows-Automator.

Create a receipt template:

```powershell
python scripts/create_local_final_qa_receipt_template.py `
  --handoff C:\qa\store-product-handoff.json `
  --output C:\qa\local-final-qa-receipt.json
```

Run the product-specific repository QA against the exact downloaded package. Do not
rebuild it. Set the receipt to PASS only when all required fields are true:

- tests_passed
- package_sha_verified
- unpacked_exe_sha_verified
- jp_en_gui_passed
- dpi_matrix_passed
- product_specific_acceptance_passed
- normal_exit_passed

The receipt must also prove:

- package_rebuilt = false
- security_bypass_used = false

Apply it:

```powershell
python scripts/apply_local_final_qa_receipt.py `
  --handoff C:\qa\store-product-handoff.json `
  --receipt C:\qa\local-final-qa-receipt.json `
  --output C:\qa\store-product-after-local-qa.json
```

The receipt is rejected if Store ID, source SHA or package SHA differ. Applying local
QA cannot approve security fields, assets, pricing, certification or Publish.

## Paid + trial

For paid one-time products:

- exact Partner Center price/tier is never inferred;
- paid price must be owner-confirmed;
- a non-none trial (1/7/15/30 days or unlimited) must be separately
  owner-confirmed;
- a trial cannot be attached to a free product;
- `manual_publish` is mandatory in this contract.

Folder Automation Engine is the first reference product:
low-cost paid one-time + owner-approved 7-day trial. Its exact price remains
HOLD until the current live Partner Center choice is selected and confirmed.

## Safe conversion

Use `scripts/prepare_store_automator_input.py`.

Validation-only example:

```text
python scripts/prepare_store_automator_input.py \
  --handoff store-product.json \
  --package-path C:\path\product.msix \
  --images-dir C:\path\store-images \
  --output automator-input.json
```

By default the command refuses to produce an executable Automator input unless
`ready_for_automator_draft=true`. `--allow-hold` may be used only to inspect the
normalized missing-field list; the generated file remains marked HOLD.

No command in this module uploads, submits certification or publishes.
