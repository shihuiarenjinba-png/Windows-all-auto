# Immutable Factory MARKET_FIT review commit (APP only)

## Why this is separate

The immutable PRE_IDENTITY source SHA for existing APP products predates the MARKET_FIT requirement. Adding `market-fit.json` to that SHA is impossible and rewriting the source SHA would invalidate EXE/Identity provenance. Do not modify the existing source or approved Identity return branch to manufacture a pass.

## Review-only evidence branch

1. Begin a new `codex/*` review branch **at the exact existing immutable source_sha**, not at the moving source branch or the later Identity CAS commit.
2. Add exactly one file: `products/<slug>/market-fit.json`. The commit must add no other files. Keep this branch unmerged and never use its HEAD as the Factory product source/build SHA.
3. Use the `market_fit_gate.py` schema: `schema_version=1`, exact `slug/request_id/source_repository/source_branch/source_sha`, `status=MARKET_FIT_PASS`, `reviewed=true`, integer `score>=70`, substantive `why_pay`, `free_alternative_difference`, and nonempty `competitor_research` entries with `competitor` and `difference`. These values must reflect an actual Factory-side assessment; never invent market evidence or infer approval.
4. After review, the **36-minute central-ledger writer only** may pin the exact full 40-character review commit SHA as `market_fit_review_commit_sha` in the matching APP rotation job. Keep original `source_sha` and `identity_return_commit_sha` unchanged.
5. The read-only verifier compares immutable `source_sha...market_fit_review_commit_sha` via authenticated GitHub. It requires exactly one descendant commit, zero behind, exact merge base and exactly one **added** file matching that slug. It then reads the file at the immutable review SHA and validates all original source/request bindings.
6. No review SHA, no authenticated read, a different product, extra changed files, invalid score, missing competitor evidence or review-commit drift means `MARKET_FIT_HOLD`. A valid Identity return can still become `POST_IDENTITY_READY`; the package gate stays HOLD.
7. `MARKET_FIT_PASS` is only one prerequisite. Separately require Package Version, assets, real signed Store package, embedded Identity/hash, GitHub backlog, local pull, Checker and Windows GUI/install QA. No Store upload, certification submission, pricing, publish, merge or main/release write is authorized by this evidence.

## Code entrypoints

- `scripts.market_fit_review_reader.assess_reviewed_market_fit(job)`: read-only `MARKET_FIT_PASS/HOLD` decision.
- `scripts.market_fit_review_reader.reconcile_with_reviewed_market_fit(...)`: returns a proposed ledger copy; never commits it. Must be called with independently authenticated Identity branch HEAD, approved-file and ancestry callbacks.
- `tests/test_market_fit_review_reader.py`: offline negative and positive regressions.

This is a new **opt-in** contract. Existing products without reviewed review-only commits remain MARKET_FIT_HOLD. Do not mark any real product PASS from code tests.
