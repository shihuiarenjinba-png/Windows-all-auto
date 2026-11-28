# Product-driven Store workflow entry point

`python -m all_auto store run --product <registered-key>` loads the existing
`uploader/config/<key>.job.json` as the product binding and creates a unique
JSON evidence report. It defaults to `AUTO`: only complete persisted
Product/Draft-bound owner approvals can dispatch their exact sections. With
the current DCA profile, AUTO resolves to PLAN_ONLY. `READ_ONLY` and `DRY_RUN`
force planning without writes.

Optional inputs are explicit and are never found by guessing:

```powershell
python -m all_auto store run --product data-contract-auditor `
  --source-root C:\path\to\csv-import-validator `
  --package C:\path\to\DataContractSchemaDrift_1.0.0.0_x64.msix
```

The source checkout's origin and resolved ref must match the registered job
profile. A supplied MSIX is checked using the existing uploader's filename,
SHA-256, Manifest Identity, Publisher, Version, and Architecture checks. The
report records unresolved owner inputs instead of inventing listing text,
price, markets, legal declarations, or Draft state. Reports use unique names;
existing evidence is never overwritten.

## Safety boundary

The default AUTO mode dispatches only exact sections persisted as
owner-approved in the product profile. Each non-Package section also requires
its own Product ID / Draft ID /
section approval, approved values, and a `verified: true` UI map. Packages also
requires the exact package SHA and Manifest, exact-package Windows runtime QA,
existing package-only authorization, and persisted device-family approval.
Missing any gate produces PLAN_ONLY or HOLD before the related UI action.

Certification and Publish have no dispatcher. Product/submission creation,
listing or commercial settings without section approval remain prohibited.
The established exact-package uploader remains the Packages adapter.

For Data Contract Auditor, the fixed Product ID, existing Submission ID,
repository/ref, identity, publisher, version, architecture, filename, and
expected SHA-256 are checked against the registered job profile. Its current
package-only approval is not interpreted as approval for other sections.

## Current integration gaps

This is an orchestration and evidence-planning entry point, not a claim that
all Store sections are live-verified. The shared form engine can operate a
mock form for text, number/price, select, radio, checkbox groups, regions,
images, and save/reload reconciliation. Real Partner Center write adapters
remain unverified for Properties, listings, pricing/markets, age ratings, and
Submission Options. Their UI maps are fail-closed until those exact live
routes are observed and recorded. Do not mark a product complete from this
report.

The profile persists device-family candidates separately from approval.
Manifest `Windows.Desktop` only suggests the Store's `Windows 10/11 Desktop`
checkbox; it is not a commercial distribution decision. A Product/Draft-bound
owner approval must be recorded once before the Packages adapter can select it.
