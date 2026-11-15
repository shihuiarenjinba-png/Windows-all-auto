# Store product handoff v2

`store-product-handoff/2` is the post-build/post-QA commercial contract between
Windows-all-auto and Windows-Automator. It does not replace the Factory MSIX
transport contract and it never authorizes Partner Center writes by itself.

## Separation of responsibilities

1. Windows-data / Factory: build and identify exact package bytes.
2. Windows-all-auto: bind package/source/identity evidence to commercial,
   distribution and owner approvals.
3. Windows-Automator: apply the validated product-specific choices to the
   current Partner Center form and save a draft.
4. Certification submission and Publish remain separate owner gates.

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
