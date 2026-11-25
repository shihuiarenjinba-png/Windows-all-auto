# Store Fleet Sync — Local Handoff — 2026-11-25

## Remote work completed

This handoff is paired with PR #166:

- Repository: `shihuiarenjinba-png/Windows-all-auto`
- Branch: `codex/msix-commercial-handoff-20261115`
- Current PR head at handoff: `ed52c038d0052968eaaed312e0efd4345ebe9175`
- PR: https://github.com/shihuiarenjinba-png/Windows-all-auto/pull/166
- State: OPEN / Draft / not merged
- Latest Windows + Ubuntu CI: success on current HEAD `ed52c038d0052968eaaed312e0efd4345ebe9175`, 379 tests on each runner; compile step passed. Runs: https://github.com/shihuiarenjinba-png/Windows-all-auto/actions/runs/45581433323 and https://github.com/shihuiarenjinba-png/Windows-all-auto/actions/runs/45581443686.

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

## Local artifact acquisition and verification — completed

The operator reports that all seven Actions artifacts were downloaded. The local file SHA-256 values match the builder-reported hashes, and each manifest's Identity, Publisher, Version, and Architecture was checked. Every package is `NotSigned`.

| Product | Version | Local MSIX SHA-256 | Remaining gate |
|---|---:|---|---|
| AI Upload Guard | 1.0.60.0 | `1141d327f43ec0f846bf780d3d0c68b82ac261dd869a7a54fdbb31c70f8b6125` | Runtime QA not verified |
| Image Privacy Cleaner | 1.0.50.0 | `90396a9097b1e7b570b5cfef4b9a45a93958733636adfe47c1aa71cde7e29800` | Owner-approved Store Version/artwork missing |
| Excel / CSV Privacy Cleaner | 1.0.57.0 | `18c4f841df4c3daffeebd068d001287baa4bfc2876ce1c2558eab258351cc79d` | Owner-approved Store Version/artwork missing |
| Data Contract Auditor | 1.0.0.0 | `e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05` | Install Access Denied; EXE launch timeout; runtime QA incomplete |
| PDF Privacy Toolkit | 1.0.54.0 | `3911348b502afb133beb07d3ab1c9070a7f68fe3ed05772d027c38c040678ed9` | Owner-approved Store Version/artwork missing |
| Web Evidence Archiver | 1.0.55.0 | `91fae107652539bad0c0bdc30e9ae1891542c1a92f2460218e1be24af987cebe` | Old pre-integration package; example capture timed out; formal preflight HOLD |
| Workflow Automation Hub | 1.0.0.0 | `512da1ab4449a69b02901baf9c8eaff6577f1e58d336f43ef608f4fbc3892a97` | Technical draft; owner approval and current Submission state not verified live |

The user-provided evidence files are:
- `LOCAL_PACKAGE_REHASH_REPORT.json`
- `PACKAGE_INVENTORY.json`
- `LOCAL_PACKAGE_QA_REPORT.json`
- `SHA256SUMS.txt`
- `FINAL_REPORT.md`

The report set is stored locally at `C:\Users\aaron\Desktop\portfolio-audit\_runtime\store-fleet-sync\`. Earlier report files were preserved under `EVIDENCE` before replacement. This update records operator-supplied local results; GitHub connector did not independently access the Windows filesystem.


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

The latest formal unsigned candidate was built from source HEAD `722ec7a077d2c6109e657c4ee661c9f3d06a4506`:
- Artifact ID: `15005358857`
- Package: `DataContractSchemaDrift_1.0.0.0_x64.msix`
- Version: `1.0.0.0`; Architecture x64
- Builder SHA and local SHA: `e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05` (match)
- EXE SHA: `b47219821bdaa9d3138b49dc4a00645190b6f6f3e7f90fa9e014fb5b93f7c1f5`
- Manifest Identity/Publisher/Version/Architecture: PASS
- Signature: `NotSigned`

Local install was denied by Windows and EXE launch timed out. Functional package QA remains incomplete. Do not infer a code defect solely from access denial; retain the Windows event / application-control diagnostic evidence and investigate the installation context. Do not certify or upload the unsigned candidate.

The historical Partner Center observation showed Draft `1152921505702212222` / Packages `Incomplete`; this phase did not live-recheck Partner Center. A fresh read-only observation is required before any later write.

### Web Evidence Archiver

The old QA package was built from Store branch `codex/store-p0-web-evidence-20261023` at `3f2de607d83f36abef6d9a87da1a1c8b3bca604a`. It was downloaded, and the local SHA matched the builder value:
- Package: `WebEvidenceArchiver_QA_UNSIGNED_1.0.55.0_x64.msix`
- SHA-256: `91fae107652539bad0c0bdc30e9ae1891542c1a92f2460218e1be24af987cebe`
- Manifest Identity/Publisher/Version/Architecture: PASS
- Signature: `NotSigned`

The GUI and Store branches were integrated locally. Integration commit:
`2516feedd5b10990fbe5c8184587e3b69214648d`

Local checks: 41 tests PASS and `compileall` PASS. However:
- GUI window launched;
- actual `example.com` CLI capture timed out;
- no capture output files were produced;
- formal Store preflight remains HOLD due approved version, owner-approved logos/assets, language settings, Chromium bundle approval, and offline/runtime QA gates;
- local integration commit is not pushed; no PR was created; remote CI was not run.

Important: the package whose SHA was verified is from the pre-integration Store source revision. It does not prove the new GUI integration commit is packaged. Do not upload or promote the old QA artifact. After pushing the integration commit on a review branch, run remote CI, repair the actual capture timeout, pass formal preflight with approved inputs, and build a fresh package from that exact commit.


## DCA and other formal gates

- AI/Image/Excel/PDF CI builds created QA_UNSIGNED packages with placeholder logos; their formal Store-candidate workflow stages were skipped because owner-approved Store Version and artwork approvals are missing.
- WEA old structural QA artifact is unsigned; its local SHA/Manifest checks pass, but actual capture timed out and formal preflight remains HOLD. The integrated local commit is unpushed and not yet built.
- WAH technical unsigned draft is source-bound but its version, assets and current initial Submission are not owner-approved.
- DCA builder/local SHA and Manifest checks pass, but installation was denied and EXE launch timed out; runtime QA remains incomplete.

The next cycle should focus on DCA Windows installation/access-denied diagnostics and runtime QA; WEA capture timeout diagnosis, then push its integrated source branch and run remote CI; obtain owner-approved Store Version/artwork/language/Chromium bundle inputs; perform a fresh read-only Partner Center recheck; and only then create new source-bound formal candidates.

## Prohibited actions in this handoff

No new Product creation, Submission start, package upload, Packages Save, pricing or market changes, Certification, Publish, PR merge, or `main` direct push is authorized by this document. Keep all Store writes behind explicit owner approval and current live-state revalidation.
