"""Pure negative/positive contract tests; mock PASS is not authenticated product PASS."""
import json
import unittest
from datetime import datetime, timezone

from scripts.accounting_country_gate import SPECS
from scripts.accounting_e2e_gate import (
    AccountingE2EHold, CASES, INFERENCE_CASES, US, US_CASES,
    US_SOURCES, check_accounting_e2e_gate,
)

SHA = "a" * 40
REPO = "shihuiarenjinba-png/AI-App-Factory"


def job(slug):
    return {"slug": slug, "product_type": "APP", "source_repository": REPO,
            "source_branch": "codex/reviewed-accounting", "source_sha": SHA,
            "request_id": f"app-{slug}-{SHA[:12]}",
            "identity_return_target": f"products/{slug}/store/approved-identity.json",
            "registration_type": "MSIX_OR_PWA_APP", "partner_center_selection": "MSIX or PWA app",
            "market_fit_gate": "MARKET_FIT_PASS", "market_fit_evidence_verified": True,
            "status": "PRE_IDENTITY_READY"}


def fixture(slug):
    market, locale, currency, country = SPECS[slug]
    names = CASES["freelance" if "freelance" in slug else "bookkeeping"] | INFERENCE_CASES | (US_CASES if slug in US else frozenset())
    contract = {"schema_version": 1, "slug": slug, "market": market, "locale": locale,
                "currency": currency, "tax_filing": False, "compliance_claim": False,
                "category_suggestions_only": True, "user_confirmation_required": True,
                "confidence_and_rationale_required": True, "ambiguous_input_fail_safe": True,
                "fixture_names": sorted(names)}
    policy = {"schema_version": 1, "market": "US", "locale": "en-US", "currency": "USD",
              "cash_accrual_is_cosmetic": False, "method_change_warning": True,
              "special_rule_categories": ["vehicle", "meals", "travel", "home_office",
                                          "depreciation", "cogs", "taxes_licenses"],
              "state_local_tax_automation": False, "tax_filing": False,
              "compliance_claim": False, "deduction_auto_approval": False}
    data = {f"products/{slug}/market-scope.json": json.dumps({
                "store_markets": [market], "store_language": locale, "currency": currency,
                "country_profile": country, "cross_market_sale": False}),
            f"products/{slug}/accounting-validation.json": json.dumps(contract),
            f"products/{slug}/US_COMPLIANCE_SCOPE.md": "Form 3115 cash accrual\n" + "\n".join(sorted(US_SOURCES)),
            f"products/{slug}/us-compliance-policy.json": json.dumps(policy),
            f"products/{slug}/store-description.txt": "Local bookkeeping. No tax filing or deduction decisions."}
    ci = {"verification_method": "AUTHENTICATED_GITHUB_ACTIONS_EXACT_SHA", "verified": True,
          "conclusion": "success", "repository": REPO, "source_sha": SHA,
          "request_id": f"app-{slug}-{SHA[:12]}", "slug": slug,
          "run_id": 1234, "test_results": {name: "PASS" for name in names}}
    review = {"verification_method": "INDEPENDENT_IRS_PRIMARY_SOURCE_REVIEW",
              "verified": True, "source_sha": SHA, "slug": slug,
              "request_id": f"app-{slug}-{SHA[:12]}", "change_detected": False,
              "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
              "source_urls": sorted(US_SOURCES)}
    def read(repo, path, sha):
        assert repo == REPO and sha == SHA
        return data[path]
    return data, ci, review, read


def check(slug, *, read=None, ci=None, review=None):
    data, valid_ci, valid_review, valid_read = fixture(slug)
    return check_accounting_e2e_gate(
        job(slug), phase="PRE_IDENTITY", fetch_immutable_text=read or valid_read,
        fetch_verified_ci=lambda _: valid_ci if ci is None else ci,
        fetch_official_review=lambda _: valid_review if review is None else review)


class AccountingE2EGateTests(unittest.TestCase):
    def test_four_skus_are_country_isolated(self):
        for slug in SPECS:
            with self.subTest(slug=slug):
                self.assertEqual(check(slug), ("ACCOUNTING_E2E_PRE_IDENTITY_PASS", SPECS[slug][0]))

    def test_candidate_cannot_pass(self):
        j = job("us-freelance-ledger")
        j["status"] = "CANDIDATE"
        with self.assertRaisesRegex(AccountingE2EHold, "NOT_PROMOTED"):
            check_accounting_e2e_gate(j, phase="PRE_IDENTITY", fetch_immutable_text=fixture(j["slug"])[3])

    def test_missing_immutable_contract_blocks(self):
        slug = "us-freelance-ledger"
        data, ci, review, read = fixture(slug)
        def missing(repo, path, sha):
            if path.endswith("accounting-validation.json"):
                raise KeyError(path)
            return read(repo, path, sha)
        with self.assertRaisesRegex(AccountingE2EHold, "IMMUTABLE_READ_FAILED"):
            check(slug, read=missing)

    def test_missing_failed_or_cross_product_ci_blocks(self):
        slug = "jp-bookkeeping-desk"
        data, ci, review, read = fixture(slug)
        ci["test_results"]["trial_balance"] = "FAIL"
        with self.assertRaisesRegex(AccountingE2EHold, "CI_EVIDENCE_CONFLICT"):
            check(slug, ci=ci)
        ci["test_results"].pop("trial_balance")
        with self.assertRaisesRegex(AccountingE2EHold, "CI_EVIDENCE_CONFLICT"):
            check(slug, ci=ci)
        ci = fixture(slug)[1]
        ci["slug"] = "us-bookkeeping-desk"
        with self.assertRaisesRegex(AccountingE2EHold, "CI_EVIDENCE_CONFLICT"):
            check(slug, ci=ci)

    def test_inference_fixture_and_duplicate_keys_required(self):
        slug = "jp-freelance-ledger"
        data, ci, review, read = fixture(slug)
        contract_path = f"products/{slug}/accounting-validation.json"
        contract = json.loads(data[contract_path])
        contract["fixture_names"].remove("ambiguous_fail_safe")
        data[contract_path] = json.dumps(contract)
        with self.assertRaisesRegex(AccountingE2EHold, "CONTRACT_MISMATCH"):
            check(slug, read=read)
        data[contract_path] = '{"slug":"a","slug":"b"}'
        with self.assertRaisesRegex(AccountingE2EHold, "DUPLICATE_KEY"):
            check(slug, read=read)

    def test_us_method_policy_and_marketing_claims_block(self):
        slug = "us-freelance-ledger"
        data, ci, review, read = fixture(slug)
        path = f"products/{slug}/us-compliance-policy.json"
        policy = json.loads(data[path])
        policy["state_local_tax_automation"] = True
        data[path] = json.dumps(policy)
        with self.assertRaisesRegex(AccountingE2EHold, "POLICY_UNSAFE"):
            check(slug, read=read)
        policy["state_local_tax_automation"] = False
        data[path] = json.dumps(policy)
        data[f"products/{slug}/store-description.txt"] = "IRS compliant guaranteed deduction"
        with self.assertRaisesRegex(AccountingE2EHold, "STORE_CLAIM_UNSAFE"):
            check(slug, read=read)

    def test_us_irs_change_staleness_and_untrusted_review_block(self):
        slug = "us-bookkeeping-desk"
        data, ci, review, read = fixture(slug)
        review["change_detected"] = True
        with self.assertRaisesRegex(AccountingE2EHold, "OFFICIAL_REVIEW_UNVERIFIED"):
            check(slug, review=review)
        review["change_detected"] = False
        review["reviewed_at_utc"] = "2024-01-01T00:00:00Z"
        with self.assertRaisesRegex(AccountingE2EHold, "OFFICIAL_REVIEW_STALE"):
            check(slug, review=review)
        review["source_urls"] = None
        with self.assertRaisesRegex(AccountingE2EHold, "OFFICIAL_REVIEW_UNVERIFIED"):
            check(slug, review=review)

    def test_package_cannot_pass_without_authenticated_store_scope(self):
        slug = "us-bookkeeping-desk"
        j = job(slug)
        j.update(status="POST_IDENTITY_READY", identity_store_id="9VERIFIED", identity_pfn="Exact.PFN")
        data, ci, review, read = fixture(slug)
        with self.assertRaisesRegex(AccountingE2EHold, "STORE_MARKETS_UNVERIFIED"):
            check_accounting_e2e_gate(j, phase="PACKAGE", fetch_immutable_text=read,
                fetch_verified_ci=lambda _: ci, fetch_official_review=lambda _: review)

    def test_non_accounting_is_not_blocked(self):
        self.assertEqual(check_accounting_e2e_gate({"slug": "focus-session-desk"},
                         phase="PRE_IDENTITY"), ("NOT_APPLICABLE", "NON_ACCOUNTING_SKU"))


if __name__ == "__main__":
    unittest.main()
