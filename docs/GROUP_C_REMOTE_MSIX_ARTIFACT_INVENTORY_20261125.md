# Remote MSIX Artifact Inventory — 2026-11-25

## Scope and handling

This inventory records GitHub Actions artifact metadata and exact workflow source revisions discovered from the product repositories. Artifact IDs, names, sizes, run URLs, source SHAs, and job-step outcomes were read from GitHub's Actions API.

Local verification was subsequently completed by the operator on 2026-11-25. All seven downloaded MSIX binaries' locally computed SHA-256 values match the builder-reported values, and each manifest's Identity, Publisher, Version, and Architecture was checked. All seven packages report `NotSigned`. This GitHub connector did not independently inspect the local Windows files; the verification is transcribed from the operator's `LOCAL_PACKAGE_REHASH_REPORT.json`, `PACKAGE_INVENTORY.json`, `FINAL_REPORT.md`, and `SHA256SUMS.txt`. A hash/manifest pass proves file integrity and identity metadata, not installability, runtime QA, owner approval, or Store upload readiness.

The Group B/C registries are the machine-readable source of truth for these observations. This document explains why each artifact is or is not reusable.

## Product status

| Product | Run / source revision | Artifact | Current classification |
|---|---|---|---|
| Workflow Automation Hub | Run 44093505473; `f2ba58895492f0c64da7676b17edfc97e98330e7` | Artifact 14332647613; 36,603,062 bytes; MSIX 1.0.0.0; SHA `512da1ab4449a69b02901baf9c8eaff6577f1e58d336f43ef608f4fbc3892a97` | Source-bound unsigned technical draft; version 1.0.0.0 is not owner-approved |
| Data Contract Auditor | Run 45580565845; source `722ec7a077d2c6109e657c4ee661c9f3d06a4506` | Artifact 15005358857; 55,210,542 bytes; MSIX 1.0.0.0; SHA `e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05`; local SHA matches | Unsigned candidate; Manifest verified; local install Access Denied and EXE launch timed out; functional QA incomplete |
| AI Upload Guard | Run 44687824883; `fcb0e5793cef78d974e71fef8169c9f7d626257e` | Artifact 14607745398; 21,569,997 bytes; MSIX 1.0.60.0; SHA `1141D327F43EC0F846BF780D3D0C68B82AC261DD869A7A54FDBB31C70F8B6125` | QA_UNSIGNED validation only; formal Store candidate step skipped |
| Image Privacy Cleaner | Run 44687836979; `b73f2dadd63843cadb9c1a779a87ef2045516af5` | Artifact 14607755190; 21,824,223 bytes; MSIX 1.0.50.0; SHA `90396A9097B1E7B570B5CFEF4B9A45A93958733636ADFE47C1AA71CDE7E29800` | QA_UNSIGNED validation only; formal Store candidate step skipped |
| Excel / CSV Privacy Cleaner | Run 44687814041; `f715ce0e6f5d3eee8e483137fb42d41cb6e4ec20` | Artifact 14607382071; 13,194,740 bytes; MSIX 1.0.57.0; SHA `18C4F841DF4C3DAFFEEBD068D001287BAA4BFC2876CE1C2558EAB258351CC79D` | QA_UNSIGNED validation only; formal Store candidate step skipped |
| PDF Privacy | Run 44687829990; `891dad28b15b5c1c7dd743e6cbe44280959ecb41` | Artifact 14607132432; 17,722,226 bytes; MSIX 1.0.54.0; SHA `3911348B502AFB133BEB07D3AB1C9070A7F68FE3ED05772D027C38C040678ED9` | QA_UNSIGNED validation only; formal Store candidate step skipped |
| Web Evidence Archiver | Run 44687808856; source `3f2de607d83f36abef6d9a87da1a1c8b3bca604a` (pre-integration) | Artifact 14607965112; 415,899,027 bytes; MSIX 1.0.55.0; SHA `91fae107652539bad0c0bdc30e9ae1891542c1a92f2460218e1be24af987cebe`; local SHA matches | QA_UNSIGNED only; local integration commit `2516feedd5b10990fbe5c8184587e3b69214648d` is unpushed; 41 tests + compile pass, but example capture timed out and formal preflight is HOLD |

All seven artifact records are also reflected in `ops/group_b_standard_store_products.json` or `ops/group_c_store_products.json`.

## Detailed findings

### Workflow Automation Hub

The current branch `codex/hub-standard-consumer-ui-20261113` is at `f2ba58895492f0c64da7676b17edfc97e98330e7`. The successful Windows workflow run `44093505473` used this exact branch HEAD.

The workflow:
- ran unit tests and source / packaged EXE self-tests;
- built an unsigned Store MSIX draft;
- verified the manifest identity and MakeAppx pack/unpack roundtrip;
- generated `store-product-handoff.json`;
- uploaded the MSIX, `msix_validation.json`, and `msix.sha256.txt` in one artifact.

Related artifacts:
- `WorkflowAutomationHub-Store-MSIX-UNSIGNED-DRAFT` — ID `14332647613`, 36,603,062 bytes;
- `WorkflowAutomationHub-Windows` — ID `14331959551`, 36,410,296 bytes;
- `WorkflowAutomationHub-GUI-Review` — ID `14331614716`, 212,696 bytes.

The run log emitted generated handoff hash `512da1ab4449a69b02901baf9c8eaff6577f1e58d336f43ef608f4fbc3892a97` for `WorkflowAutomationHub_1.0.0.0_x64_StoreDraft_UNSIGNED.msix`. The operator reports that the binary was downloaded and its local SHA matches this value; Manifest Identity, Publisher, Version, and Architecture checks also passed. Signature status is `NotSigned`.

The source manifest explicitly labels version `1.0.0.0` as a technical draft only, states that the accepted Store version history is not verified, says temporary technical logos must be replaced, and sets `submission_allowed=false`. The local verification phase did not live-recheck Partner Center, so current Submission state remains unverified. No Submission was started.

This is an unsigned technical draft with its binary hash and manifest checked, not a commercial release package. Owner Version/asset approval and a fresh read-only Partner Center check are still required before any potential submission.

Workflow: https://github.com/shihuiarenjinba-png/workflow-automation-hub/actions/runs/44093505473

### Data Contract Auditor

The QA baseline source SHA is `107e59f2cbcde9c6ca88cf1aaf3d52262004e6e0`; it is not the formal candidate source requirement. A formal unsigned candidate was successfully built from source HEAD `722ec7a077d2c6109e657c4ee661c9f3d06a4506` in run `45580565845`.

The build passed source tests, compile, Store readiness preflight, pack, unpack, and MSIX verification.

Latest formal candidate:
- Artifact: `data-contract-QA_UNSIGNED-msix-45580565845` — ID `15005358857`, 55,210,542 bytes.
- Package: `DataContractSchemaDrift_1.0.0.0_x64.msix`; Version `1.0.0.0`; Architecture x64.
- Source SHA: `722ec7a077d2c6109e657c4ee661c9f3d06a4506`.
- EXE SHA-256: `b47219821bdaa9d3138b49dc4a00645190b6f6f3e7f90fa9e014fb5b93f7c1f5`.
- MSIX SHA-256: `e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05`; operator-reported local SHA matches.
- Signature: `NotSigned`; Manifest Identity/Publisher/Version/Architecture checks PASS.
- Local install attempt: ACCESS DENIED.
- EXE launch attempt: TIMEOUT.
- Functional package QA: incomplete; do not infer an application defect solely from the access-denied result without examining Windows policy / install logs.

The post-build profile test had been stale and was corrected. Run `45580565845` passed source tests, compile, preflight, formal build and QA structural build.

The binary hash is now verified locally against the builder value, but runtime QA is blocked. The Partner Center historical snapshot records Draft `1152921505702212222` with Packages `Incomplete`; Partner Center was not live-rechecked in this local phase. No upload is authorized.

Workflow: https://github.com/shihuiarenjinba-png/csv-import-validator/actions/runs/45580565845

### AI Upload Guard, Image Privacy Cleaner, Excel / CSV Privacy Cleaner, and PDF Privacy

Each product has a successful Windows portable prerequisite and a QA-only unsigned MSIX artifact. The workflow generates temporary placeholder logos for this QA lane.

The QA builder logs emitted these MSIX values:
- AI Upload Guard — `AIUploadGuard_QA_UNSIGNED_1.0.60.0_x64.msix`; SHA `1141D327F43EC0F846BF780D3D0C68B82AC261DD869A7A54FDBB31C70F8B6125`.
- Image Privacy Cleaner — `ImagePrivacyCleaner_QA_UNSIGNED_1.0.50.0_x64.msix`; SHA `90396A9097B1E7B570B5CFEF4B9A45A93958733636ADFE47C1AA71CDE7E29800`.
- Excel / CSV Privacy Cleaner — `ExcelCSVPrivacyCleaner_QA_UNSIGNED_1.0.57.0_x64.msix`; SHA `18C4F841DF4C3DAFFEEBD068D001287BAA4BFC2876CE1C2558EAB258351CC79D`.
- PDF Privacy — `PDFPrivacyToolkit_QA_UNSIGNED_1.0.54.0_x64.msix`; SHA `3911348B502AFB133BEB07D3AB1C9070A7F68FE3ED05772D027C38C040678ED9`.

For Image, Excel/CSV, and PDF, the workflow's formal Store candidate steps were skipped because:
- `approved_store_version` is null;
- `package_version_approval` is `UNKNOWN`;
- `brand_assets_approval` is `UNKNOWN`;
- an owner-approved `store-assets/approval.json` is missing or not approved.

AI Upload Guard's current November 20 run follows the same gating pattern: the QA-only unsigned package step succeeded, while the formal Store candidate build and preservation steps were skipped.

All four local MSIX hashes match their builder-reported hashes; each Manifest Identity/Publisher/Version/Architecture check passed. All remain `NotSigned` and classified QA_UNSIGNED. AI Upload Guard runtime QA is not verified; Image, Excel/CSV, and PDF still lack owner-approved formal Store Version and artwork. Hash/Manifest integrity does not promote these packages to formal Store candidates.

Workflows:
- AI Upload Guard: https://github.com/shihuiarenjinba-png/-AI-Upload-Guard-AI-/actions/runs/44687824883
- Image Privacy Cleaner: https://github.com/shihuiarenjinba-png/-Screenshot-Image-Privacy-Cleaner/actions/runs/44687836979
- Excel / CSV Privacy Cleaner: https://github.com/shihuiarenjinba-png/-Excel-CSV-Privacy-Cleaner/actions/runs/44687814041
- PDF Privacy: https://github.com/shihuiarenjinba-png/-PDF-Privacy-Toolkit/actions/runs/44687829990

### Web Evidence Archiver

The QA Store package was built from the pre-integration Store branch:
- `codex/store-p0-web-evidence-20261023`
- source `3f2de607d83f36abef6d9a87da1a1c8b3bca604a`
- workflow run `44687808856`
- artifact `web-evidence-QA_UNSIGNED-validation-msix-44687808856-1`, ID `14607965112`, 415,899,027 bytes
- package `WebEvidenceArchiver_QA_UNSIGNED_1.0.55.0_x64.msix`, SHA `91fae107652539bad0c0bdc30e9ae1891542c1a92f2460218e1be24af987cebe`

The operator downloaded this artifact and locally recomputed the same SHA. Manifest Identity, Publisher, Version, and Architecture checks passed. The package remains unsigned and reflects the **old Store branch**, not the subsequently integrated GUI source.

The operator reports a local merge/integration commit:
- commit `2516feedd5b10990fbe5c8184587e3b69214648d`
- 41 tests passed; compileall passed
- commit not pushed; remote CI not run; no PR created yet.

GUI launch succeeded, but an actual `example.com` capture did not: the CLI timed out and no output files were created. Therefore real end-to-end capture QA is not complete.

Formal Store preflight remains HOLD because approved Version, owner-approved logos/assets, manifest language settings, Chromium bundle approval, and successful offline/runtime capture QA are not all present. The next package must be rebuilt from the integrated commit only after the local branch is pushed/reviewed and the runtime capture blocker is resolved.

Workflow for the old package: https://github.com/shihuiarenjinba-png/web-evidence-archiver/actions/runs/44687808856

## Local package verification — operator-reported complete

The operator reports that all seven downloaded MSIX binaries were locally re-hashed and matched the recorded builder SHA-256 values. All seven manifests also passed Identity, Publisher, Version, and Architecture checks. All seven signatures are `NotSigned`.

| Product | Version | Local SHA-256 | Package verification / remaining runtime gate |
|---|---:|---|---|
| AI Upload Guard | 1.0.60.0 | `1141d327f43ec0f846bf780d3d0c68b82ac261dd869a7a54fdbb31c70f8b6125` | Hash + Manifest PASS; runtime QA not verified |
| Image Privacy Cleaner | 1.0.50.0 | `90396a9097b1e7b570b5cfef4b9a45a93958733636adfe47c1aa71cde7e29800` | Hash + Manifest PASS; formal Version/artwork approval missing |
| Excel / CSV Privacy Cleaner | 1.0.57.0 | `18c4f841df4c3daffeebd068d001287baa4bfc2876ce1c2558eab258351cc79d` | Hash + Manifest PASS; formal Version/artwork approval missing |
| Data Contract Auditor | 1.0.0.0 | `e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05` | Hash + Manifest PASS; install Access Denied, EXE launch timeout, functional QA incomplete |
| PDF Privacy Toolkit | 1.0.54.0 | `3911348b502afb133beb07d3ab1c9070a7f68fe3ed05772d027c38c040678ed9` | Hash + Manifest PASS; formal Version/artwork approval missing |
| Web Evidence Archiver | 1.0.55.0 | `91fae107652539bad0c0bdc30e9ae1891542c1a92f2460218e1be24af987cebe` | Hash + Manifest PASS; actual capture timed out, old pre-integration package only |
| Workflow Automation Hub | 1.0.0.0 | `512da1ab4449a69b02901baf9c8eaff6577f1e58d336f43ef608f4fbc3892a97` | Hash + Manifest PASS; technical draft, owner approval and Submission state not verified live |

Evidence supplied by the operator:
- `LOCAL_PACKAGE_REHASH_REPORT.json`
- `PACKAGE_INVENTORY.json`
- `LOCAL_PACKAGE_QA_REPORT.json`
- `SHA256SUMS.txt`
- `FINAL_REPORT.md`

The report set has been preserved locally under `C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\`. This GitHub update records the operator-reported result; it does not independently reproduce the local rehash.

## Local WEA integration result

WEA's local integration commit is `2516feedd5b10990fbe5c8184587e3b69214648d`. Local integration tests passed 41/41 and compileall passed. The commit remains unpushed, with no PR and no remote CI. The actual capture timed out with no output files. Formal preflight remains HOLD. The old verified package SHA above belongs to the pre-integration Store branch and must not be treated as a package built from commit `2516fe...`.

## Partner Center and release boundary

Partner Center was not live-rechecked in this local verification phase. Existing Product/Draft information is only the historical read-only snapshot from `2026-11-25T07:52:09Z`. No package upload, Packages Save, Certification, Publish, or Submission start occurred. All seven packages are unsigned, so none is ready for commercial upload.

## Safety boundary

No Product or Submission was created. No package was uploaded or saved in Partner Center. No price or market settings were changed. No Certification or Publish action was performed. Artifact discovery does not equal Store authorization.
