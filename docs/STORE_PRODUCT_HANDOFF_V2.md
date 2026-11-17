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

## Exact-package QA and Microsoft Store signing strategy

For Microsoft Store MSIX distribution, do not purchase or require a third-party
production code-signing certificate solely to satisfy this pipeline. The intended
production signing path is Microsoft Store signing after certification.

Pre-Store QA and post-Store-signed QA are deliberately separated:

1. Before any Store write, bind the exact source/MSIX/EXE hashes and complete all
   static/package-integrity checks plus source/CI functional tests that do not
   require weakening Windows security policy.
2. If the physical QA machine naturally permits the exact unsigned executable,
   complete the existing package-bound local GUI/DPI/product QA receipt before
   Store submission.
3. If Windows Application Control blocks the exact unsigned executable, record an
   environment HOLD. Do not weaken policy, add a temporary certificate, or use a
   bypass path merely to force the test.
4. For an initial release that needs Microsoft-signed physical QA, use a separately
   approved **Private audience** Store submission. After certification and private
   publishing, install the Microsoft-signed package through the Store and perform
   the final physical GUI/DPI/product-specific QA there.
5. Only after the Store-signed private-audience QA passes may a later submission
   change the product to Public audience. Public certification/publication remains
   a separate owner gate.
6. For later updates, package flights may be used as the limited-audience signed
   test lane before broad release.

Uploading a package, submitting certification, private-audience publishing, and
public publishing are distinct external writes and require distinct execution-time
approval. A checked-in approval value is evidence only.

For paid Private-audience products, do not require the owner/tester to make a paid
purchase merely to obtain the Store-signed build. Private audience controls who may
acquire the product, but the configured paid price still applies. After certification
and private publishing complete, use a Microsoft Store promotional code for the
approved Private-audience Microsoft account so the signed build can be acquired at
no charge. The product must complete publishing before the promotional code can be
redeemed. Keep the intended commercial price intact; do not temporarily switch the
product to Free solely for QA.

### Local QA receipt

When a handoff contains `qa`, the existing `local-final-qa-receipt/1` remains the
receipt format for a completed physical QA run. Do not mark it PASS when execution
was blocked by Application Control; retain HOLD evidence and continue through the
approved Store-signed test lane instead.

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
