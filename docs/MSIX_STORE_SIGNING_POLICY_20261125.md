# Microsoft Store MSIX signing policy — 2026-11-25

## Decision

For these seven Windows products, use the Microsoft Store signing path. Do not purchase an external CA code-signing certificate, Azure Artifact Signing subscription, or hardware token for Store-distributed MSIX packages.

Microsoft's official guidance states that a CA-trusted certificate is not required for MSIX/AppX Store submissions. After an app passes certification, Microsoft Store automatically re-signs the package with a Microsoft certificate during the publishing process. The Store handles the certificate lifecycle.

Official references:
- https://learn.microsoft.com/ja-jp/windows/apps/publish/faq/get-started-with-the-microsoft-store
- https://learn.microsoft.com/ja-jp/windows/msix/package/sign-msix-package-guide
- https://learn.microsoft.com/windows/msix/package/signing-package-overview

## Timing matters

The Store signature is not applied merely because a file has been uploaded. The stages are distinct:

1. Submit the MSIX/AppX package to the existing Partner Center draft. A CA-trusted external signature is not required for this Store route.
2. Microsoft analyzes the package and the submission proceeds through certification.
3. After certification passes, the Store re-signs the package during publishing.
4. Customers install the Store-distributed package with Microsoft's trusted signature.

This policy is specific to Store-distributed MSIX/AppX. It does not apply to standalone MSI or EXE installers; Microsoft does not re-sign those installers.

## How to interpret the seven local packages

The operator reported that all seven files are `.msix`, each local SHA-256 matched the builder-reported SHA-256, and each package manifest passed Identity, Publisher, Version, and Architecture checks. Each local package reports `NotSigned`.

For these Store MSIX candidates, `NotSigned` is an expected pre-submission state and **must not be treated as a standalone upload blocker**. No external signing certificate should be introduced just to change that status.

The uploader's current `verify_file` implementation checks the `.msix` extension, file size, SHA-256 when pinned, and manifest Identity/Publisher/Version/Architecture. It does not require an Authenticode signature. The existing unit-test fixture exercises an unsigned MSIX through this validation path.

## Gates that remain independent of signing

Removing the external-certificate requirement does not waive package or release quality checks. Before a package is written to Partner Center, retain all of the following:

- Exact Store Product ID and current existing Draft ID re-read from the authenticated Partner Center session.
- Exact source revision, repository path, package filename, pinned SHA-256, Identity, Publisher, Version, and Architecture.
- Product-specific upload authorization. Approval for one product must not be generalized to another.
- Owner-approved Store version, artwork, language, and other product-specific commercial metadata.
- Functional/runtime QA appropriate to the app. An unsigned local install blocked by a Windows application-control policy is evidence that local unsigned testing was blocked; it is not, by itself, proof that the code is defective. It also does not prove the Store-signed package will work.
- A clean, source-bound package built from the exact reviewed revision; do not upload an older QA artifact when the source has since been integrated or changed.

A successful package upload and draft save is not certification or publication. Certification and publication remain separate steps and must not be inferred from upload success.

## Product fleet status at this handoff

The 2026-11-25 local verification does not yet establish seven upload-ready candidates:

| Product | Independent remaining issue |
|---|---|
| AI Upload Guard | Runtime QA was not verified. |
| Image Privacy Cleaner | Owner-approved Store version and artwork were missing. |
| Excel / CSV Privacy Cleaner | Owner-approved Store version and artwork were missing. |
| Data Contract Auditor | Local install returned Access Denied and EXE launch timed out; functional QA remains incomplete. Its uploader job config also remains `upload_approved: false`, carries an older source ref, and has a placeholder expected SHA. |
| PDF Privacy Toolkit | Owner-approved Store version and artwork were missing. |
| Web Evidence Archiver | Verified 1.0.55.0 artifact predates the local GUI/Store integration. The integrated source commit is unpushed, and the actual capture timed out. Build a new package from the integrated source after the runtime issue is fixed. |
| Workflow Automation Hub | The package is a technical draft without owner approval; current Submission state was not live-rechecked. |

The Partner Center IDs and Draft IDs in the 2026-11-25 observation are historical read-only values. Re-read the current Product and Draft immediately before any upload. Workflow Automation Hub has no verified existing Draft in that snapshot; do not start a Submission just to accommodate the uploader.

## Operational consequence

Do not add certificate purchase or pre-upload signing as a required task. Do not change the other product-specific approval, identity, version, source, QA, or Partner Center state gates. Upload only the exact packages whose independent gates pass, and leave Certification/Publish untouched unless explicitly authorized in a separate step.
