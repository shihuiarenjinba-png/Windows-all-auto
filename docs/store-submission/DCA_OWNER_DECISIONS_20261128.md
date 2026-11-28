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

The immutable Job Config expects `e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05` for the artifact from run `45580565845` / artifact `15005358857`, source `722ec7a077d2c6109e657c4ee661c9f3d06a4506`. The pinned source's `store/product.json` records `4b373d2bc54ecbd3efa0a77a94005007777e66d641fa3908f523ac69fcd46984` and links the formal package to source `5a09d81955e25664761ea25ecfb4ebf8d24cea6d`. Both records name the same filename/version but identify different bytes. The package, Job Config expected SHA, Product ID, and Draft ID have not been changed. The source profile's formal-package record appears stale relative to a later artifact build; the precise edit that caused the divergence has not been proven. **Resolve by identifying and recording the authoritative build/package provenance; do not select a SHA by filename or silently rewrite either record.**

The recorded Git history places `5a09d81955e25664761ea25ecfb4ebf8d24cea6d` on 2026-11-23 (“Update MSIX wrapper contract for formal candidate labeling”) and the artifact source `722ec7a077d2c6109e657c4ee661c9f3d06a4506` on 2026-11-25 (“test: align DCA profile checks with post-build read-only gate”). The later artifact's build evidence binds `e2ca…` to run `45580565845`; it does not make the earlier product-profile digest equal to the new artifact. The available compare notes show only Store packaging/gate/test files changed after the older source QA revision, but they do not establish which bytes were intended as the formal package at each revision. Therefore the discrepancy is classified as a stale or divergent source-profile record, with exact historical cause unresolved.

Evidence refs: [pinned product profile](https://github.com/shihuiarenjinba-png/csv-import-validator/blob/722ec7a077d2c6109e657c4ee661c9f3d06a4506/store/product.json), [artifact inventory](../GROUP_C_REMOTE_MSIX_ARTIFACT_INVENTORY_20261125.md), and `uploader/config/data-contract-auditor.job.json`.

## Decisions still required

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

Next admissible QA route: use an owner-managed isolated Windows 10/11 VM or a dedicated Windows QA host with documented MSIX test-certificate trust. Preserve the fixed package unchanged; if a test-signed copy is produced, record its distinct SHA, signing certificate, transformation steps, and byte differences, and report its runtime result separately. Exact-package QA remains blocked until a policy-compliant method can execute the unsigned Store candidate or an equivalent exact-byte Store/runtime path is documented. No paid environment is to be provisioned without cost approval.

## Execution gate

The integrated command remains `python -m all_auto store run --product data-contract-auditor`. Until provenance and required owner inputs are resolved, it must fail closed, report pending sections accurately, and perform no Partner Center writes. This record does not authorize package upload/Save, pricing/market changes, certification, or publication.
