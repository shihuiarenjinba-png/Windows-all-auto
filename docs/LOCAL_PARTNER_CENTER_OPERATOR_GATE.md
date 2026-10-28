# Local Partner Center operator gate — Prism Route 3D

This branch is stacked on PR #23 (exact-source local code sync guards).
It introduces a **local-only, fail-closed handoff contract**, not a Partner
Center browser driver. It does not authenticate, create a product, read
browser cookies/tokens, upload packages, submit to Store, or apply CAS.

## Prerequisites

1. Use a separate checkout of the current central ledger branch
   codex/e2e-belt-connection-20261027 and this branch.
2. On the **user's physical Windows PC**, run the exact-source worker from
   PR #23 with tests/fixtures/local_code_sync_targets.json, and verify
   three exact SHA snapshots and all three idempotent reuses.
3. Do not substitute a GitHub Actions Windows runner receipt for the physical
   local receipt. The source branch must still match the pinned SHA.

## Prepare the operator job

Run from this branch's checkout in PowerShell:

    py -3 -m scripts.local_partner_center_operator prepare --ledger "C:\path\to\central\ops\active_e2e_handoff.json" --sync-receipt "$env:LOCALAPPDATA\FactoryCodeMirror\state\last-code-sync.json" --snapshot-root "$env:LOCALAPPDATA\FactoryCodeMirror" --output "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\3d-prism-route-3d-15fdcb52e46e\operator-job.json"

This performs a second source snapshot check including remote branch HEAD,
origin, immutable SHA, and clean tree. It also verifies exact
request_id, slug, registration_type, Partner Center selection, display name,
and central allow_local_product_creation=true.

If any check fails, stop at LOCAL_PARTNER_CENTER_OPERATOR_HOLD.

## Browser operator procedure (not yet automated by this branch)

Use the existing authenticated Partner Center Edge session. Search the exact
display name **Prism Route 3D** in Apps and games Overview. Only if the
exact result count is zero and the central allow flag remains true, choose
**MSIX or PWA game** and attempt creation with the exact same name. If
there are multiple matches, a name collision, a new agreement, or an
unexpected confirmation, HOLD; do not guess or choose an alternate name.
If exactly one existing product is found, reuse it instead of creating a
duplicate.

After creation or exact existing-product reuse, verify exactly one product
in Overview and capture the Identity details locally: store_id,
reserved_display_name, identity_name, publisher, publisher_display_name,
package_family_name, package_sid. No GDK/Xbox identifiers are required.
Do not record credentials, raw HTML, session data, MFA material, or cookies.

The local capture JSON must contain those seven Identity fields, all eight
binding fields in operator-job.json (request_id, slug, source_repository,
source_branch, source_sha, registration_type, partner_center_selection,
display_name), and exactly three evidence fields:
creation_status ("CREATED" or "REUSED_EXISTING"),
overview_exact_match_count (integer 1), and identity_details_observed (true).
No other keys are permitted. These evidence values are operator attestations,
not independently authenticated browser proof.

## Validate local capture

    py -3 -m scripts.local_partner_center_operator validate --job "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\3d-prism-route-3d-15fdcb52e46e\operator-job.json" --capture "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\3d-prism-route-3d-15fdcb52e46e\captured-identity.json" --output "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\3d-prism-route-3d-15fdcb52e46e\validated-capture.json"

The worker does not print Identity values to the terminal. It refuses to
overwrite a different existing output. It rejects duplicate JSON keys,
unknown/secret fields, mismatched product/source, ambiguous search count,
missing fields, invalid Identity schema, and wrong reserved display name.

**A validated local capture is not CAS_RETURN_PASS or authenticated
Partner Center PASS.** The existing Identity scheduler/Provisioner must
independently validate and route the payload, and the existing explicit
request-scoped CAS approval must still be obtained. Version and brand assets
remain separate approval gates. No Store submission is authorized.

Current status: LOCAL_MODE reopened by user; cloud exact-source smoke PASS;
physical local source receipt NOT OBSERVED; Partner Center product creation,
Identity capture, route, CAS, and package remain unverified/HOLD.
