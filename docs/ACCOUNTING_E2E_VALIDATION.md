# Accounting E2E validation contract (Draft / no live integration)

2026-10-31 JST. Pure fail-closed contract, stacked on country-market gate Draft PR #95. NOT a live intake adapter and NOT proof that any of the four candidates passed E2E. Canonical ledger unchanged.

## Country-specific SKUs

- jp-freelance-ledger: JP / ja-JP / JPY
- jp-bookkeeping-desk: JP / ja-JP / JPY
- us-freelance-ledger: US / en-US / USD
- us-bookkeeping-desk: US / en-US / USD

No candidate can enter PRE_IDENTITY before immutable Factory promotion, exact request_id/source_sha, and independently verified MARKET_FIT_PASS.

## Required immutable files

At the promoted exact source_sha, an authenticated Factory reader must fetch:
- All four: products/<slug>/market-scope.json and products/<slug>/accounting-validation.json.
- US only: products/<slug>/US_COMPLIANCE_SCOPE.md, products/<slug>/us-compliance-policy.json, products/<slug>/store-description.txt.

The validation JSON strictly binds schema_version=1, slug, market, locale, currency, tax_filing=false, compliance_claim=false, category_suggestions_only=true, user_confirmation_required=true, confidence_and_rationale_required=true, ambiguous_input_fail_safe=true, and the exact fixture_names set.

An independently authenticated GitHub Actions reader must verify successful run at exact source SHA and match repository, slug, request_id, and every required fixture result. Self-authored JSON is not an Actions attestation.

Fixture groups:
- Freelance: monthly_net, annual_net, negative_net, decimal_rounding, currency_scope.
- Bookkeeping: debit_equals_credit, reject_unbalanced, trial_balance, profit_and_loss, balance_sheet, net_income, currency_scope.
- Both: candidate_only, confidence_and_rationale, explicit_user_confirmation, ambiguous_fail_safe.
- US: cash_accrual_locked, method_change_warning, vehicle_review, meals_review, travel_review, home_office_review, depreciation_review, cogs_review, taxes_licenses_review, no_tax_filing, no_state_local_tax_automation.

US policy must fix cash_accrual_is_cosmetic=false, method_change_warning=true, all seven special_rule_categories, and state_local_tax_automation=false, tax_filing=false, compliance_claim=false, deduction_auto_approval=false. Store copy must not claim IRS compliant, tax compliant or guaranteed deductions.

An independently authenticated official IRS review must match exact request/source, include all six primary URLs, and be at most seven days old. Changed guidance => HOLD and return to 00-minute APP owner. Do not hardcode rates, deduction limits or thresholds without year-specific official evidence.

PACKAGE phase additionally requires authenticated Partner Center Pricing and availability evidence of exactly one allowed country and all_markets_default=false. Screenshot or user-authored JSON does not prove this. This PR makes no Partner Center writes.

## Official sources checked 2026-10-31

- IRS Publication 583: https://www.irs.gov/publications/p583
- IRS Publication 538 (January 2022 revision): https://www.irs.gov/publications/p538
- IRS Form 3115: https://www.irs.gov/instructions/i3115 and https://www.irs.gov/forms-pubs/about-form-3115
- IRS Schedule C instructions (2025): https://www.irs.gov/instructions/i1040sc
- IRS Publication 463 (2025): https://www.irs.gov/publications/p463
- IRS Publication 587: https://www.irs.gov/publications/p587
- NTA No.2070 (as of 2026-04-01): https://www.nta.go.jp/taxes/shiraberu/taxanswer/shotoku/2070.htm

IRS cash/accrual method changes and special-rule deductions are fact-dependent. References in a document do not certify legal compliance or product readiness.

## Release decision

HOLD all four accounting SKUs. Factory Draft PRs #59–62 do not yet provide promoted immutable source/request, authenticated calculation fixture receipts, independent IRS review adapter, verified market fit, signed MSIX, or authenticated Partner Center single-country restriction. Next: APP owner implements and executes fixtures and manifests, then 36-minute E2E owner wires this pure gate to PRE_IDENTITY and PACKAGE boundaries. Windows/Ubuntu CI, real signed MSIX, local pull, Checker, and GUI/install QA remain separate gates. No CAS, Store upload, final submission, pricing changes, merge or main/release changes.
