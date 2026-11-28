# MSIX QA and Store release gates

This defines separate evidence gates for a frozen unsigned Store candidate and a diagnostic test-signed copy. It does not authorize a Partner Center write, Certification, or Publish, and it does not relax the current product gate.

## What the signature rules mean

Windows deployment requires an MSIX signature whose certificate is trusted on the target device. A self-signed development/test package requires the test certificate to be trusted on that test device. Microsoft Store submissions are a separate path: Microsoft says the Store signs submitted MSIX packages during the submission/publishing process, so the Store candidate need not be locally signed with a commercial certificate. Therefore the current unsigned DCA candidate is valid as a Store-upload candidate in principle, but it cannot be installed as-is on an ordinary Windows QA host under the normal MSIX deployment rules. The prior Access Denied remains unexplained at the event-code/policy level; this rule explains why unsigned installation is not a valid generic test path, not the exact cause of that event.

References: [MSIX signing overview](https://learn.microsoft.com/windows/msix/package/signing-package-overview), [signing guide](https://learn.microsoft.com/windows/msix/package/sign-msix-package-guide), [MSIX overview](https://learn.microsoft.com/en-us/windows/msix/overview).

## Gates

| Gate | Required evidence | What it allows | Current DCA state |
|---|---|---|---|
| G0 — Frozen structural candidate | Source revision; local MSIX SHA; manifest Identity/Publisher/Version/Architecture; package validation; provenance reconciliation | Candidate may be assessed for the next gate | Candidate `e2ca6fd8…` is recorded; formal profile still records historical `4b373d…`; owner approval to advance the formal pointer is missing |
| G1 — Test-signature derivative identity | Copy the exact frozen bytes; sign only the copy with a temporary certificate whose subject exactly matches the Manifest Publisher; signature verification; source SHA unchanged; Manifest, block map, binaries, and assets byte-identical; permit only `AppxSignature.p7x` and signing-generated `AppxMetadata/CodeIntegrity.cat`, plus the matching signature/catalog declarations in `[Content_Types].xml` | Diagnostic install/launch test of the derived copy | Implemented in the ephemeral Windows CI harness; not yet passed by a hosted run for this commit |
| G2 — Windows runtime QA | Install, activate, and run product-specific smoke behavior; bind the receipt to both source and derived SHA, certificate thumbprint, OS, and test result | Under existing policy, exact candidate runtime gate remains unmet until accepted QA evidence exists | `RUNTIME_QA_UNRESOLVED`; synthetic harness is infrastructure evidence, not DCA evidence |
| G3 — Existing Draft Packages Save | Current G0/provenance, product-specific G2 policy, owner-approved device family, exact Product/Draft read-only recheck, separate Packages write approval; upload and reload receipt | Save only the package on the already-existing Draft | Not authorized by the current `PLAN_ONLY` execution profile; SHA provenance and QA/owner decisions remain outstanding |
| G4 — Certification | Every required Draft section complete, package and compliance evidence, separate explicit Certification approval | Certification submission only | Not authorized |
| G5 — Publish | Certification outcome accepted and separate explicit release/Publish approval | Store release | Not authorized |

No gate implies the next gate. A passing G1/G2 on the signature derivative is not a pass for the frozen unsigned SHA; the receipt must retain both SHA values and call out that difference.

If the owner later wants G2 to accept a signature-only derivative as equivalent runtime evidence, that is a QA-policy change and requires a separate approval record binding the product, source MSIX SHA, derivative MSIX SHA, certificate thumbprint, allowed package-member delta (`AppxSignature.p7x` only), smoke scope, and expiry/review policy. Until such a record exists, the effective rule remains exact-candidate runtime QA; derivative results are supplemental diagnostics only.

## Test-signing lane

`scripts/test_sign_msix_copy.ps1` is restricted to GitHub Actions. It verifies the source SHA and Manifest tuple, makes a distinct copy, creates a short-lived code-signing certificate matching the Publisher, signs and verifies the copy with Windows SDK SignTool, trusts the certificate only in the ephemeral runner, verifies member-level identity using `all_auto.msix_derivative`, and installs the copy. It first invokes the declared AUMID with `IApplicationActivationManager`. If the hosted runner reports a process but the app produces no fresh marker, the script records `registered_activation=UNCONFIRMED_IN_HOSTED_RUNNER`, captures matching AppModel/AppX events, and separately launches the executable from the installed package directory. Only that executable's fresh deterministic smoke marker can pass the generic harness; the receipt labels the fallback and does not claim AUMID activation. The app and temporary certificate are removed in `finally`, and the original package is rehashed. The signed copy and temporary cert are not uploaded as Store artifacts.

The CI workflow builds a synthetic full-trust desktop fixture to exercise this mechanism. Its marker verifies only launch of the installed package executable and a deterministic arithmetic check. Hosted-runner AUMID activation is separately reported; an executable fallback never proves registered-app activation. The fixture does not replace the DCA GUI/manual checks, does not inspect screen rendering, and does not establish the DCA exact-package runtime gate. A product-specific command/UI smoke must be added only when the product supports a reliable noninteractive smoke contract.

GitHub-hosted Windows runners are fresh VMs, configured as administrators with UAC disabled, and are discarded after a job. That makes them appropriate for a temporary test certificate and isolated install test, but not for an owner’s interactive visual QA or persistent certification evidence. No certificate, Windows security policy, or local machine trust is changed on the developer PC. For interactive UI/DPI review use a disposable owner-managed VM with the same one-run certificate lifecycle, or a dedicated interactive QA host; registering a self-hosted runner would require owner-controlled setup and lifecycle/security review.

## Current package and Store-operation status

- Current candidate MSIX SHA remains `e2ca6fd81720dc270667e65db05404b6efdde5b2c0712bee2853e0608767db05`; historical registered SHA remains `4b373d2bc54ecbd3efa0a77a94005007777e66d641fa3908f523ac69fcd46984`.
- The provenance origin is already documented in `DCA_OWNER_DECISIONS_20261128.md`; no new history investigation is required. The current SHA cannot become the formal profile value until owner approval is recorded.
- Approved value collection remains product-scoped and digest-bound in `uploader/config/store_submission_policy.json`. Candidate listing text, screenshots, device family, price, market, privacy, age rating, commercial rights, and publication choices remain separately classified in the owner-decision sheet.
- Properties and Pricing can be separately rehearsed because they do not depend on Packages. Store listings remain dependency-blocked until Packages is saved. Real Partner Center input/Save requires a separate section approval; this CI change does not interact with Partner Center.
- Product-specific listing/screenshot capture should use the real built UI and owner-approved copy/assets. Price, markets, legal answers, and publication settings remain owner decisions and are not inferred by automation.
