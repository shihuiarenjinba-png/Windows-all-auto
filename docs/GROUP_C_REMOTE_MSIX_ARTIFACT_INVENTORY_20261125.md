# Remote MSIX Artifact Inventory — 2026-11-25

## Scope and handling

This inventory records GitHub Actions artifact metadata and exact workflow source revisions discovered from the product repositories. Artifact IDs, names, sizes, run URLs, source SHAs, and job-step outcomes were read from GitHub's Actions API.

The MSIX binaries themselves were **not downloaded or hashed in this GitHub-side operation**. Every `package_sha256` field therefore remains unclaimed until the exact artifact is downloaded and inspected locally. The QA artifacts below are unsigned and/or use temporary placeholder logos; none is authorized for Partner Center upload.

The Group B/C registries are the machine-readable source of truth for these observations. This document explains why each artifact is or is not reusable.

## Product status

| Product | Run / source revision | Artifact | Current classification |
|---|---|---|---|
| Workflow Automation Hub | Run 44093505473; `f2ba58895492f0c64da7676b17edfc97e98330e7` | Artifact 14332647613; 36,603,062 bytes | Source-bound unsigned technical draft; version 1.0.0.0 is not owner-approved |
| Data Contract Auditor | Run 45103784990; candidate source `5a09d81955e25664761ea25ecfb4ebf8d24cea6d` vs required `107e59f2cbcde9c6ca88cf1aaf3d52262004e6e0` | Artifact 14787075908; 55,190,196 bytes | Unsigned candidate build succeeded but source revision does not match required source |
| AI Upload Guard | Run 44687824883; `fcb0e5793cef78d974e71fef8169c9f7d626257e` | Artifact 14607745398; 21,569,997 bytes | QA_UNSIGNED validation only; formal Store candidate step skipped |
| Image Privacy Cleaner | Run 44687836979; `b73f2dadd63843cadb9c1a779a87ef2045516af5` | Artifact 14607755190; 21,824,223 bytes | QA_UNSIGNED validation only; formal Store candidate step skipped |
| Excel / CSV Privacy Cleaner | Run 44687814041; `f715ce0e6f5d3eee8e483137fb42d41cb6e4ec20` | Artifact 14607382071; 13,194,740 bytes | QA_UNSIGNED validation only; formal Store candidate step skipped |
| PDF Privacy | Run 44687829990; `891dad28b15b5c1c7dd743e6cbe44280959ecb41` | Artifact 14607132432; 17,722,226 bytes | QA_UNSIGNED validation only; formal Store candidate step skipped |
| Web Evidence Archiver | Run 44687808856; Store packaging source `3f2de607d83f36abef6d9a87da1a1c8b3bca604a` | Artifact 14607965112; 415,899,027 bytes | QA_UNSIGNED structural/preflight artifact only; GUI and Store branches diverged |

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

The source manifest explicitly labels version `1.0.0.0` as a technical draft only, states that the accepted Store version history is not verified, says temporary technical logos must be replaced, and sets `submission_allowed=false`. The current Partner Center observation shows no Submission and an available `Start submission` control; it was not clicked.

This is the best-provenanced remote MSIX candidate found so far, but it is not a release package. Download the artifact locally, extract the handoff and SHA file, verify the binary digest, and keep it as a QA/inspection candidate only.

Workflow: https://github.com/shihuiarenjinba-png/workflow-automation-hub/actions/runs/44093505473

### Data Contract Auditor

The successful candidate build run `45103784990` used candidate source `5a09d81955e25664761ea25ecfb4ebf8d24cea6d`. The Group C required source remains `107e59f2cbcde9c6ca88cf1aaf3d52262004e6e0`.

Artifacts:
- `data-contract-QA_UNSIGNED-msix-45103784990` — ID `14787075908`, 55,190,196 bytes;
- `data-contract-QA_UNSIGNED-validation-msix-45103784990-1` — ID `14787095933`, 55,176,827 bytes.

The build job succeeded, but the candidate source revision is not the required registered source revision. The package is unsigned and remains blocked from upload. Compare the downloaded manifest, embedded source receipt, and package SHA to the required branch before deciding whether to rebuild.

Workflow: https://github.com/shihuiarenjinba-png/csv-import-validator/actions/runs/45103784990

### AI Upload Guard, Image Privacy Cleaner, Excel / CSV Privacy Cleaner, and PDF Privacy

Each product has a successful Windows portable prerequisite and a QA-only unsigned MSIX artifact. The workflow generates temporary placeholder logos for this QA lane.

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

The inspection and QA unsigned structural MSIX jobs succeeded, while the formal unsigned candidate job was skipped. Preflight blockers include missing approved Store version, empty manifest resources, and missing browser bundle approval.

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
1. Recompute SHA-256 for every MSIX; compare to any included `msix.sha256.txt` or validation receipt.
2. Verify Package Identity, Publisher, Version, Architecture, and exact Source Revision from the embedded manifest/handoff.
3. Distinguish the QA placeholder-logo artifacts from formal Store candidates.
4. Do not upload unsigned/QA candidates. This is evidence collection and local verification only.

## Safety boundary

No Product or Submission was created. No package was uploaded or saved in Partner Center. No price or market settings were changed. No Certification or Publish action was performed. Artifact discovery does not equal Store authorization.
