# Multi-product PRE-IDENTITY rotation (Draft PR #20)

This is a cloud-contract-only extension stacked on Identity handoff PR #19. It
does not obtain Partner Center Identity, invoke CAS, build packages, or run local
GUI/install QA. Do not merge or apply CAS without explicit authorization.

## Check-only

```powershell
python -m scripts.rotation_identity_queue --check-only
```

To write a new **private** draft after verifying the central ledger and remote
HEADs, use a path outside every Git worktree:

```powershell
python -m scripts.rotation_identity_queue --output "$env:LOCALAPPDATA\FactoryIdentityWorker\secure\rotation-jobs.json"
```

Existing queue files are never overwritten. The local scheduler still runs one
job at a time with its existing lock/idempotency and explicit per-request CAS
approval. APP/3D routing remains a safe HOLD until the appropriate Provisioner
return contract is reviewed and implemented; Signal Sprint delegates to the
existing GAME CAS worker.

## Central contract

The **36-minute lane alone** writes `ops/active_e2e_handoff.json`.
`rotation_cohorts.app_jobs` accepts at most five APP products **including** a
promoted primary Offline Notes Canary. `rotation_cohorts.three_d_jobs`
accepts one 3D Canary. Unpromoted products remain deferred and cannot borrow
another product's Identity.

A READY rotation entry requires `product_type`, `slug`, `request_id`,
`source_repository`, `source_branch`, `source_sha`,
`factory_build_branch`, `factory_build_head`, `expected_exe_sha256`,
`artifact_provenance=REAL_WINDOWS_EXPORT_VERIFIED`, final
`packaging_family`, `registration_type`, and
`partner_center_selection`. Both source and build branch HEADs must match
the pinned SHA. A separate matching `user_id_requests.items` entry must
contain the same request_id/repo/branch/source_sha/slug/product_type and the
private Identity target template. A missing or mismatched binding fails closed.

For Prism Route 3D, a Godot EXE/PCK is **intermediate**, not a Store
registration type. Only verified Godot-to-MakeAppx standard MSIX evidence
allows `MSIX_OR_PWA_GAME` / `MSIX or PWA game`. Do not label it GDK or
claim PRE_IDENTITY_READY from CI alone.

## Gates and metrics

The queue reports APP `total_jobs`, `pre_identity_pass`,
`waiting_user_identity`, `identity_received`, `conflicts`, `retries`,
`artifact_mismatch`, `schema_conflict`, `cross_product_rejection`, and
3D `3d_total_jobs`, `3d_pre_identity_pass`, `3d_waiting_identity`,
`3d_conflicts`, `3d_artifact_mismatch`. Zero conflict counters mean **no
recorded live conflicts**, not that the system was stress-tested with five real
products. Regression tests separately exercise rejection paths.

LOCAL_UNAVAILABLE_MODE keeps local EXE recheck, Identity validation, CAS,
Local pull, Checker, and GUI/install QA as DEFERRED_LOCAL_GATE. Do not promote
those gates to PASS from GitHub CI.
