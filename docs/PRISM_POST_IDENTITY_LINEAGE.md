# Prism Route 3D: immutable source vs observed Identity-return commit

This read-only audit is a **reconciliation candidate classifier**, not a CAS receipt generator.

- Pinned PRE_IDENTITY source: `15fdcb52e46e35e6de8e87c55af99719c21e09b9`
- Observed Factory branch HEAD: `11417b75636ee18816028ffd5221884c4c9a9836`
- GitHub compare: one descendant commit, one added file `products/prism-route-3d/store/approved-identity.json`
- The file contains the seven values matching the user's manual Partner Center reference. This is **not** independent browser capture, proof of request-scoped CAS approval, or authorized Store packaging.

## Physical Windows read-only audit

Use **separate clean clones** for central `codex/e2e-belt-connection-20261027` and 3D Factory `codex/3d-canary-prism-route-20261028`. Never reset an existing development checkout.

From the reviewed PR #27 checkout:

```powershell
py -3 -m scripts.prism_identity_lineage_audit `
  --central-checkout "C:\path\to\independent-central-clone" `
  --source-checkout "C:\path\to\independent-3d-factory-clone" `
  --manual-reference "tests\fixtures\prism_route_3d_manual_reference.json"
```

The worker verifies both remote HEADs, exact HTTPS origins, clean checkouts, the single-parent relationship, sole added Identity file, request/source/executable SHA binding, and all seven manual-reference fields. It prints only a sanitized non-authorizing classification. It never reads browser sessions, creates products, writes receipts to GitHub, changes the source branch, calls CAS, uploads packages or submits to Store.

Expected candidate classification: `POST_IDENTITY_COMMIT_CANDIDATE__CAS_RECEIPT_UNVERIFIED`, with `local_code_sync=HOLD_REMOTE_HEAD_CONFLICT` and `cas_return_pass=false`. A PASS from this audit **must not** bypass the hardened PR #23 source-sync remote-HEAD guard. If a commit differs, HOLD and review; do not repin source SHA.

Before any further route, require independently verified local UI capture and request-scoped approval/receipt from the existing Provisioner single-writer CAS path. The 3D scheduler routing gap and Version/asset approval are separate HOLD gates. The old source SHA remains immutable even if the later Identity commit is ultimately authorized. GUI/install and real MSIX checks remain independent.
