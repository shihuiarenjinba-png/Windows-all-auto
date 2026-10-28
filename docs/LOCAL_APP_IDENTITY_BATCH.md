# Local APP Identity batch

This contract handles one explicitly scheduled four-product APP batch. It does
not open Partner Center by itself and never uploads a package, submits to the
Store, changes pricing, or publishes a product.

The scheduled trigger receipt must bind automation
`6adf4b1e7654819193b997fb4fb83c85`, the current central ledger HEAD and exactly
four ordered products. Discovery fails closed when fewer or more ready APP jobs
exist, when an excluded product is mixed in, or when request IDs, slugs, source
SHAs or return targets are duplicated.

`scripts/local_identity_batch.py` persists these transitions:

1. `discover` validates all four GitHub jobs before any browser action.
2. `claim` exposes only the next ordered job and rejects a second active job.
3. The Windows operator verifies exact source and EXE evidence, then performs
   the Partner Center search/create/capture externally.
4. `scripts/local_partner_center_operator.py validate` writes a request-bound,
   versionless private receipt.
5. The APP Provisioner existing single writer performs CAS and immediate replay.
6. `complete` accepts only a result matching the active request, slug, source
   SHA and return target. A cross-product value stops the batch.

The durable state records `next_resume_index`. A product-level HOLD may be
completed as HOLD and the next index claimed. Authentication ambiguity, queue
drift, duplicate creation suspicion, cross-product contamination, or a broken
single-writer contract must stop the whole batch.

Package Version remains a separate gate. Every Identity-only result records
`package_version_gate=HOLD` and `store_submission=NOT_PERFORMED`.

## Completion evidence and fail-closed classification

The four Factory PRE_IDENTITY artifacts have separately verifiable ZIP digests,
EXE SHA-256, EXE byte counts and source HEADs. These prove a **cloud preflight**,
not local Windows source sync, an authenticated Partner Center session, or a
scheduled local run. The local operator must independently verify each snapshot
and actual Identity capture before an APP single-writer CAS.

An `APPLIED` or `EXISTING_VERIFIED` string is insufficient for batch success.
Each successful `complete` result must bind the batch ID/index, central HEAD,
queue digest, request/slug/source SHA, source snapshot HEAD, registration type,
return target, exact Overview count, authenticated UI capture, all Identity
fields, returned GitHub commit SHA and same-product `EXISTING_VERIFIED` replay.
Missing evidence raises HOLD without incrementing the success count. Global
auth/MFA ambiguity, duplicate creation, queue drift, cross-product contamination
and CAS-contract failure must stop the entire batch. Only allowlisted
product-level HOLD codes can advance to the next index.

`discover`, `claim` and `complete` share a nonblocking OS lock on the state
file. State writes are atomic and fsynced. Repeated `discover` cannot reset
completed jobs; exact `complete` replay cannot increment counters twice.
Use a distinct `--job-output` path for each batch index and never edit managed
source snapshots.

**Schedule attestation is not yet implemented.** The static fields
`trigger_origin=SCHEDULED_36_MIN_LOOP` and the automation ID are not
independent proof that a local Windows worker was invoked by the saved
schedule. The batch state therefore sets `schedule_trigger_proven=false`
and cannot report `MULTI_PRODUCT_IDENTITY_BATCH_PASS` until a trusted
scheduler-to-local attestation path is implemented and verified. A user or
script editing JSON must never upgrade this flag by assertion alone.

The contract module does not operate a browser, click Reserve product name,
capture authenticated Partner Center Identity or execute the APP CAS itself.
Those are separate local-worker integration gates. GitHub CI success for this
module does not imply those operations occurred.
