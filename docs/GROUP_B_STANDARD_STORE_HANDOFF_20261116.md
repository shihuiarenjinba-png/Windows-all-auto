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

For subsequent updates, a Package flight may be used as the limited-audience signed
test path before broad release.

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
2. run local tests and exact frozen-SHA checks;
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
