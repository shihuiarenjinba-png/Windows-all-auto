# Code owner handoff — Group B standard app conveyor

Updated: 2026-11-17 JST

## Scope

Continue the GitHub -> exact Store artifact -> minimal local Windows confirmation
conveyor for the four Group B **standard** apps.

Do not mix the `-2` consumer repositories into this work.

The Store execution owner is separate. This handoff does **not** authorize:

- Start submission / Start update;
- package upload;
- pricing or audience changes;
- certification submission;
- Private/Public publish;
- main/release merge;
- Windows security-policy changes or certificate bypasses.

## Operating model

GitHub CI is the primary test environment.

Local Windows is not a second full CI environment. It should confirm the exact bytes
that already passed GitHub and perform only checks GitHub cannot prove, such as real
Windows DPI, Task Scheduler, OAuth, bundled Chromium behavior, or Store-signed
physical QA.

The intended flow is:

```text
product PR exact HEAD
  -> required GitHub CI SUCCESS
  -> Store-build artifact + store-product-handoff.json
  -> central registry identity/workflow binding
  -> exact-head artifact discovery
  -> local immutable artifact receipt
  -> minimal product-specific Windows confirmation
  -> machine-readable QA receipt
  -> separate Store execution owner
```

## Central repository

Repository: `shihuiarenjinba-png/Windows-all-auto`  
PR: #166  
Branch: `codex/msix-commercial-handoff-20261115`

Important central files:

- `ops/group_b_standard_store_products.json`
- `ops/group_b_conveyor_checkpoint_20261117.json`
- `all_auto/product_artifact_pull.py`
- `all_auto/local_preupload_receipt.py`
- `all_auto/store_preupload_gate.py`
- `all_auto/store_product_handoff.py`
- `scripts/pull_store_product_artifact.py`
- `scripts/pull_group_b_store_product.py`
- `scripts/prepare_group_b_local_confirmation.py`
- `scripts/run_store_preupload_readiness.ps1`
- `scripts/create_local_final_qa_receipt_template.py`

## Completed central behavior

### Exact product artifact pull

For Scheduled / Hub / Browser, the central Group B registry fixes:

- repository;
- source branch;
- Store-build workflow name;
- Store artifact name;
- Store ID;
- Identity Name;
- Version;
- Architecture;
- local-only acceptance checks.

The normal command is:

```powershell
python scripts/pull_group_b_store_product.py `
  --product-id <product-id> `
  --target-root C:\path\to\group-b-local-inbox `
  --receipt C:\path\to\evidence\artifact-pull-receipt.json
```

If `--run-id` is omitted, the wrapper:

1. resolves the registered branch HEAD;
2. lists successful Actions runs;
3. requires exactly one completed SUCCESS run of the registered Store-build workflow
   for that exact HEAD;
4. HOLDs if none exist;
5. refuses to guess if multiple exact-head successes exist.

If `--run-id` is supplied explicitly, it still must be for the **current registered
branch HEAD**, the registered Store workflow, and a completed SUCCESS result. An old
successful run cannot be used to roll back the candidate.

### Artifact verification

The direct artifact worker requires:

- exactly one live artifact with the registered name;
- successful exact run;
- run HEAD SHA == artifact handoff source SHA;
- repository match;
- artifact run ID match;
- one MSIX;
- one `store-product-handoff.json`;
- one `msix_validation.json`;
- one `msix.sha256.txt`;
- MSIX SHA match across bytes/handoff/validation/checksum;
- EXE source/unpacked SHA match;
- Manifest Identity verification PASS;
- MakeAppx roundtrip PASS;
- signed/store_submission_approved/sale_approved remain false;
- central Store ID / Identity / Version / Architecture match.

The receipt also records the GitHub artifact archive:

- artifact ID;
- artifact digest;
- artifact size;
- expired=false.

### Local staging safety

Local artifact staging is:

- path-safe;
- product-id constrained;
- atomic at the artifact-directory level;
- no destination overwrite;
- no evidence receipt overwrite;
- package_rebuilt=false;
- security_bypass_used=false;
- package_installed=false;
- submitted_to_store=false;
- certification_submitted=false;
- published=false.

### One-command local confirmation workspace

Use:

```powershell
python scripts/prepare_group_b_local_confirmation.py `
  --product-id <scheduled-api-runner|workflow-automation-hub|browser-automation-runner> `
  --workspace-root C:\path\to\workspace
```

It:

1. discovers/pulls the exact GitHub Store artifact;
2. validates registry/provenance/package evidence;
3. stages the exact files;
4. creates an immutable local QA template;
5. writes `workspace.json` with status
   `READY_FOR_LOCAL_WINDOWS_CONFIRMATION`.

The generated QA template records:

- `github_ci_is_primary=true`;
- `local_full_test_suite_required=false`;
- `test_source=github_exact_head_ci`;
- product-specific local-only checks from the registry.

Do not restore a mandatory full local unit-suite run. That is intentionally rejected
by the Store handoff contract.

## Product status

### Folder Automation Engine — pilot

Repository: `shihuiarenjinba-png/folder-automation-engine`  
PR: #10  
Current metadata/runbook HEAD at this checkpoint:
`a69d73aeeffbc7e734debec50aeb2b3b8900734d`

Frozen candidate remains:

- source: `51597b389384be6cf2b3d85c09ee66099b80807e`
- Store ID: `9P99MJX1R4V6`
- MSIX SHA256:
  `911f8eb13abfdbb51bea8f279006d138d6be9cba4a25413416c1d70458676450`
- EXE SHA256:
  `d53161ea1119445afb8070d989d4a72e8019895b8c5e166738a3e38718b54976`

Do not use the direct product-artifact pull to replace this frozen Folder candidate.

Current conveyor state:

`HOLD_SUBMISSION_RECONCILE_REQUIRED`

Dependency:

Store execution owner must return an
`existing-store-initial-submission-reconcile-receipt/1` with status
`INITIAL_SUBMISSION_DRAFT_PRESENT_RECOVERED`, exact Store ID, numeric Draft ID,
exact Draft URL, and all write flags false.

Until then, do not rebuild Folder, rerun the known blocked unsigned EXE, upload the
package, or touch Partner Center from this lane.

### Scheduled API Runner

Repository: `shihuiarenjinba-png/scheduled-api-runner`  
PR: #8  
Current branch HEAD: `0c2a38ff8c7d5311b115e67387deaed2ce11a523`

The current branch HEAD contains a Store-runbook-only documentation change. It does
**not** replace the locally static-verified Store candidate.

Frozen candidate:

- source: `28ef873ab2ff325b8f26c61a9ba48701280e8290`
- Store/Windows run: `44093493317`
- Store artifact: `14333575447`
- artifact digest:
  `sha256:b45d53a0473f5b8cdcac64c1ffdcf12957919da2e5cb846564344d757165afa7`
- MSIX SHA256:
  `db599cdfa673688e8fe7db70d11acc69010562636c67f4996b4cba36adfd8877`
- EXE SHA256:
  `06d3b92bd83281750e5a454f9add6526fa90f6bfc29017fd6919bbeaa64213d9`
- local static verification: PASS
- package rebuilt: false
- security bypass: false

A docs-only descendant build also exists at source
`0c2a38ff8c7d5311b115e67387deaed2ce11a523`, run `44106267118`, artifact
`14337483379`, but its MSIX/EXE bytes differ. It is **not promoted**. Do not replace
the frozen candidate unless that descendant completes a fresh local static
verification and the central frozen-candidate record is explicitly updated.

Exact-head CI:

- Reliability run `44093493219`: SUCCESS
- Store/Windows run `44093493317`: SUCCESS

Store artifact from that run:

- ID: `14333575447`
- name: `ScheduledApiRunner-Store-MSIX-UNSIGNED-DRAFT`
- digest:
  `sha256:b45d53a0473f5b8cdcac64c1ffdcf12957919da2e5cb846564344d757165afa7`

Current local state:

`APPLICATION_CONTROL_BLOCKED_STORE_SIGNED_QA_REQUIRED`

The one-shot unsigned launch is complete and must **not** be repeated.

Observed:

- action-time approval: yes
- attempts: 1
- normal user: yes
- process started: no
- original wrapper status: `LAUNCH_FAILED`
- reconciled classification: `APPLICATION_CONTROL_BLOCKED`
- Code Integrity block events: 3033 / 3077
- supplemental event: 3118
- policy: `VerifiedAndReputableDesktop`
- policy GUID: `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`
- residual processes: 0
- security bypass: none
- Store write: none

The original launch receipt remains immutable. The later Code Integrity evidence must
be reconciled into a separate
`unsigned-exe-launch-reconciliation-receipt/1` using
`scripts/reconcile_delayed_code_integrity_launch.py`.

The next physical QA is **not another unsigned launch**. It resumes on a Microsoft
Store-signed Private distribution of the same frozen candidate.

Remaining signed-build QA:

1. Microsoft Store delivery/signature verification;
2. JP/EN GUI + normal exit;
3. real OS DPI 100/125/150;
4. authorized non-production HTTPS GET using an owner-approved endpoint only;
5. CSV append / duplicate-date protection / secret redaction;
6. Windows Task Scheduler register -> run -> verify -> unregister.

Do not invent an endpoint, do not pay to reacquire the owner's own application, and
do not contact production systems merely to complete QA.

### Workflow Automation Hub

Repository: `shihuiarenjinba-png/workflow-automation-hub`  
PR: #12  
HEAD: `f2ba58895492f0c64da7676b17edfc97e98330e7`

Exact-head Store/Windows run:

- `44093505473`: SUCCESS

Store artifact:

- ID: `14332647613`
- name: `WorkflowAutomationHub-Store-MSIX-UNSIGNED-DRAFT`
- digest:
  `sha256:16b910bc658d75f403952d6dc73756be71e183c0292b120ce4691ec2d4e2d742`

Local-only focus:

- real JP/EN GUI;
- real OS DPI 100/125/150;
- non-production Google OAuth/Blogger;
- one controlled test-blog mutation only after Dry Run/backup;
- Windows Task Scheduler lifecycle.

No production Blogger write is authorized.

### Browser Automation Runner

Repository: `shihuiarenjinba-png/browser-automation-runner`  
PR: #8  
HEAD: `2ae45a80f1a16e70dfcc86277ca44ed0ce80292a`

Exact-head CI:

- Reliability run `44093519140`: SUCCESS
- Store/Windows run `44093519175`: SUCCESS

Store artifact:

- ID: `14332567327`
- name: `BrowserAutomationRunner-Store-MSIX-UNSIGNED-DRAFT`
- digest:
  `sha256:9df4b194373ebc59bf386f1b8c8263d37ea0ba6f1235cb9c1649a8a654224276`

Local-only focus:

- real JP/EN GUI;
- real OS DPI 100/125/150;
- bundled Chromium physical launch;
- harmless local/test-site workflow;
- output collision/no-overwrite.

Human HOLD remains:

`THIRD_PARTY_RIGHTS_OWNER_LEGAL_REVIEW`

Do not flip that flag from file existence alone.

## Code-owner next tasks

Work in this order.

### P0 — Scheduled unsigned lane is complete and blocked

Do **not** repeat Scheduled artifact staging or static confirmation. The local report
has already established:

- state: `APPLICATION_CONTROL_BLOCKED_STORE_SIGNED_QA_REQUIRED`;
- artifact receipt verified against the frozen candidate;
- repeated workspace/receipt/template creation refused and prior evidence hashes
  remained unchanged;
- MakeAppx unpack PASS;
- Manifest Identity / Publisher / Version / Architecture PASS;
- unpacked EXE SHA PASS;
- Defender custom scan reported no threats for the exact MSIX and EXE;
- Authenticode is `NotSigned` for both, which is expected for the unsigned draft;
- GitHub CI remains primary and no full local suite was duplicated;
- QA template remains `HOLD`.

The one-shot physical launch is already complete and blocked before process start.
Do not request or perform another unsigned launch.

### P0.5 — reconcile the delayed Code Integrity evidence

Do **not** relaunch the unsigned EXE.

Use the immutable original launch receipt plus the separate
`code-integrity-block-evidence/1`:

```powershell
python scripts/reconcile_delayed_code_integrity_launch.py `
  --handoff <frozen store-product-handoff.json> `
  --launch-receipt <original unsigned-exe-launch-receipt.json> `
  --code-integrity-evidence <code-integrity-block-evidence.json> `
  --output <new unsigned-exe-launch-reconciliation-receipt.json>
```

Then bind that new reconciliation receipt into a **new** QA evidence file with
`apply_unsigned_exe_launch_receipt.py`.

Expected classification:

`APPLICATION_CONTROL_BLOCKED`

The original launch receipt and Code Integrity evidence remain unchanged. The QA state
remains `HOLD`.

### P1 — formalize the limited pre-Store signing lane, then hand off

Before sending the evidence to the Store execution owner, convert the already-verified
artifact + reconciled Application Control block into the central contract:

`pre-store-static-qa-receipt/1`

Use:

```powershell
python scripts/create_pre_store_static_block_receipt.py `
  --handoff <frozen store-product-handoff.json> `
  --artifact-receipt <immutable artifact-pull-receipt.json> `
  --launch-reconciliation <unsigned-exe-launch-reconciliation-receipt.json> `
  --output <new pre-store-static-qa-receipt.json>
```

Then apply it to a **new** handoff evidence file:

```powershell
python scripts/apply_pre_store_static_qa_receipt.py `
  --handoff <frozen store-product-handoff.json> `
  --receipt <pre-store-static-qa-receipt.json> `
  --output <new handoff-after-pre-store-static-block.json>
```

Expected central QA state:

- `pre_store_static_pass=true`
- `unsigned_gui_execution_status=APPLICATION_CONTROL_BLOCKED`
- `local_final_pass=false`
- `store_signed_install_pass=false`
- Private Store-signing lane may be ready only subject to the other independent
  commercial/assets/security/audience gates.

This receipt does **not** authorize upload, certification, pricing, audience change,
or publication.

The code-owner lane must not perform Partner Center writes. Provide the Store owner
the exact frozen package binding, the reconciliation receipt, the pre-Store static
receipt, and the updated package-bound handoff. Request a Microsoft Store-signed
Private distribution path with zero acquisition cost.

After the Store-signed build is available, resume physical QA there. No unsigned
relaunch is permitted. Complete only the remaining local-only checks on the
Store-signed build. Do not rerun the whole GitHub unit suite.

Return the exact package-bound local QA receipt to Windows-all-auto.

If Windows Application Control blocks an exact unsigned executable:

- record the block;
- do not change policy;
- do not add a temporary certificate;
- do not bypass it;
- use the established pre-Store static/Store-signing lane if applicable.

### P2 — keep direct-pull products generic

Any code needed by Scheduled / Hub / Browser should live centrally when possible.
Avoid copying product-independent artifact/provenance logic into three repositories.

Product repositories should own only:

- product build/test logic;
- product Store handoff profile;
- product-specific local-only checklist;
- customer-facing Store/compliance documents.

### P3 — Folder resume path

When the Store owner returns the recovered Draft receipt:

1. verify schema/status/write flags;
2. apply it with `apply_recovered_initial_submission_receipt.py`;
3. bind Draft ID/URL to the frozen handoff;
4. rerun the same frozen Folder MSIX through local pre-upload readiness;
5. stop at `READY_FOR_MSIX_UPLOAD_APPROVAL`;
6. do not perform upload from this code-owner lane.

### P4 — preserve evidence immutability

Continue refusing overwrite of:

- exact artifact staging destinations;
- artifact pull receipts;
- QA evidence templates;
- final package-bound receipts.

If recovery is necessary, use a new evidence path rather than mutating prior evidence.

## Acceptance criteria before returning this handoff

- all changed PR HEADs have required CI SUCCESS;
- no main/release merge;
- no Store write;
- no product candidate rebuilt merely for metadata changes;
- exact artifact provenance remains traceable from GitHub run -> artifact -> handoff ->
  local MSIX -> QA receipt;
- GitHub CI remains the primary test source;
- local Windows remains minimal physical confirmation.

## Current human/external dependencies

1. Scheduled: Store execution owner must provide a Microsoft Store-signed Private
   distribution / zero-cost acquisition path for the frozen candidate before GUI,
   DPI, HTTPS GET and Task Scheduler physical QA can resume.
2. Folder recovered Draft receipt from Store execution owner.
3. Folder Store assets/security/audience/price owner approvals later.
4. Browser third-party redistribution-rights owner/legal decision.
5. Package upload / certification / publish remain separate explicit approvals.

Do not convert any of these dependencies into guessed values or automated approvals.
