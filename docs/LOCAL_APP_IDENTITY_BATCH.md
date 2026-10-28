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
