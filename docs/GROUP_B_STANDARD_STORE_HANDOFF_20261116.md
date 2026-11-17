# Group B standard apps — GitHub-to-local Store handoff

Updated: 2026-11-16 JST

## Objective

GitHub should finish every task that does not require the owner's physical Windows
machine, live Partner Center state, or a human/legal approval. Local work should begin
from exact CI artifacts, not from rebuilding source.

Standard products only:

1. Folder Automation Engine
2. Scheduled API Runner
3. Workflow Automation Hub
4. Browser Automation Runner

Never mix the `-2` repositories with these products.

## Shared completed GitHub path

For Scheduled / Hub / Browser, each product repository now contains:

- `store/generate_store_handoff.py`
- `store/STORE_HANDOFF_PROFILE_20261116.json`
- `store/LOCAL_FINAL_QA_AND_STORE_HANDOFF_20261116.md`
- generator contract tests
- CI wiring that emits `store-product-handoff.json` next to the exact MSIX
- Store listing/privacy/runFullTrust material in the MSIX artifact

The generated handoff binds:

- exact source commit;
- exact MSIX SHA256;
- exact EXE SHA256;
- Store ID / Identity / Publisher / Version;
- commercial model;
- Private-audience route;
- security/package binding;
- explicit HOLDs for live state and owner approvals.

Windows-all-auto supports exact-package local QA receipts:

- `scripts/create_local_final_qa_receipt_template.py`
- `scripts/apply_local_final_qa_receipt.py`

A QA receipt cannot be reused for another source/package.

## Signing policy for Group B standard MSIX products

The intended production signing route is the Microsoft Store's MSIX signing path.
Do not introduce a paid CA certificate merely to satisfy these Store releases.

The GAME pipeline was reviewed for reusable safety principles only. Reuse its
immutable-artifact binding, exact SHA/source provenance, check-only staging,
Code-Integrity non-bypass rule, and separation of signing from physical QA. Do not
copy GDK/MSIXVC packaging, CAS, Xbox sandbox, or game-specific submission mechanics
into this standard App route.

If an owner-controlled Windows QA device naturally runs the exact unsigned test
bytes, complete physical QA before Store submission as usual. If Windows Application
Control blocks those exact unsigned bytes, treat that as an environment HOLD rather
than weakening policy or installing a temporary trust certificate.

For the initial Store release, the preferred signed-QA lane is:

1. exact source/MSIX/EXE provenance and static preflight PASS;
2. source/CI functional tests PASS;
3. live Partner Center identity/submission-state reverify;
4. separately approved package upload;
5. separately approved certification submission configured for **Private audience**;
6. after certification/private publishing, install the Microsoft-signed Store build;
7. run JP/EN, DPI and product-specific physical QA against that signed Store build;
8. only after PASS, create a separate submission to move to Public audience.

The Private-audience publish is not the same approval as package upload,
certification submission, or later Public publication. Do not infer any of those
approvals from this document.

For Folder, which is intended to be paid, Private audience does not by itself make
the acquisition free. Never pay the app price merely to execute signed QA.

After the initial Private-audience submission is published, prefer this zero-cost
acquisition order:

1. use a Partner Center promotional code if the published app exposes that option;
2. otherwise use the configured Store free trial only if the live Store offers the
   tester a zero-cost install;
3. otherwise create a separately owner-approved temporary Free Private-beta
   submission, perform signed QA, then restore paid one-time + 7-day trial in a later
   submission before Public release.

The signed-QA receipt must record a zero-cost acquisition method and
`acquisition_cost_paid=false`.

For subsequent updates, a Package flight may be used as the limited-audience signed
test path before broad release. A flight is not the first-install solution because
flight members must already have the app.

### No-purchase signed QA for paid Private-audience products

For a paid product such as Folder Automation Engine, membership in a Private audience
does **not** make acquisition free. A tester would normally pay the configured Store
price.

The preferred owner test route is therefore:

1. keep the product paid and Private audience;
2. complete certification/private publishing under separate approval;
3. after the product reaches the final published state for that private audience,
   generate a Microsoft Store promotional code;
4. redeem the code with the Microsoft account that belongs to the configured Private
   audience / Known User Group;
5. acquire and install the Microsoft-signed Store package at no charge;
6. perform final signed-build QA;
7. do not purchase the app merely to perform owner QA.

Do not temporarily change the commercial model to Free only to avoid a test purchase.
Do not assume a promo code is usable before the product completes publishing.
Promo-code creation/redemption is an acquisition/test step; it does not itself approve
a later Public release.

The game/GDK repositories contain useful provenance and physical-QA patterns, but
their GDK/MSIXVC2/sandbox rules are product-route-specific. Reuse only the general
principles (immutable bytes, exact Identity/version, no Code Integrity bypass,
separate physical QA evidence); never substitute a GDK package flow for this standard
MSIX app.

## Priority 1 — Folder Automation Engine

Repository: `shihuiarenjinba-png/folder-automation-engine`  
PR: #10

Frozen upload candidate:

- product source: `51597b389384be6cf2b3d85c09ee66099b80807e`
- Store ID: `9P99MJX1R4V6`
- version: `1.0.0.0`
- MSIX SHA256: `911f8eb13abfdbb51bea8f279006d138d6be9cba4a25413416c1d70458676450`
- EXE SHA256: `d53161ea1119445afb8070d989d4a72e8019895b8c5e166738a3e38718b54976`

The later Folder commits after the frozen product source are Store metadata/runbook
changes only. Do not rebuild the product only because those metadata files changed.

Local-only sequence:

1. sync the three execution repositories;
2. verify the existing frozen local MSIX and exact SHA/Manifest/EXE binding; do not rerun GitHub's full test suite locally;
3. re-read Partner Center;
4. require exact initial-submission/update classification;
5. direct execution-time approval for any Start action;
6. bind Draft receipt;
7. observe remaining Store fields;
8. VALIDATE_ONLY;
9. DRY_RUN;
10. separate package-upload approval.

## Priority 2 — Scheduled API Runner

PR #8.

GitHub completion target:

- exact-head unit/reliability CI;
- exact Windows EXE + unsigned MSIX;
- exact-package handoff emitted in artifact;
- Store docs bundled;
- local final QA runbook committed.

Local-only acceptance:

- physical JP/EN + DPI;
- controlled authorized API GET;
- dated CSV behavior;
- secret redaction;
- Task Scheduler lifecycle;
- live Partner Center reverify.

Commercial model: FREE candidate. Actual Partner Center change remains owner-gated.

## Priority 3 — Workflow Automation Hub

PR #12.

GitHub completion target:

- exact Windows build;
- GUI evidence;
- source/frozen self-test;
- SBOM / third-party notices;
- unsigned MSIX;
- exact-package handoff emitted in artifact;
- Store docs bundled.

Local-only acceptance:

- physical JP/EN + DPI;
- controlled non-production Google OAuth/Blogger;
- Dry Run then one controlled test-blog mutation;
- backup / duplicate guard;
- Task Scheduler lifecycle;
- live Partner Center reverify.

Commercial model: FREE candidate. No production Blogger write is implied.

## Priority 4 — Browser Automation Runner

PR #8.

GitHub completion target:

- exact Windows build;
- bundled Chromium offline smoke;
- unsigned MSIX;
- customer-readable Playwright/Chromium/FFmpeg notice collection;
- package inventory + roundtrip hash verification;
- exact-package handoff emitted in artifact;
- Store docs bundled.

Local-only acceptance:

- physical JP/EN + DPI;
- safe test-site workflow;
- bundled Chromium behavior;
- output collision/no-overwrite;
- owner/legal review of exact redistributed browser payload;
- live Partner Center reverify.

Technical notice collection does not replace the human redistribution-rights decision.

## Direct product-artifact pull for local confirmation

For Scheduled API Runner, Workflow Automation Hub, and Browser Automation Runner,
do not manually retype repository/artifact names when staging the exact successful
Store artifact. Use the checked-in Group B registry:

```text
ops/group_b_standard_store_products.json
```

and the wrapper:

```powershell
python scripts/pull_group_b_store_product.py `
  --product-id <scheduled-api-runner|workflow-automation-hub|browser-automation-runner> `
  --target-root C:\path\to\group-b-local-inbox `
  --receipt C:\path\to\evidence\artifact-pull-receipt.json
```

By default the wrapper resolves the registered source branch, requires the current
branch HEAD, and discovers a unique successful run of the registered Store-build
workflow for that exact HEAD. If there are zero matches it HOLDs. If there are
multiple exact-head successful Store runs it refuses to guess; pass `--run-id`
explicitly after selecting the intended run.

The wrapper delegates to `pull_store_product_artifact.py` and requires:

- the run conclusion is SUCCESS;
- workflow head SHA equals the artifact handoff source SHA;
- exactly one MSIX, validation report, checksum, and Store handoff;
- package SHA matches handoff + validation + checksum;
- EXE SHA roundtrip matches;
- Store ID / Identity / Publisher / Version match;
- the destination and receipt do not already exist.

It records `package_rebuilt=false`, `security_bypass_used=false`,
`submitted_to_store=false`, `certification_submitted=false`, and
`published=false`.

Folder is intentionally excluded from this direct-pull route because its pilot uses
the already-frozen source/package bytes. Do not replace Folder's frozen candidate with
a newer product-repository artifact.

## Definition of GitHub-side completion

A product is GitHub-complete when its latest PR HEAD has successful required CI and
the Store artifact contains:

1. exact MSIX;
2. `msix_validation.json`;
3. checksum file;
4. `store-product-handoff.json`;
5. local final-QA runbook;
6. Store listing/privacy/runFullTrust documents;
7. product-specific compliance evidence where applicable.

At that point, do not add speculative product features. Download the exact artifact,
perform local QA, return the exact-package QA receipt, reverify live Partner Center,
then proceed through separately authorized Store gates.

Main/release merges, package upload, certification and Publish are not authorized by
this document.
