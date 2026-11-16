# Group B standard apps — GitHub handoff

Updated: 2026-11-16 JST

## Purpose

Advance the four standard Group B Windows apps from validated GitHub/MSIX engineering
candidates into the controlled Microsoft Store pipeline. This handoff is GitHub-side
coordination only.

Do NOT:

- merge main/release branches;
- modify Windows security policy or certificate stores;
- create/modify Partner Center products without the explicit gate for that action;
- upload a package, edit pricing, submit certification, or publish merely because a
  repository file says it is approved;
- mix any `-2` consumer repositories with these standard products.

## Priority order

1. Folder Automation Engine
2. Scheduled API Runner
3. Workflow Automation Hub
4. Browser Automation Runner

The goal is to open one complete Store conveyor with Folder first, then reuse the
verified path for the remaining products.

## 1. Folder Automation Engine — Store execution lane

Repository: `shihuiarenjinba-png/folder-automation-engine`  
PR: #10  
Branch: `codex/folder-standard-consumer-ui-20261026`

Frozen upload candidate:

- product source: `51597b389384be6cf2b3d85c09ee66099b80807e`
- Store ID: `9P99MJX1R4V6`
- version: `1.0.0.0`
- MSIX SHA256: `911f8eb13abfdbb51bea8f279006d138d6be9cba4a25413416c1d70458676450`
- EXE SHA256: `d53161ea1119445afb8070d989d4a72e8019895b8c5e166738a3e38718b54976`

Product engineering before the latest metadata-only documentation update:

- PR #10 exact-head workflows all SUCCESS;
- Windows Store build: 87 tests PASS;
- GUI startup evidence PASS;
- JP/EN Store capture PASS at 1366×768+;
- MSIX pack/unpack, manifest identity, source binding and EXE roundtrip PASS.

The frozen product source to the later metadata head contains Store metadata/runbook
changes only. Do not rebuild the product solely because those metadata files changed.

Required next local steps:

1. sync Folder, Windows-all-auto and Windows-Automator worktrees to their required heads;
2. run local tests;
3. verify the frozen MSIX SHA exactly;
4. re-read Partner Center submission state;
5. require `EXISTING_PRODUCT_INITIAL_SUBMISSION`;
6. obtain direct execution-time approval for exactly one `Start submission` write;
7. create one initial Draft and bind the receipt;
8. read price/category/customer-group/security values without saving;
9. complete owner-confirmed fields;
10. run VALIDATE_ONLY and DRY_RUN;
11. require a separate approval before package upload.

Certification and Publish remain later independent gates.

## 2. Scheduled API Runner — package lane

Repository: `shihuiarenjinba-png/scheduled-api-runner`  
PR: #8  
Head validated before handoff: `a1f7c09ff9363f73c0e9560f9e389107c477ac26`

Evidence:

- Reliability workflow SUCCESS;
- Windows desktop workflow SUCCESS;
- 79 Windows build tests PASS;
- unsigned Store MSIX `ScheduledApiRunner_1.0.0.0_x64_StoreDraft_UNSIGNED.msix` generated;
- source/manifest/SHA/EXE roundtrip guards PASS.

Commercial position: FREE candidate.

Remaining gates:

- controlled real API GET acceptance;
- Windows Task Scheduler lifecycle acceptance;
- JP/EN Store imagery;
- final Store route and owner-approved free pricing.

Do not upload before the Folder Store lane has proved the shared submission pipeline.

## 3. Workflow Automation Hub — integration lane

Repository: `shihuiarenjinba-png/workflow-automation-hub`  
PR: #12  
Head validated before handoff: `d090ae4c6d51d4412cd9c3687de8c9367e675db5`

Evidence:

- Windows build workflow SUCCESS;
- 100 tests PASS;
- GUI review artifact present;
- source and packaged EXE self-test PASS;
- CycloneDX SBOM and THIRD_PARTY_NOTICES checked;
- unsigned Store MSIX generated and Store identity matched.

Commercial position: FREE candidate.

Remaining gates:

- controlled real Google OAuth;
- Blogger connection;
- Dry Run then controlled test-blog mutation;
- Windows Task Scheduler lifecycle;
- JP/EN Store imagery and free pricing approval.

No live Blogger write is authorized by this handoff.

## 4. Browser Automation Runner — rights lane

Repository: `shihuiarenjinba-png/browser-automation-runner`  
PR: #8  
Head validated before handoff: `0d223d2968a976b2de0edba64822a82499ada977`

Evidence:

- Reliability workflow SUCCESS;
- Windows desktop build SUCCESS;
- 42 Windows build tests PASS;
- Chromium-bundled unsigned Store MSIX generated;
- source/manifest/SHA/EXE roundtrip guards PASS.

Commercial position: FREE candidate.

Hard release hold:

- Playwright/Chromium/FFmpeg redistribution notices and rights review;
- exact customer-readable third-party notices/SBOM;
- final Store imagery and pricing approval.

The CI warning that Chromium rights review is incomplete must remain release-blocking
until the legal/distribution evidence is closed.

## Shared automation contracts

Windows-all-auto:

- branch `codex/msix-commercial-handoff-20261115`;
- commercial Store handoff v2;
- fail-closed translation to Windows-Automator;
- price/trial approval cannot be inferred;
- initial-submission receipt binds only the Draft ID;
- package/certification/publish gates remain separate.

Windows-Automator:

- branch `codex/msix-commercial-contract-20261115`;
- read-only existing-submission inspection;
- owner-gated initial Draft start;
- exact state is re-read immediately before `Start submission`;
- exactly one Start submission control is required;
- ambiguous write outcome is HOLD and must not be blindly retried;
- initial Draft creation cannot upload package, change price, submit certification or publish.

## Completion definition for the next operator

The next operator should not report Group B as "Store conveyor open" until Folder has:

- synced local execution repos;
- local tests PASS;
- frozen package SHA PASS;
- exact Partner Center initial-submission state reverified;
- one initial Draft receipt bound to the exact Store ID/source/package;
- Store fields observed;
- VALIDATE_ONLY PASS;
- DRY_RUN PASS.

Package upload requires its own later approval. Certification and Publish require
separate later approvals.
