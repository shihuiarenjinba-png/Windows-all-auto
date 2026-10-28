# Local Partner Center operator gate — Prism Route 3D

This branch is stacked on PR #23 (exact-source local code sync guards).
It provides the local fail-closed receipt boundary used by the physical
Windows browser operator. It never reads browser cookies/tokens, uploads
packages, submits to Store, or implements a second CAS writer.

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

## Browser operator procedure

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
No other keys are permitted. The `capture` command writes this strict local
payload without printing Identity values to the terminal. `validate` binds it
to the GitHub queue digest, exact source snapshot, central HEAD and return
target, and optionally requires an exact operator reference comparison.

## Validate local capture

    py -3 -m scripts.local_partner_center_operator validate --job "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\3d-prism-route-3d-15fdcb52e46e\operator-job.json" --capture "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\3d-prism-route-3d-15fdcb52e46e\captured-identity.json" --output "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\3d-prism-route-3d-15fdcb52e46e\validated-capture.json"

The worker does not print Identity values to the terminal. It refuses to
overwrite a different existing output. It rejects duplicate JSON keys,
unknown/secret fields, mismatched product/source, ambiguous search count,
missing fields, invalid Identity schema, and wrong reserved display name.

Schema validation by itself is not CAS return. A physical UI capture is marked
authenticated only when the exact product count is one, all seven UI values
are observed, the reference comparison is `MATCH`, and the GitHub/source
binding remains exact. The existing Provisioner must still independently
route it through the single writer. Version and brand assets remain separate
approval gates. No Store submission is authorized.

## 2026-10-28 physical Prism Route 3D retry

- GitHub PRE_IDENTITY origin: `shihuiarenjinba-png/Windows-all-auto`, branch
  `codex/e2e-belt-connection-20261027`, HEAD
  `43dacc1747eb75002a54375ba79c4cecbfc138bf`.
- Queue job digest: `7a4f4e282bc4bc78be18974539d8b33e3681282787ed82aa97463e7af5f604b8`.
- Exact physical source snapshot was reused at
  `15fdcb52e46e35e6de8e87c55af99719c21e09b9`.
- Partner Center Overview exact search returned one existing product. No
  duplicate product was created. Product Identity and reserved name were read
  from the authenticated UI and matched the user-supplied reference.
- Local receipt status:
  `IDENTITY_CAPTURED__UI_MATCHED_REFERENCE__GITHUB_BOUND`.
- Store submission, package upload, certification and price changes: zero.
- Package Version is deliberately absent and remains
  `PACKAGE_VERSION_GATE=HOLD`.

Current status: LOCAL_MODE reopened by user; cloud exact-source smoke PASS;
physical local source receipt NOT OBSERVED; Partner Center product creation,
Identity capture, route, CAS, and package remain unverified/HOLD.
