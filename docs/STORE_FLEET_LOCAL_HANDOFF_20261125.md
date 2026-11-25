# Store Fleet Sync — Local Handoff — 2026-11-25

## Remote work completed

This handoff is paired with PR #166:

- Repository: `shihuiarenjinba-png/Windows-all-auto`
- Branch: `codex/msix-commercial-handoff-20261115`
- Current recorded head before this handoff document: `b0bac5eb05a9df4f13925ce5ed23b8d3d25f147c`
- PR: https://github.com/shihuiarenjinba-png/Windows-all-auto/pull/166
- State: OPEN / Draft / not merged
- Latest Windows + Ubuntu CI: success on the current code, 379 tests; compile step passed.

Remote changes include:
- 2026-11-25 read-only Partner Center snapshot for all seven products;
- all six existing Group C Submission IDs bound to static registry fields;
- Workflow Automation Hub Product Identity/Publisher confirmed and `draft_id: null` explicitly recorded;
- all seven Store IDs, Identity names, and Publisher values in the appropriate Group B/C registry;
- current source branch SHAs for Image, Excel/CSV, PDF, AI Upload Guard, and Workflow Automation Hub;
- remote QA/unsigned MSIX artifact IDs, names, sizes, builder-reported hashes, versions, and provenance status;
- a fix to Group C Store ID validation: the previous `9P` prefix-only check rejected the confirmed Web Evidence Archiver Store ID `9NNT1B142ZWV`. Validation now accepts `9` followed by 11 uppercase alphanumeric characters;
- regression tests and documentation.

The Partner Center observation is tagged `TRANSCRIBED_FROM_USER_SUPPLIED_FINAL_REPORT`. The local source report and screenshots were not independently attached to this GitHub update. The observed timestamp is `2026-11-25T07:52:09Z`. Re-read Partner Center before every write operation.

## Local branch reported by the operator

The operator reported this local branch/commit, not yet visible in GitHub:

- Branch: `codex/store-fleet-live-identities-20261125`
- Commit: `cb6406f5fe51386ddd2ede1ab3a07b62ac3bb5d1`
- Reported state: clean working tree; 219 tests passed.
- Earlier baseline `72bdbdb9dc34ed1e32b464a01e0c863571c879a4` was preserved.

The local branch appears to add `store_manager/fleet_sync.py`, CLI integration, and the seven live Identity/Submission bindings. It has not been pushed by this GitHub-side work. Before pushing, verify its repository root, remotes, branch ancestry, and diff. Do not force push or overwrite the PR #3 branch.

Suggested local checks:

```powershell
git status --short --branch
git rev-parse --show-toplevel
git remote -v
git show --stat --oneline cb6406f5fe51386ddd2ede1ab3a07b62ac3bb5d1
git merge-base cb6406f5fe51386ddd2ede1ab3a07b62ac3bb5d1 origin/codex/local-store-uploader-forensics-20261124
```

If the commit is based on the Windows-Automator PR #3 head, create a follow-up branch/PR that targets `codex/local-store-uploader-forensics-20261124`. Otherwise, create a clean branch from the current PR #3 head and port only the reviewed fleet-sync changes. Resolve conflicts deliberately; keep the local 219-test implementation and the existing uploader contracts. Do not merge any PR.

## Three missing local source clones

The three products that were not present as local clones have existing GitHub repositories and exact Store packaging branches. Search the existing worktree roots first; clone only when the repository is genuinely absent. Use the Store branch, not the sparse default `main`.

```powershell
$Base = "C:\Users\aaron\Desktop\portfolio-audit\_task_worktrees"
New-Item -ItemType Directory -Force -Path $Base | Out-Null

git clone --branch codex/store-p1-image-privacy-20261023 --single-branch https://github.com/shihuiarenjinba-png/-Screenshot-Image-Privacy-Cleaner.git (Join-Path $Base "image-privacy-cleaner")

git clone --branch codex/store-p1-excel-csv-privacy-20261023 --single-branch https://github.com/shihuiarenjinba-png/-Excel-CSV-Privacy-Cleaner.git (Join-Path $Base "excel-csv-privacy-cleaner")

git clone --branch codex/store-p1-pdf-privacy-20261023 --single-branch https://github.com/shihuiarenjinba-png/-PDF-Privacy-Toolkit.git (Join-Path $Base "pdf-privacy-toolkit")
```

Pinned Store branch heads at discovery time:
- Image Privacy Cleaner: `b73f2dadd63843cadb9c1a779a87ef2045516af5`
- Excel / CSV Privacy Cleaner: `f715ce0e6f5d3eee8e483137fb42d41cb6e4ec20`
- PDF Privacy Toolkit: `891dad28b15b5c1c7dd743e6cbe442809ecb41`

After clone, record `git rev-parse HEAD`, `git remote -v`, source tree status, builder script path, Package Identity fields, approval file, and CI run corresponding to that exact head. Do not cherry-pick a main branch or default branch over these Store-specific branches.

Each Store branch contains its own builder:
- Image: `store/build-msix.ps1`
- Excel/CSV: `store/build-store-msix.ps1`
- PDF: `store/build-msix.ps1`

The QA-only unsigned artifacts from their CI workflows were created with temporary/placeholder package artwork. Their formal Store-candidate build steps were skipped because version and asset approvals are missing. Do not promote these artifacts to Store upload candidates.

## Restore local GitHub connectivity

The previous local run reported DNS failures for `github.com`, a failed TCP 443 probe, and invalid configured GitHub CLI credentials. This GitHub-side connection could read/write the authorized PR branch, but it does not fix the local Windows machine's DNS or `gh` authentication.

After restoring network and interactive authentication:

```powershell
Resolve-DnsName github.com
Test-NetConnection github.com -Port 443
gh auth status -h github.com
git ls-remote https://github.com/shihuiarenjinba-png/Windows-all-auto.git HEAD
```

Do not paste tokens into chat, source code, logs, or reports. Do not create or revoke credentials as an automatic recovery step. After local authentication is valid, fetch and inspect the remote branch head before any push.

## Download exact remote artifacts for local hash verification

The remote artifact metadata is in:
- `ops/group_b_standard_store_products.json`
- `ops/group_c_store_products.json`
- `docs/GROUP_C_REMOTE_MSIX_ARTIFACT_INVENTORY_20261125.md`

Use exact artifact names and download to a new evidence folder. These artifacts are not Store upload approval:

```powershell
$root = "C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\remote-artifacts"
New-Item -ItemType Directory -Force -Path $root | Out-Null

gh run download 44093505473 -R shihuiarenjinba-png/workflow-automation-hub -n WorkflowAutomationHub-Store-MSIX-UNSIGNED-DRAFT -D (Join-Path $root "workflow-automation-hub")
gh run download 45103784990 -R shihuiarenjinba-png/csv-import-validator -n data-contract-QA_UNSIGNED-msix-45103784990 -D (Join-Path $root "data-contract-auditor")
gh run download 44687824883 -R shihuiarenjinba-png/-AI-Upload-Guard-AI- -n group-c-QA_UNSIGNED-validation-msix-44687824883-1 -D (Join-Path $root "ai-upload-guard")
gh run download 44687836979 -R shihuiarenjinba-png/-Screenshot-Image-Privacy-Cleaner -n group-c-QA_UNSIGNED-validation-msix-44687836979-1 -D (Join-Path $root "image-privacy-cleaner")
gh run download 44687814041 -R shihuiarenjinba-png/-Excel-CSV-Privacy-Cleaner -n group-c-QA_UNSIGNED-validation-msix-44687814041-1 -D (Join-Path $root "excel-csv-privacy-cleaner")
gh run download 44687829990 -R shihuiarenjinba-png/-PDF-Privacy-Toolkit -n group-c-QA_UNSIGNED-validation-msix-44687829990-1 -D (Join-Path $root "pdf-privacy")
gh run download 44687808856 -R shihuiarenjinba-png/web-evidence-archiver -n web-evidence-QA_UNSIGNED-validation-msix-44687808856-1 -D (Join-Path $root "web-evidence-archiver")
```

Then compute the actual files' SHA-256 and compare them with the builder-reported hashes in the inventory. The hashes recorded in this PR came from GitHub Actions logs/generated handoffs; those binary artifacts have not yet been downloaded and independently re-hashed locally. If any local digest differs, hold that artifact and investigate; do not upload.

## Product-specific next actions

### Six products with existing Submissions

The read-only snapshot shows existing Submission 1 / In draft for:
- AI Upload Guard — Product `9PDJ1T5BQ4P1`, Draft `1152921505702212224`
- Image Privacy Cleaner — Product `9PNSPFBKBBTQ`, Draft `1152921505702212225`
- Excel / CSV Privacy Cleaner — Product `9P3Z36J7PSFC`, Draft `1152921505702213008`
- Data Contract Auditor — Product `9PDL4ZWSB45P`, Draft `1152921505702212222`
- PDF Privacy — Product `9PD1RXLFWPBC`, Draft `1152921505702212497`
- Web Evidence Archiver — Product `9NNT1B142ZWV`, Draft `1152921505702212223`

These IDs are timestamped observations, not evergreen authorization. Re-read the current Product/Draft immediately before any upload.

### Workflow Automation Hub

Product `9P6SXJNNB5KK` and its Identity/Publisher are present, but the 2026-11-25 Partner Center observation showed no Submission and a `Start submission` control. It was not clicked.

A source-bound unsigned technical draft exists at source `f2ba58895492f0c64da7676b17edfc97e98330e7`, package `WorkflowAutomationHub_1.0.0.0_x64_StoreDraft_UNSIGNED.msix`, builder-reported SHA `512da1ab4449a69b02901baf9c8eaff6577f1e58d336f43ef608f4fbc3892a97`. The handoff/validation/SHA files are included in the remote artifact.

The source marks 1.0.0.0 technical-only, not owner-approved, uses temporary technical logos, and states `submission_allowed=false`. Do not start a Submission or upload this artifact until the owner approves the version/assets and the local exact-package QA is complete. If subsequently authorized, use the existing owner-gated initial-submission route and re-read Partner Center after the action; do not blindly retry.

### Data Contract Auditor

The QA baseline source is `107e59f2cbcde9c6ca88cf1aaf3d52262004e6e0`. This is **not** the formal candidate source requirement. The formal candidate gate records `formal_source_sha=5a09d81955e25664761ea25ecfb4ebf8d24cea6d`, 40 commits after the QA baseline. The successful run `45103784990` built `DataContractSchemaDrift_1.0.0.0_x64.msix` from the formal source SHA and the builder logged package SHA `80cd02c0df8e75d1962d03ce63c1ba72d9a8f67e8056f43718ffc5bd8d3f3279`.

The current branch HEAD at this handoff is `722ec7a077d2c6109e657c4ee661c9f3d06a4506`; the commits after `5a09...` change only the formal gate, product profile, and post-build profile test. No app runtime or packaging script changes were found in that range.

The failed CI run `45107287117` was caused by a stale test expecting pre-build status `READY_FOR_FORMAL_MSIX_BUILD`; the actual profile/gate had advanced to `READY_FOR_PARTNER_CENTER_READONLY` and `FORMAL_UNSIGNED_MSIX_CREATED_AND_VERIFIED`. The test was corrected in commit `722ec7a077d2c6109e657c4ee661c9f3d06a4506`.

Current workflow run `45580565845`:
- source tests passed;
- compile passed;
- Store package readiness preflight passed;
- the formal unsigned candidate and QA structural jobs are running.

Wait for the build jobs to finish and record the newly generated package filename, exact source SHA, MSIX SHA-256, and artifact ID. The prior candidate from run `45103784990` remains available and source-bound to `5a09...`; new run output should supersede it only after its SHA is independently verified locally.

The current Partner Center read-only observation showed Draft `1152921505702212222` with Packages `Incomplete`. That must be re-read immediately before any upload. An unsigned candidate build is not authorization to upload, certify, or publish.

### Web Evidence Archiver

Store package branch:
- `codex/store-p0-web-evidence-20261023` at `3f2de607d83f36abef6d9a87da1a1c8b3bca604a`

Latest GUI QA branch:
- `codex/web-evidence-gui-progress-20261124` at `fd34b93068d5ea39e3a02e89dc1c8c3d9bcb0812`

The branches diverged from merge base `0f1537e33c6f5b3e79d034ad92865a162ee36275`: GUI branch is 7 commits ahead and 76 behind the Store branch. Create a review branch from the Store package branch and merge the GUI branch into it; preserve the Store packaging, manifest resources, browser bundle license/approval gates, and new GUI fixes. Resolve conflicts, run full Windows QA and Store preflight on the resulting commit, and only then create/update a review PR. Do not package from either old branch alone.

## DCA and other formal gates

- AI/Image/Excel/PDF CI builds created QA_UNSIGNED packages with placeholder logos; their formal Store-candidate workflow stages were skipped because owner-approved Store Version and artwork approvals are missing.
- WEA structural QA artifact is unsigned, and formal candidate build was skipped because approved version, manifest resources, and browser bundle approval are missing.
- WAH technical unsigned draft is source-bound but its version, assets and current initial Submission are not owner-approved.
- DCA candidate source mismatch and current branch test failure remain unresolved.

The next local cycle should therefore complete: download/re-hash -> inspect manifests / Source Revision -> fix DCA current branch test -> integrate WEA GUI and Store source -> build/retest only when approved inputs exist -> update handoff receipts and PRs.

## Prohibited actions in this handoff

No new Product creation, Submission start, package upload, Packages Save, pricing or market changes, Certification, Publish, PR merge, or `main` direct push is authorized by this document. Keep all Store writes behind explicit owner approval and current live-state revalidation.
