# Folder Automation Engine — Store-signed no-cost QA pilot

Updated: 2026-11-17 JST

## Objective

Complete one Group B standard product end-to-end without buying a production
code-signing certificate and without paying to acquire the paid app for the owner's
test account.

This pilot applies only to:

- Store ID: `9P99MJX1R4V6`
- Identity: `OkinawaDesktopTools.FolderAutomationEngine`
- Publisher: `CN=46263F21-A700-41DB-8C9B-114C22FB82FC`
- PFN: `OkinawaDesktopTools.FolderAutomationEngine_j8yefg9jgfh58`
- Version: `1.0.0.0`
- frozen product source: `51597b389384be6cf2b3d85c09ee66099b80807e`
- frozen MSIX SHA256:
  `911f8eb13abfdbb51bea8f279006d138d6be9cba4a25413416c1d70458676450`
- frozen EXE SHA256:
  `d53161ea1119445afb8070d989d4a72e8019895b8c5e166738a3e38718b54976`

Do not rebuild or substitute the frozen MSIX.

## Microsoft signing model

For MSIX distributed through Microsoft Store, production signing is provided by
Microsoft Store during the submission/certification/publishing flow. A paid CA code
signing certificate is not required for this Store-distribution path.

Local self-signing is technically possible for development testing, but this pilot
does not weaken Windows Application Control, add a temporary trust certificate, or
modify the machine certificate store merely to force the unsigned candidate to run.

Current pre-Store evidence is therefore retained as
`APPLICATION_CONTROL_BLOCKED`, not treated as a product-functional failure.

## Important: package flights are not the initial-release lane

Microsoft package flights are useful after an app already has a published
non-flighted Store submission. They are not the replacement for Folder's first
submission.

For the initial Folder release, first create and certify a tightly limited normal
submission. Package flighting may be used for later updates.

## No-cost acquisition strategy

The owner should not purchase their own paid app merely to test the Microsoft-signed
Store build.

Microsoft Store promotional codes can provide free acquisition of a published paid
app for testing. For general Windows apps, promo codes are available only after the
product completes publishing.

The preferred Folder pilot is therefore:

1. keep the commercial model as paid one-time at the owner-confirmed live
   Partner Center value of JPY 360, with no free trial;
2. use the most restrictive practical pre-release visibility;
3. after certification and limited publishing, verify that Partner Center exposes
   promotional-code ordering for this exact Folder product;
4. if Private Audience is being used, verify live that the owner's tester Microsoft
   account is in the allowed audience and that promo-code redemption is supported
   for the product before relying on that path;
5. redeem one promo code with the dedicated tester Microsoft account;
6. acquire/install the Microsoft Store-delivered signed build at no charge;
7. run final Store-signed physical QA;
8. only after PASS consider a separate public-release submission.

Do not assume a promo code is usable until Partner Center exposes the option for this
published product and the tester account can redeem it.

### Fail-closed fallback

If Private Audience + promo-code acquisition is not available for this non-game
product, STOP before paying for the app.

Do not purchase the product just to unblock QA.

Instead, present the live Partner Center options to the owner. The documented
alternative beta route for Windows apps is a non-discoverable/stop-acquisition
configuration where acquisition is allowed through promotional codes. Changing
visibility from Private Audience to that route is an external configuration change
and requires separate owner approval because the confidentiality properties differ.

Do not silently change the product price to Free as a workaround.

## Local conveyor entrypoint before Store upload

The reusable local pre-upload entrypoint is:

```text
scripts/run_store_preupload_readiness.ps1
```

For Folder, use the frozen package path and `SourceCheckoutMode=ContainedCommit`.
This allows the current local Folder worktree to contain later Store metadata/runbook
commits while keeping the package source SHA frozen. The script still requires the
frozen source commit to exist in local Git history and to be an ancestor of the
current HEAD; it never changes the package bytes or source SHA.

The wrapper performs only local/read-only work:

1. exact package existence and SHA verification;
2. MSIX unpack + Manifest/EXE identity/hash verification;
3. exact Draft binding verification in the handoff;
4. optional Store-assets directory presence check;
5. emits one deterministic readiness receipt.

It can return:

- `HOLD_LOCAL_MSIX_NOT_FOUND`
- `HOLD_LOCAL_MSIX_SHA_MISMATCH`
- `HOLD_SUBMISSION_RECONCILE_REQUIRED`
- `HOLD_EXACT_PACKAGE_MISMATCH`
- `HOLD_STORE_ASSETS`
- `READY_FOR_MSIX_UPLOAD_APPROVAL`

It never uploads a package, submits certification, or publishes.

## Pilot sequence

### Gate 1 — initial Draft

Preconditions immediately before write:

- exact Store ID/Identity/Publisher still match;
- state is `EXISTING_PRODUCT_INITIAL_SUBMISSION`;
- exactly one visible `Start submission` control;
- no active package exists.

Permitted write: click `Start submission` once.

Not permitted by this gate:

- package upload;
- price write;
- certification submit;
- publish;
- public-audience change.

After click, require `EXISTING_PRODUCT_DRAFT_PRESENT` and a concrete Draft ID.
Ambiguous result => HOLD, no blind retry.

### Gate 2 — read Draft fields

Read-only inspect:

- Packages section;
- Pricing and availability;
- Visibility / audience options;
- Known User Group requirements;
- exact price choices;
- 7-day trial option;
- certification/publishing options;
- whether promotional-code acquisition is compatible with the intended limited
  release path.

No field writes during this inspection.

### Gate 3 — Store configuration

After owner review, configure the selected limited-release path. Keep manual publish
holds and avoid general-public exposure.

The exact price/tier must come from live Partner Center; never infer it.

### Gate 4 — package upload

Before upload, re-hash the local MSIX and require the frozen SHA above.

Package upload requires its own execution-time owner approval.

After upload, verify Store-side package acceptance, Identity, version and
architecture. Do not submit certification automatically.

### Gate 5 — certification

Certification submission requires a separate execution-time approval.

Keep the selected limited-release visibility. Certification approval is not public
release approval.

### Gate 6 — limited publishing and no-cost acquisition

Limited publishing is a separate external write and requires explicit approval.

After the Store product completes publishing:

- verify promotional codes are available for the exact Folder product;
- create/order only the minimum test code(s) required;
- redeem with the owner-approved tester Microsoft account;
- verify acquisition cost is zero before completing acquisition;
- install from Microsoft Store;
- confirm the delivered package is Microsoft-trusted and matches the expected Store
  product Identity/version.

If a paid purchase screen would charge money, STOP. Do not complete the purchase.

### Gate 7 — Store-signed physical QA

Required:

- Store delivery verified;
- trusted Microsoft Store signature path verified;
- JP UI;
- EN UI;
- DPI 100 / 125 / 150;
- preview;
- Dry Run;
- approval;
- copy;
- move;
- no-overwrite;
- symlink rejection;
- junction rejection;
- source/destination safety;
- restart;
- normal exit.

Bind PASS with `store-signed-install-qa-receipt/1`.

### Gate 8 — public sale

Only after `qa.store_signed_install_pass=true`:

- review exact paid price;
- review 7-day trial;
- review listing/assets/security;
- create a separate public-release submission;
- require a separate explicit owner approval before Public audience / Publish.

## Game-pipeline guidance reused here

The AI-Game-Factory GDK documents are not a generic app publishing route and must not
be used to send Folder through GDK/MSIXVC.

Only these principles are reused:

- immutable source/package provenance;
- exact artifact hashes;
- no rebuilt package substitution;
- fail closed on mismatched state;
- package/certification/publish evidence must reflect real external state;
- a check-only/test gate never authorizes the next Store write.

## Current disposition

`PRIVATE_STORE_SIGNING_QA`

The next external write remains `Start submission` only, after direct
execution-time owner approval.
