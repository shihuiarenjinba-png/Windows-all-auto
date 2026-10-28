# PRE-IDENTITY queue bridge (user-managed Identity)

This bridge reads the live central E2E ledger at
`codex/e2e-belt-connection-20261027`, checks the immutable GAME Factory
source HEAD, the latest observed Provisioner HEAD, the pinned unsigned
Windows EXE SHA-256, and the central USER_ID_REQUEST entry. It creates
**only a draft local queue**. It never downloads Identity, opens Partner
Center, performs CAS, uploads a package, or changes a product branch.

Run from a PR #18 checkout with authenticated `gh` read access:

```powershell
py -3 -m scripts.pre_identity_queue --check-only
py -3 -m scripts.pre_identity_queue --output "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\pre-identity-jobs.json"
```

The output is created with no-overwrite semantics. It belongs outside Git
checkouts and must be protected with user-only ACLs. It contains no Identity
values, authentication material or private evidence. Do not commit it.

The generated GAME job has `package_path: null`. Before passing the queue
to `scripts.local_identity_scheduler`, the local operator must obtain
the **already verified** Factory EXE artifact, compare its extracted EXE
SHA-256 against `package_sha256`, and set `package_path` to the real
private local EXE path. The artifact ZIP SHA-256 and extracted EXE SHA-256
are different checks; never substitute one for the other.

Every new queue job also carries one registration handoff from Factory and
Provisioner evidence through the local scheduler:

- `product_type`, `packaging_family`, and `build_artifact_kind`
- one of `MSIX_OR_PWA_APP`, `EXE_OR_MSI_APP`, `GDK_GAME`, or
  `MSIX_OR_PWA_GAME`, plus the exact Partner Center selection label
- `registration_reason` and immutable `registration_evidence`
- `store_identity_status`, `required_identity_fields`, and
  `user_registration_required`
- `registration_event` and `next_action`

The final packaging family decides the registration type. An intermediate EXE
is preserved as `build_artifact_kind` evidence and never reclassifies an MSIX
app as an EXE/MSI app. Missing or contradictory packaging evidence is
`HOLD_REGISTRATION_TYPE_UNRESOLVED` or `REGISTRATION_*_CONFLICT`.

`--check-only` prints `registration_requests` for the operator. A product with
missing Identity emits `USER_ID_REQUEST` with the exact Partner Center choice
and required fields. A product whose Identity was already received emits no
repeat request. Signal Sprint therefore says `GDK game` and no new Partner
Center action; Offline Notes Canary says `MSIX or PWA app` and waits for formal
Factory promotion/source binding without requesting its already received
Identity again.

If the APP canary is not formally promoted with a source SHA, request_id,
real EXE SHA and verified branch HEAD, it is deferred as NOT_YET_REQUIRED.
No second APP, GAME or 3D product is created. Store known-good products
with existing Identity references are not newly requested.

After package preflight, missing user-provided official Identity must yield
WAITING_USER_IDENTITY. The user obtains it independently and places the
private file at the designated location. Only the existing dedicated
Provisioner/worker may perform a separately approved CAS. A queue draft
is not PRE_IDENTITY_READY for real local execution, not Identity PASS,
not real MSIX PASS and not E2E PASS.

The central ledger remains owned exclusively by the 36-minute E2E lane.
This stacked feature branch does not edit `ops/active_e2e_handoff.json`.
