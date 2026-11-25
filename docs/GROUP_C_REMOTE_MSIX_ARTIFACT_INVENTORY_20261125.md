# Remote MSIX Artifact Inventory — 2026-11-25

## Scope and handling

This inventory records GitHub Actions artifact metadata and exact workflow source revisions discovered from the product repositories. Artifact IDs, names, sizes, run URLs, source SHAs, and job-step outcomes were read from GitHub's Actions API.

The MSIX binaries themselves were **not downloaded or independently re-hashed in this GitHub-side operation**. However, the exact MSIX SHA-256 values printed by the corresponding GitHub Actions builder logs or generated handoff were captured and recorded as `BUILDER_REPORTED_HASH`. These are provenance-linked hashes, not an independent local byte-for-byte verification. Re-download and re-hash the artifact locally before relying on the package. The QA artifacts below are unsigned and/or use temporary placeholder logos; none is authorized for Partner Center upload.

The Group B/C registries are the machine-readable source of truth for these observations. This document explains why each artifact is or is not reusable.

## Product status

| Product | Run / source revision | Artifact | Current classification |
|---|---|---|---|
| Workflow Automation Hub | Run 44093505473; `f2ba58895492f0c64da7676b17edfc97e98330e7` | Artifact 14332647613; 36,603,062 bytes; MSIX 1.0.0.0; SHA `512da1ab4449a69b02901baf9c8eaff6577f1e58d336f43ef608f4fbc3892a97` | Source-bound unsigned technical draft; version 1.0.0.0 is not owner-approved |
| Data Contract Auditor | Run 45103784990; candidate source `5a09d81955e25664761ea25ecfb4ebf8d24cea6d`; current branch head `0c73a746bcec9ded702567768d5c04f4240a12a9`; required `107e59f2cbcde9c6ca88cf1aaf3d52262004e6e0` | Artifact 14787075908; 55,190,196 bytes; MSIX 1.0.0.0; SHA `80cd02c0df8e75d1962d03ce63c1ba72d9a8f67e8056f43718ffc5bd8d3f3279` | Unsigned candidate build succeeded but source revision does not match required source; current branch CI fails before packaging |
| AI Upload Guard | Run 44687824883; `fcb0e5793cef78d974e71fef8169c9f7d626257e` | Artifact 14607745398; 21,569,997 bytes; MSIX 1.0.60.0; SHA `1141D327F43EC0F846BF780D3D0C68B82AC261DD869A7A54FDBB31C70F8B6125` | QA_UNSIGNED validation only; formal Store candidate step skipped |
| Image Privacy Cleaner | Run 44687836979; `b73f2dadd63843cadb9c1a779a87ef2045516af5` | Artifact 14607755190; 21,824,223 bytes; MSIX 1.0.50.0; SHA `90396A9097B1E7B570B5CFEF4B9A45A93958733636ADFE47C1AA71CDE7E29800` | QA_UNSIGNED validation only; formal Store candidate step skipped |
| Excel / CSV Privacy Cleaner | Run 44687814041; `f715ce0e6f5d3eee8e483137fb42d41cb6e4ec20` | Artifact 14607382071; 13,194,740 bytes; MSIX 1.0.57.0; SHA `18C4F841DF4C3DAFFEEBD068D001287BAA4BFC2876CE1C2558EAB258351CC79D` | QA_UNSIGNED validation only; formal Store candidate step skipped |
| PDF Privacy | Run 44687829990; `891dad28b15b5c1c7dd743e6cbe44280959ecb41` | Artifact 14607132432; 17,722,226 bytes; MSIX 1.0.54.0; SHA `3911348B502AFB133BEB07D3AB1C9070A7F68FE3ED05772D027C38C040678ED9` | QA_UNSIGNED validation only; formal Store candidate step skipped |
| Web Evidence Archiver | Run 44687808856; Store packaging source `3f2de607d83f36abef6d9a87da1a1c8b3bca604a` | Artifact 14607965112; 415,899,027 bytes; MSIX 1.0.55.0; SHA `91fae107652539bad0c0bdc30e9ae1891542c1a92f2460218e1be24af987cebe` | QA_UNSIGNED structural/preflight artifact only; GUI and Store branches diverged |

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

The run log emitted generated handoff hash `512da1ab4449a69b02901baf9c8eaff6577f1e58d336f43ef608f4fbc3892a97` for `WorkflowAutomationHub_1.0.0.0_x64_StoreDraft_UNSIGNED.msix`. This is the hash stored in the generated handoff; download the artifact and independently recompute it locally.

The source manifest explicitly labels version `1.0.0.0` as a technical draft only, states that the accepted Store version history is not verified, says temporary technical logos must be replaced, and sets `submission_allowed=false`. The current Partner Center observation shows no Submission and an available `Start submission` control; it was not clicked.

This is the best-provenanced remote MSIX candidate found so far, but it is not a release package. Download the artifact locally, extract the handoff and SHA file, verify the binary digest, and keep it as a QA/inspection candidate only.

Workflow: https://github.com/shihuiarenjinba-png/workflow-automation-hub/actions/runs/44093505473

### Data Contract Auditor

The formal candidate gate records:
- QA baseline source SHA: `107e59f2cbcde9c6ca88cf1aaf3d52262004e6e0`;
- formal candidate source SHA: `5a09d81955e25664761ea25ecfb4ebf8d24cea6d`.

The 107e commit is the QA baseline, not the required formal package revision. The formal source is 40 commits after that baseline. Run `45103784990` used the exact formal candidate source SHA `5a09...` and built the unsigned Store candidate.

Artifacts:
- `data-contract-QA_UNSIGNED-msix-45103784990` — ID `14787075908`, 55,190,196 bytes;
- `data-contract-QA_UNSIGNED-validation-msix-45103784990-1` — ID `14787095933`, 55,176,827 bytes.

The candidate file was `DataContractSchemaDrift_1.0.0.0_x64.msix`; the builder log emitted SHA `80cd02c0df8e75d1962d03ce63c1ba72d9a8f67e8056f43718ffc5bd8d3f3279`.

The current source branch HEAD at the time of this update was `0c73a746bcec9ded702567768d5c04f4240a12a9`, two metadata-only commits after the formal build source. The app runtime and packaging scripts did not change after `5a09...`. The failed CI run `45107287117` was caused by a stale product-profile test: it expected pre-build state `READY_FOR_FORMAL_MSIX_BUILD` after the profile had advanced to `READY_FOR_PARTNER_CENTER_READONLY` and `FORMAL_UNSIGNED_MSIX_CREATED_AND_VERIFIED`.

That stale test has been corrected on the DCA source branch to assert the recorded post-build read-only state and bind it to the formal candidate gate. New CI run `45580565845` is testing the correction.

The candidate is still unsigned and is not upload authorization. The exact artifact must be downloaded and independently re-hashed, its manifest/source receipt inspected, and package-level local QA bound to that exact binary SHA. Re-read the current Partner Center Draft and Packages state before any upload.

Workflow: https://github.com/shihuiarenjinba-png/csv-import-validator/actions/runs/45103784990

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

These packages can support local technical QA or candidate inspection only. The placeholder assets, unsigned state, and unapproved version prevent promotion to a Store upload candidate.

Workflows:
- AI Upload Guard: https://github.com/shihuiarenjinba-png/-AI-Upload-Guard-AI-/actions/runs/44687824883
- Image Privacy Cleaner: https://github.com/shihuiarenjinba-png/-Screenshot-Image-Privacy-Cleaner/actions/runs/44687836979
- Excel / CSV Privacy Cleaner: https://github.com/shihuiarenjinba-png/-Excel-CSV-Privacy-Cleaner/actions/runs/44687814041
- PDF Privacy: https://github.com/shihuiarenjinba-png/-PDF-Privacy-Toolkit/actions/runs/44687829990

### Web Evidence Archiver

Store packaging branch:
- `codex/store-p0-web-evidence-20261023`
- `3f2de607d83f36abef6d9a87da1a1c8b3bca604a`
- workflow run `44687808856`
- QA artifact `web-evidence-QA_UNSIGNED-validation-msix-44687808856-1`, ID `14607965112`, 415,899,027 bytes.

The inspection and QA unsigned structural MSIX jobs succeeded, while the formal unsigned candidate job was skipped. The builder emitted MSIX SHA `91fae107652539bad0c0bdc30e9ae1891542c1a92f2460218e1be24af987cebe` for `WebEvidenceArchiver_QA_UNSIGNED_1.0.55.0_x64.msix`, EXE SHA `a243aa2a5aaf9c067f4f550621d26ae013301a3c90f329eeca004deecef8fa99`, and browser bundle tree SHA `751c3f638d890a1764badfa234a40ae4f2db348ad57bbf032ceb14b3d0b3c921`.

Preflight blockers include missing approved Store version, empty manifest resources, and missing browser bundle approval.

The latest GUI branch is `codex/web-evidence-gui-progress-20261124` at `fd34b93068d5ea39e3a02e89dc1c8c3d9bcb0812`. The two branches diverged: GUI branch is 7 commits ahead and 76 behind the Store branch, with common ancestor `0f1537e33c6f5b3e79d034ad92865a162ee36275`.

Do not package or upload from either old branch alone. Integrate GUI changes into the Store packaging branch, preserve the Store-specific packaging/licensing work, and rerun all QA/preflight gates on the integrated source.

Workflow: https://github.com/shihuiarenjinba-png/web-evidence-archiver/actions/runs/44687808856

## Local artifact download commands

After GitHub network access and CLI authentication are restored, download the exact named artifacts into a dedicated evidence directory. Example PowerShell commands:

```powershell
gh run download 44093505473 -R shihuiarenjinba-png/workflow-automation-hub -n WorkflowAutomationHub-Store-MSIX-UNSIGNED-DRAFT -D C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\remote-artifacts\workflow-automation-hub

gh run download 45103784990 -R shihuiarenjinba-png/csv-import-validator -n data-contract-QA_UNSIGNED-msix-45103784990 -D C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\remote-artifacts\data-contract-auditor

gh run download 44687824883 -R shihuiarenjinba-png/-AI-Upload-Guard-AI- -n group-c-QA_UNSIGNED-validation-msix-44687824883-1 -D C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\remote-artifacts\ai-upload-guard

gh run download 44687836979 -R shihuiarenjinba-png/-Screenshot-Image-Privacy-Cleaner -n group-c-QA_UNSIGNED-validation-msix-44687836979-1 -D C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\remote-artifacts\image-privacy-cleaner

gh run download 44687814041 -R shihuiarenjinba-png/-Excel-CSV-Privacy-Cleaner -n group-c-QA_UNSIGNED-validation-msix-44687814041-1 -D C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\remote-artifacts\excel-csv-privacy-cleaner

gh run download 44687829990 -R shihuiarenjinba-png/-PDF-Privacy-Toolkit -n group-c-QA_UNSIGNED-validation-msix-44687829990-1 -D C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\remote-artifacts\pdf-privacy

gh run download 44687808856 -R shihuiarenjinba-png/web-evidence-archiver -n web-evidence-QA_UNSIGNED-validation-msix-44687808856-1 -D C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\remote-artifacts\web-evidence-archiver
```

After downloading:
1. Recompute SHA-256 for every MSIX; compare to the builder-reported value above and any included `msix.sha256.txt` or validation receipt. A mismatch must stop the candidate.
2. Verify Package Identity, Publisher, Version, Architecture, and exact Source Revision from the embedded manifest/handoff.
3. Distinguish the QA placeholder-logo artifacts from formal Store candidates.
4. Do not upload unsigned/QA candidates. This is evidence collection and local verification only.

## Safety boundary

No Product or Submission was created. No package was uploaded or saved in Partner Center. No price or market settings were changed. No Certification or Publish action was performed. Artifact discovery does not equal Store authorization.
