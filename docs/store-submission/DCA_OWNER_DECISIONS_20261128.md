# Data Contract Auditor — owner decisions for Store registration

Generated from the pinned DCA source/profile, uploader job configuration, and the recorded read-only Partner Center observation. This document is a decision sheet, not authorization to write to Partner Center. Values marked **Candidate** remain unapproved.

## Fixed identifiers and existing approvals (reused)

| Item | Recorded value | Status / evidence |
|---|---|---|
| Product / Store ID | Data Contract Auditor / `9PDL4ZWSB45P` | Fixed job binding |
| Existing submission | `1152921505702212222` | Fixed job binding; do not create a new submission |
| Package identity | `OkinawaDesktopTools.DataContractAuditor` | Job config and expected manifest |
| Publisher | `CN=46263F21-A700-41DB-8C9B-114C22FB82FC` | Job config and expected manifest |
| Version / architecture | `1.0.0.0` / `x64` | Fixed job config |
| Store package version | `1.0.0.0` | Existing owner approval in source record |
| Icon concept | Blue spreadsheet/document, magnifier, green check | Owner approval recorded 2026-11-23 in `store/assets/approval.json`; this does not approve screenshots |
| Manifest languages | `en-US`, `ja-JP` | Product profile; this does not approve listing copy or language readiness |
| Package operation scope | One specified package to existing Draft Packages only | Prior narrowly scoped chat authorization; current automated execution profile remains `PLAN_ONLY` |
| Certification / Publish | Not authorized | Must remain separate gates |

## Package provenance conflict — unresolved hold

The immutable Job Config keeps current candidate SHA `e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05` for run `45580565845` / artifact `15005358857`, source `722ec7a077d2c6109e657c4ee661c9f3d06a4506`. GitHub identifies that artifact as created 2026-11-25 08:58:31Z, expiring 2026-12-25 08:58:27Z; its archive digest is `5d914be309e83bf8e0422e71be2f2914fcf6cda9588d9d765e075b31bcb97548` (ZIP digest, not the MSIX digest). The artifact build evidence/local rehash records the MSIX SHA as `e2ca…`. The prior source registers `4b373d2bc54ecbd3efa0a77a94005007777e66d641fa3908f523ac69fcd46984` and links its formal package to source `5a09d81955e25664761ea25ecfb4ebf8d24cea6d`. The package, Job Config expected SHA, Product ID, and Draft ID have not been changed.

The exact old-SHA registration commits are now confirmed: `2956574fc1a3cf80b60281dfc8e6914cc8084383` updated `store/FORMAL_CANDIDATE_GATE_20261122.json` on 2026-11-23, and `0c73a746bcec9ded702567768d5c04f4240a12a9` updated `store/product.json` on 2026-11-23. Both register `4b373…` against source `5a09…`. The 2026-11-25 artifact is a separate build and source revision; its build evidence binds `e2ca…` to run `45580565845`. Thus the discrepancy's provenance is explained: the source's formal record was not advanced when the later artifact was produced. The old SHA is historical; the current candidate remains `e2ca…` pending owner approval.

**Proposed record change, not yet applied:** retain the old registration as an append-only historical record with its two commit IDs and source revision; after the owner approves the current artifact candidate, update the product profile's formal-current pointer to `e2ca…`, recording artifact/run/source provenance and preserving the old record. The current Job Config SHA remains unchanged throughout. No formal product-profile value has been rewritten in this change.

**Single explicit provenance decision needed:** approve or reject using artifact `15005358857` / run `45580565845`, source `722ec7a077d2c6109e657c4ee661c9f3d06a4506`, package SHA `e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05` as the new formal-current package record for Product `9PDL4ZWSB45P` / existing Submission `1152921505702212222`, while retaining `4b373d…` as history. This decision only changes the source product's formal provenance pointer after it is recorded. It does not approve upload, Packages Save, Certification, or Publish, and does not declare runtime QA passed.

Evidence refs: [pinned product profile](https://github.com/shihuiarenjinba-png/csv-import-validator/blob/722ec7a077d2c6109e657c4ee661c9f3d06a4506/store/product.json), [artifact inventory](../GROUP_C_REMOTE_MSIX_ARTIFACT_INVENTORY_20261125.md), and `uploader/config/data-contract-auditor.job.json`.

## Decisions still required

The following candidates can be approved together in one reply. Approval must identify each choice; blank items remain unresolved. Package provenance approval does not authorize upload, and section values do not authorize Certification or Publish.

| Decision | Evidence-based candidate to approve or replace |
|---|---|
| Formal-current package record | Adopt run `45580565845` / Artifact `15005358857`, source `722ec7a077d2c6109e657c4ee661c9f3d06a4506`, SHA `e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05` as current; retain `4b373d…` and its source as append-only history. |
| Device families | Select `Windows 10/11 Desktop` to match `Windows.Desktop`; separately choose whether Microsoft may decide availability for future device families (currently checked in the recorded Packages screen). |
| Category | `Productivity`, consistent with the pinned tool description. |
| Price | Choose one-time paid / free / subscription and the exact JPY amount. No DCA price amount is evidenced, so the system will not propose a numeric price. |
| Markets | Preserve the observed 240-market selection, or provide the exact replacement market list. |
| Listings | Approve the Japanese source draft and a reviewed English translation; confirm English UI/support readiness. |
| Screenshots | Approve four genuine app captures after DCA runtime QA: initial selection, schema findings, quality findings, and output files. No synthetic UI is eligible. |
| Privacy | Review a Yes candidate because user-selected data files may contain personal information; separately approve the privacy-policy URL and exact declaration. |
| IARC | Candidate type `All Other App Types`; owner must provide/confirm each content questionnaire answer from product behavior. |
| Commercial rights | Supply/approve license and redistribution evidence. Current source is `NOT_CERTIFIED`, so commercial distribution remains on hold. |
| Publishing and automation | Keep manual Publish; retain package-only scope and `PLAN_ONLY` until a separately scoped approval is recorded. |

| Decision | Evidence-backed candidate(s) | Current observation / blocker | Owner decision needed |
|---|---|---|---|
| Device family | **Candidate:** Windows 10/11 Desktop, since Manifest targets `Windows.Desktop` | Existing Packages observation: Desktop unchecked | Approve Desktop selection for this submission, or provide another Manifest-compatible choice |
| Future device families | **Candidate:** retain Microsoft's “decide future device families” behavior; alternative is limit to explicitly selected families | Existing observation: option checked | Keep enabled or disable |
| Category | **Candidate:** Productivity; product is a local CSV/XLSX schema-drift auditor | Properties category blank in observation | Approve category or specify another |
| Price | No numeric candidate is supported by the records | Pricing base price unset | Specify one-time price/free/subscription and base market price; this sheet does not infer it |
| Markets | **Candidate:** preserve the observed 240-market worldwide selection; alternative is an exact owner-specified list | Observation showed all 240 markets selected; no approval found | Preserve current selection or give exact market list |
| Japanese listing | **Candidate:** review `store/STORE_MINIMUM_LISTING_JA_DRAFT.md` | File is explicitly a draft, not approved | Approve exact copy or provide edits |
| English listing | **Candidate:** prepare a faithful translation based on pinned README and the Japanese draft | English UI/support readiness is not confirmed in the listing draft | Confirm English UI/support readiness and approve exact copy, or exclude en-US listing |
| Screenshots | **Candidate:** four real UI captures: initial file selection, schema differences, quality comparison, report output | No approved screenshots found; those screens are requested in the listing draft | Approve captures after review; do not substitute generated/mock UI |
| Privacy declaration | **Candidate for review:** answer Yes to personal-data use because selected CSV/XLSX files may contain personal data; app modules inspected read/analyze locally and write local reports, with no outbound-networking code found | The questionnaire's current answer was not captured; code inspection does not decide the legal declaration | Confirm the exact Partner Center answer and privacy-policy details |
| Age rating | **Candidate:** IARC app type “All Other App Types”; answer content questions from actual features | Questionnaire incomplete; utility is not a game/social product | Confirm app type and each content answer based on product behavior |
| Commercial license | No pass candidate; source says `NOT_CERTIFIED` | Commercial rights/dependency evidence incomplete | Provide/approve license evidence and confirm commercial distribution rights |
| Publication | **Candidate:** hold for manual publication after certification | Existing publication radio state was not captured | Confirm manual publication policy; this does not authorize certification or publish |
| Automatic execution scope | **Candidate:** keep the existing package-only scope; add each other section only with a separate section-specific approval | Job Config is `PLAN_ONLY`, approved section list empty | Approve exact section(s), product/draft binding, and approved field values when ready |

## Runtime QA and release gate

The exact unsigned MSIX passed hash/manifest inspection, but its local install attempt returned Access Denied and the packaged EXE launch timed out. Packaged runtime QA is **not passed**. The existing GitHub Windows workflow builds and structurally inspects the unsigned candidate; it does not install and interactively run this package. Source-based QA on an older source revision is separate evidence and cannot replace exact-package runtime QA. No test-signed copy has been created, and no independent VM has been confirmed. Do not repeat the same install attempt, change security policy, or report a signed-copy test as proof for the fixed MSIX.

Next admissible QA route: use an owner-managed disposable Windows 10/11 VM or dedicated QA host, first confirming its supported MSIX sideload/test-signing policy and documenting that policy without disabling Application Control. Keep the existing OS policy unchanged. If policy permits a **separate test-signed copy**, use a temporary test certificate whose subject exactly matches the package Publisher, trust it only inside the disposable VM, install with the standard AppX deployment API, launch through the package's registered application entry, exercise the smoke cases, then revert the VM snapshot and remove the temporary certificate. Record the source/package SHA, signed-copy SHA, certificate thumbprint, signing method, and differing package members. This is a diagnostic lane only; a passing signed copy is not a pass for fixed SHA `e2ca…`. If the disposable environment cannot execute the fixed unsigned package under its existing policy, record that exact-package runtime remains blocked; do not change policy or repeat the existing Access Denied attempt. No paid environment may be provisioned without cost approval. The central repo has no Windows-data/Windows-checker runtime installer for this DCA package, and the current hosted Windows CI only runs static package validation, not install/launch QA.

Microsoft documents that Windows requires an MSIX signature from a trusted certificate for deployment, and that a self-signed test package requires its certificate to be trusted on the test device. This explains why an unsigned Store candidate is not directly installable as-is on a clean test host; it does not by itself prove the precise cause of the earlier Access Denied event. References: [MSIX signing overview](https://learn.microsoft.com/windows/msix/package/signing-package-overview), [MSIX signing and test distribution guide](https://learn.microsoft.com/windows/msix/package/sign-msix-package-guide), [Add-AppxPackage](https://learn.microsoft.com/en-us/powershell/module/appx/add-appxpackage?view=windows-11).

Under the current, unchanged upload gate, Packages upload/Save requires the exact frozen bytes and manifest, resolved SHA provenance, approved device family, exact-package runtime QA receipt, section-scoped execution approval, and an authenticated read-only Product/Draft recheck. A successful Packages Save only establishes a saved Draft package. Certification additionally requires every required Draft section complete, commercial/license and legal disclosures resolved, exact-package QA passed, and a separate explicit Certification approval. Sale requires Certification completion and a separate explicit Publish decision; neither action is authorized here.

## Execution gate

The integrated command remains `python -m all_auto store run --product data-contract-auditor`. Until provenance and required owner inputs are resolved, it must fail closed, report pending sections accurately, and perform no Partner Center writes. This record does not authorize package upload/Save, pricing/market changes, certification, or publication.
