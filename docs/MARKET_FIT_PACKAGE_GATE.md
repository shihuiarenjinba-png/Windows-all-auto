# APP MARKET_FIT → package gate (Draft contract)

This is a **pre-MSIX** commercial-quality gate, separate from Store Identity,
package version, asset approval, signature, WACK, local GUI and final submission.

## Fail-closed behavior

- A GitHub-approved Store Identity still transitions PRE → POST when its
  immutable Factory return commit and source bindings verify.
- An APP may **not** be queued for formal MSIX/GDK packaging solely because
  its Identity was returned. Missing Factory market-fit evidence produces
  `MARKET_FIT_HOLD` and leaves `package_version_gate=HOLD`.
- The existing Provisioner is the only CAS writer. This gate performs no CAS,
  Partner Center/browser work, Store submission, upload, merge or publication.
- The reader must obtain `products/<slug>/market-fit.json` from the exact
  pinned Factory `source_sha` via authenticated GitHub contents. Reading a
  moving branch or trusting an operator/local JSON is not valid.
- The present reconciler does **not** wire an authenticated market-fit reader
  from the Windows runner. Consequently, the real APP pipeline stays on HOLD
  until Factory evidence and the reviewed reader are connected. No fabricated
  market-fit PASS is permitted.

## Proposed Factory evidence (schema_version 1)

```json
{
  "schema_version": 1,
  "slug": "<exact queue slug>",
  "request_id": "<exact queue request_id>",
  "source_repository": "<exact queue source_repository>",
  "source_branch": "<exact queue source_branch>",
  "source_sha": "<exact immutable source_sha>",
  "reviewed": true,
  "status": "MARKET_FIT_PASS",
  "score": 75,
  "why_pay": "<specific reason a buyer pays>",
  "free_alternative_difference": "<verified advantage over free substitutes>",
  "competitor_research": [
    {"competitor": "<researched competitor>", "difference": "<material difference>"}
  ]
}
```

The score must be an integer from 70 through 100, never a boolean. All
fields must bind to the exact queue job. `why_pay`, the difference from
free alternatives and at least one competitor comparison must be nonempty.
`reviewed=true` and `status=MARKET_FIT_PASS` are both required. Duplicate
JSON keys, schema errors, source conflicts, and missing data all HOLD.
The evidence is not an automatic claim of real market demand; the Factory
owner must substantiate the score and research before marking it reviewed.

## Integration sequence

1. The APP Factory owner reviews a real product's score, buyer value,
   free substitutes and competitors, then commits evidence to a pinned
   immutable Factory source commit or produces a new reviewed source pin.
2. The 36-minute E2E owner reviews the Factory evidence adapter and passes
   an authenticated GitHub immutable-ref reader into
   `reconcile_approved_return(fetch_market_fit=...)`.
3. Reconcile only the exact matching APP job. Require MARKET_FIT_PASS
   **and** separately approved Package Version/assets before formal MSIX.
4. Keep real MSIX, backlog, local pull, Checker, GUI/install and E2E PASS
   separate; never infer them from market-fit or Identity.

This PR is a code-level safety gate and regression suite, not physical
Windows or product-market validation.
