# Store package archive and live write gates

## Exact package archive

`python -m all_auto store archive --product <product-key>` resolves the product's registered package, verifies its configured SHA-256 and MSIX Manifest, and creates an immutable local archive under `portfolio-audit/_runtime/store-fleet-sync/durable-package-archive` by default. The path is keyed by Product ID, Version, and SHA-256. A JSON receipt binds the package to its source commit, GitHub Artifact ID/run, Submission ID, Identity, Publisher, Architecture, signature state, and capture time. Repeating the command verifies the existing bytes and receipt; it never replaces them.

GitHub Actions artifacts remain temporary. The DCA source artifact 15005358857 was observed as created on 2026-11-25 and scheduled to expire on 2026-12-25. The local archive protects against that expiration while this workstation and its storage remain available. It is not a disaster-recovery backup; copy the archive and receipt to the organization's approved backup location. Do not commit MSIX binaries to this public repository or publish a release asset without a separate owner decision.

Example:

```powershell
python -m all_auto store archive --product data-contract-auditor
```

For a verified package at a known local path:

```powershell
python -m all_auto store archive --product data-contract-auditor --package C:\path\DataContractSchemaDrift_1.0.0.0_x64.msix --archive-root C:\approved\archive
```

## Shared live package gate

`store run`, `store apply --section packages`, `uploader.run --execute`, and direct `process_job(..., dry_run=False)` all pass through the same `uploader.live_gates.package_write_hold_reason` check. Live package writes require an exact package SHA, an exact-package Windows runtime QA receipt, a Product/Draft-bound package execution approval, a Product/Draft-bound device-family approval that covers Manifest targets, and explicit existing-Draft-only scope. Certification and Publish must remain false. A failure is returned before an upload attempt is reserved or a browser upload adapter is called.

The current DCA profile remains `PLAN_ONLY`: its packaged runtime QA is unresolved and its device-family and execution approvals are pending. Therefore `store run --product data-contract-auditor` gathers evidence and reports holds; it does not upload.

## UI map evidence

The map records live-observed DCA navigation links and Packages screen content. The current observation showed an empty package list, a single package file input, Desktop unchecked, and the future-device-family option checked. Properties, Store listings, Pricing, Age ratings, and Submission Options route links were visible, but their page contents and Save/reload behavior were not observed. Their `verified` flags remain false and the live form engine will refuse writes through those unverified maps.
