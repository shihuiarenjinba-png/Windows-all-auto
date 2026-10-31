"""Country isolation regressions; no GitHub/Store access."""
import json
import unittest

from scripts.accounting_country_gate import (
    SPECS, CountryMarketHold, check_accounting_country_gate,
)

SHA = "a" * 40


def job(slug):
    return {
        "slug": slug, "product_type": "APP",
        "source_repository": "shihuiarenjinba-png/AI-App-Factory",
        "source_branch": "codex/app-accounting-immutable",
        "source_sha": SHA, "request_id": f"app-{slug}-{SHA[:12]}",
        "identity_return_target": f"products/{slug}/store/approved-identity.json",
        "registration_type": "MSIX_OR_PWA_APP",
        "partner_center_selection": "MSIX or PWA app",
        "market_fit_gate": "MARKET_FIT_PASS",
        "market_fit_evidence_verified": True,
        "status": "PRE_IDENTITY_READY",
    }


def scope(slug):
    market, language, currency, country = SPECS[slug]
    data = {"store_markets": [market], "store_language": language,
            "currency": currency, "country_profile": country,
            "cross_market_sale": False}
    if slug.startswith("us-"):
        data.update({
            "federal_scope": (
                "sole_proprietor_recordkeeping_and_schedule_c_preparation_support"
                if slug == "us-freelance-ledger" else
                "general_business_bookkeeping_records_not_tax_return_preparation"
            ),
            "state_local_tax_automation": False,
            "tax_filing": False,
            "deductibility_determination": False,
            "compliance_claim": False,
        })
    return json.dumps(data)


def reader(slug):
    def fetch(repo, path, sha):
        assert repo == "shihuiarenjinba-png/AI-App-Factory"
        assert path == f"products/{slug}/market-scope.json"
        assert sha == SHA
        return scope(slug)
    return fetch


class AccountingCountryGateTests(unittest.TestCase):
    def test_all_four_skus_have_separate_exact_market_scope(self):
        for slug, expected in SPECS.items():
            with self.subTest(slug=slug):
                self.assertEqual(check_accounting_country_gate(
                    job(slug), phase="PRE_IDENTITY",
                    fetch_immutable_scope=reader(slug)),
                    ("ACCOUNTING_PRE_IDENTITY_COUNTRY_SCOPE_PASS", expected[0]))

    def test_candidate_cannot_enter_queue_without_promotion(self):
        for slug in SPECS:
            with self.subTest(slug=slug):
                candidate = job(slug)
                candidate.pop("source_sha")
                candidate.pop("request_id")
                with self.assertRaisesRegex(CountryMarketHold, "PROMOTION_BINDING"):
                    check_accounting_country_gate(candidate, phase="PRE_IDENTITY",
                                                  fetch_immutable_scope=reader(slug))

    def test_unreviewed_market_fit_and_untrusted_scope_block(self):
        j = job("jp-freelance-ledger")
        j["market_fit_gate"] = "MARKET_FIT_HOLD"
        with self.assertRaisesRegex(CountryMarketHold, "MARKET_FIT"):
            check_accounting_country_gate(j, phase="PRE_IDENTITY",
                                          fetch_immutable_scope=reader(j["slug"]))
        j["market_fit_gate"] = "MARKET_FIT_PASS"
        with self.assertRaisesRegex(CountryMarketHold, "READER_MISSING"):
            check_accounting_country_gate(j, phase="PRE_IDENTITY")

    def test_reject_all_markets_cross_country_and_duplicate_keys(self):
        j = job("jp-bookkeeping-desk")
        for bad in (
            scope(j["slug"]).replace('"JP"', '"JP", "US"'),
            scope(j["slug"]).replace('"JPY"', '"USD"'),
            scope(j["slug"]).replace('"cross_market_sale": false',
                                     '"cross_market_sale": true'),
        ):
            with self.assertRaisesRegex(CountryMarketHold, "COUNTRY_SCOPE_MISMATCH"):
                check_accounting_country_gate(j, phase="PRE_IDENTITY",
                                              fetch_immutable_scope=lambda *_: bad)
        duplicate = '{"store_markets":["JP"],"store_markets":["US"]}'
        with self.assertRaisesRegex(CountryMarketHold, "DUPLICATE_KEY"):
            check_accounting_country_gate(j, phase="PRE_IDENTITY",
                                          fetch_immutable_scope=lambda *_: duplicate)

    def test_us_extended_scope_requires_exact_safe_policy(self):
        for slug in ("us-freelance-ledger", "us-bookkeeping-desk"):
            valid = json.loads(scope(slug))
            for field, bad_value in (
                ("state_local_tax_automation", True),
                ("tax_filing", True),
                ("deductibility_determination", True),
                ("compliance_claim", True),
                ("federal_scope", "another_market_or_product"),
            ):
                with self.subTest(slug=slug, field=field):
                    bad = dict(valid, **{field: bad_value})
                    with self.assertRaisesRegex(
                        CountryMarketHold, "COUNTRY_SCOPE_MISMATCH"
                    ):
                        check_accounting_country_gate(
                            job(slug), phase="PRE_IDENTITY",
                            fetch_immutable_scope=lambda *_: json.dumps(bad),
                        )
            missing = dict(valid)
            missing.pop("federal_scope")
            with self.assertRaisesRegex(CountryMarketHold, "SCOPE_SCHEMA_INVALID"):
                check_accounting_country_gate(
                    job(slug), phase="PRE_IDENTITY",
                    fetch_immutable_scope=lambda *_: json.dumps(missing),
                )
        jp = json.loads(scope("jp-bookkeeping-desk"))
        jp["federal_scope"] = "us-only"
        with self.assertRaisesRegex(CountryMarketHold, "SCOPE_SCHEMA_INVALID"):
            check_accounting_country_gate(
                job("jp-bookkeeping-desk"), phase="PRE_IDENTITY",
                fetch_immutable_scope=lambda *_: json.dumps(jp),
            )

    def test_integer_zero_cannot_impersonate_false_market_flags(self):
        for slug in SPECS:
            valid = json.loads(scope(slug))
            flags = ["cross_market_sale"]
            if slug.startswith("us-"):
                flags += ["state_local_tax_automation", "tax_filing",
                          "deductibility_determination", "compliance_claim"]
            for flag in flags:
                with self.subTest(slug=slug, flag=flag):
                    unsafe = dict(valid, **{flag: 0})
                    with self.assertRaisesRegex(
                        CountryMarketHold, "SCOPE_BOOLEAN_INVALID"
                    ):
                        check_accounting_country_gate(
                            job(slug), phase="PRE_IDENTITY",
                            fetch_immutable_scope=lambda *_: json.dumps(unsafe),
                        )

    def test_package_requires_authenticated_exact_store_availability(self):
        slug = "us-bookkeeping-desk"
        j = job(slug)
        j.update(status="POST_IDENTITY_READY", identity_store_id="9ABC12345678",
                 identity_pfn="OkinawaDesktopTools.USBookkeeping_abcdefghijklm")
        kwargs = dict(phase="PACKAGE", fetch_immutable_scope=reader(slug))
        with self.assertRaisesRegex(CountryMarketHold, "MARKETS_UNVERIFIED"):
            check_accounting_country_gate(j, **kwargs)
        observed = {"verification_method": "AUTHENTICATED_PARTNER_CENTER_PRICING_AVAILABILITY",
                    "verified": True, "request_id": j["request_id"],
                    "source_sha": SHA, "slug": slug,
                    "store_id": j["identity_store_id"], "markets": ["US"],
                    "all_markets_default": False}
        self.assertEqual(check_accounting_country_gate(
            j, fetch_verified_store_availability=lambda _: observed, **kwargs),
            ("ACCOUNTING_COUNTRY_STORE_MARKET_PASS", "US"))
        for changed in ({"markets": ["US", "JP"]}, {"markets": ["JP"]},
                        {"all_markets_default": True}, {"verified": False},
                        {"store_id": "OTHER"}, {"request_id": "OTHER"}):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(CountryMarketHold, "EVIDENCE_CONFLICT"):
                    check_accounting_country_gate(
                        j, fetch_verified_store_availability=lambda _, change=changed:
                        {**observed, **change}, **kwargs)

    def test_cross_market_identity_reuse_and_request_reuse_block(self):
        j = job("jp-freelance-ledger")
        j["identity_store_id"] = "9REUSED"
        other = job("us-freelance-ledger")
        other["identity_store_id"] = "9REUSED"
        with self.assertRaisesRegex(CountryMarketHold, "IDENTITY_REUSE"):
            check_accounting_country_gate(j, phase="PRE_IDENTITY",
                                          fetch_immutable_scope=reader(j["slug"]),
                                          other_jobs=[other])
        other.pop("identity_store_id")
        other["request_id"] = j["request_id"]
        with self.assertRaisesRegex(CountryMarketHold, "CROSS_PRODUCT_BINDING"):
            check_accounting_country_gate(j, phase="PRE_IDENTITY",
                                          fetch_immutable_scope=reader(j["slug"]),
                                          other_jobs=[other])

    def test_malformed_job_and_reader_errors_hold_with_fixed_codes(self):
        with self.assertRaisesRegex(CountryMarketHold, "JOB_INVALID"):
            check_accounting_country_gate({"slug": []}, phase="PRE_IDENTITY")
        j = job("jp-freelance-ledger")
        with self.assertRaisesRegex(CountryMarketHold, "SCOPE_READ_FAILED"):
            check_accounting_country_gate(j, phase="PRE_IDENTITY",
                                          fetch_immutable_scope=lambda *_: 1 / 0)

    def test_non_accounting_not_affected(self):
        self.assertEqual(check_accounting_country_gate(
            {"slug": "focus-session-desk"}, phase="PRE_IDENTITY"),
            ("NOT_APPLICABLE", "NON_ACCOUNTING_SKU"))


if __name__ == "__main__":
    unittest.main()
