"""Offline accounting intake regressions; mocked callbacks are NOT live evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from all_auto.handoff_bridge import stage_bundle

SOURCE_SHA = "b" * 40
BUILD_SHA = "a" * 40
PAYLOAD = b"offline-accounting-fixture"


class AccountingIntakeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "incoming"
        self.source.mkdir()
        self.queue = self.root / "queue"
        self.slug = "jp-freelance-ledger"
        xml = (
            b'<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
            b'<Identity Name="OkinawaDesktopTools.JPBook" Publisher="CN=ABC" Version="1.2.3.0"/>'
            b'<Applications><Application Executable="app.exe"/></Applications></Package>'
        )
        with zipfile.ZipFile(self.source / "package.msix", "w") as archive:
            archive.writestr("AppxManifest.xml", xml)
            archive.writestr("AppxBlockMap.xml", b"<BlockMap/>")
            archive.writestr("[Content_Types].xml", b"<Types/>")
            archive.writestr("app.exe", PAYLOAD)
        raw = (self.source / "package.msix").read_bytes()
        self.meta = {
            "schema_version": 1,
            "source_repository": "https://github.com/shihuiarenjinba-png/AI-App-Factory",
            "source_sha": SOURCE_SHA,
            "expected_head_sha": SOURCE_SHA,
            "factory_head_sha": BUILD_SHA,
            "type": "app",
            "product_type": "APP",
            "source_factory": "AI-App-Factory",
            "source_branch": "codex/accounting-fixture",
            "request_id": f"app-{self.slug}-{SOURCE_SHA[:12]}",
            "slug": self.slug,
            "display_name": "JP Freelance Ledger",
            "store_id": "9PTESTING",
            "prebuilt_exe_sha256": hashlib.sha256(PAYLOAD).hexdigest(),
            "package": "package.msix",
            "status": "QA_UNSIGNED",
            "package_sha256": hashlib.sha256(raw).hexdigest(),
            "package_bytes": len(raw),
            "identity": {
                "name": "OkinawaDesktopTools.JPBook",
                "publisher": "CN=ABC",
                "version": "1.2.3.0",
            },
        }
        self.write()

    def write(self):
        (self.source / "handoff.json").write_text(
            json.dumps(self.meta), encoding="utf-8"
        )

    @staticmethod
    def mock_attestation(info):
        market = "JP" if info["slug"].startswith("jp-") else "US"
        return {
            "verification_method": "INDEPENDENT_ACCOUNTING_PACKAGE_GATE",
            "verified": True,
            "phase": "PACKAGE",
            "gate": "ACCOUNTING_E2E_PACKAGE_PRECHECK_PASS",
            "source_repository": "shihuiarenjinba-png/AI-App-Factory",
            "slug": info["slug"],
            "request_id": info["request_id"],
            "source_sha": info["source_sha"],
            "factory_build_head": info["factory_head_sha"],
            "package_sha256": info["package_sha256"],
            "store_id": info["claimed_store_id"],
            "identity_name": info["identity"]["name"],
            "identity_publisher": info["identity"]["publisher"],
            "package_version": info["identity"]["version"],
            "market": market,
            "store_markets": [market],
            "all_markets_default": False,
            "market_fit_verified": True,
        }

    def test_accounting_default_bridge_holds_before_copy(self):
        self.meta["accounting_e2e_gate"] = "ACCOUNTING_E2E_PACKAGE_PRECHECK_PASS"
        self.meta["market_fit_verified"] = True
        self.write()
        with self.assertRaisesRegex(ValueError, "AUTHENTICATED_GATE_MISSING"):
            stage_bundle(self.source, self.queue, BUILD_SHA)
        self.assertFalse(self.queue.exists())

    def test_mocked_trusted_callback_binds_exact_bytes_and_rechecks_replay(self):
        calls = []
        def attestor(info):
            calls.append(info["package_sha256"])
            return self.mock_attestation(info)
        first = stage_bundle(
            self.source, self.queue, BUILD_SHA, accounting_attestor=attestor
        )
        second = stage_bundle(
            self.source, self.queue, BUILD_SHA, accounting_attestor=attestor
        )
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 2)
        self.assertFalse(first["submit_allowed"])
        self.assertFalse(first["security_confirmed"])

    def test_cross_product_or_unsafe_evidence_is_rejected(self):
        for key, bad in (
            ("slug", "us-freelance-ledger"),
            ("request_id", "app-us-freelance-ledger-" + SOURCE_SHA[:12]),
            ("source_sha", "c" * 40),
            ("factory_build_head", "c" * 40),
            ("package_sha256", "d" * 64),
            ("store_id", "9POTHER"),
            ("identity_name", "Other"),
            ("package_version", "9.9.9.9"),
            ("market", "US"),
            ("store_markets", ["JP", "US"]),
            ("all_markets_default", 0),
            ("market_fit_verified", 1),
            ("verified", 1),
            ("phase", "PRE_IDENTITY"),
        ):
            with self.subTest(key=key):
                def bad_attestor(info):
                    return self.mock_attestation(info) | {key: bad}
                with self.assertRaisesRegex(ValueError, "EVIDENCE_CONFLICT"):
                    stage_bundle(
                        self.source, self.queue, BUILD_SHA,
                        accounting_attestor=bad_attestor,
                    )
                self.assertFalse(self.queue.exists())

    def test_missing_or_failed_attestor_never_leaks_secrets(self):
        def failing(_):
            raise RuntimeError("token=PRIVATE_SECRET")
        with self.assertRaisesRegex(ValueError, "^HOLD_ACCOUNTING_INTAKE_GATE_UNAVAILABLE$") as caught:
            stage_bundle(
                self.source, self.queue, BUILD_SHA,
                accounting_attestor=failing,
            )
        self.assertNotIn("PRIVATE_SECRET", str(caught.exception))
        self.assertFalse(self.queue.exists())

    def test_source_request_collision_rejected_even_with_mock_pass(self):
        self.meta["request_id"] = "app-other-" + SOURCE_SHA[:12]
        self.write()
        with self.assertRaisesRegex(ValueError, "PROVENANCE_CONFLICT"):
            stage_bundle(
                self.source, self.queue, BUILD_SHA,
                accounting_attestor=self.mock_attestation,
            )
        self.assertFalse(self.queue.exists())

    def test_us_requires_us_only_market(self):
        self.slug = "us-bookkeeping-desk"
        self.meta["slug"] = self.slug
        self.meta["request_id"] = f"app-{self.slug}-{SOURCE_SHA[:12]}"
        self.write()
        def wrong_market(info):
            return self.mock_attestation(info) | {"store_markets": ["JP"]}
        with self.assertRaisesRegex(ValueError, "EVIDENCE_CONFLICT"):
            stage_bundle(
                self.source, self.queue, BUILD_SHA,
                accounting_attestor=wrong_market,
            )
        self.assertFalse(self.queue.exists())

    def test_accounting_request_id_cannot_be_relabelled_as_ordinary_app(self):
        # A partial alias must not skip the accounting PACKAGE attestor.
        self.meta["slug"] = "ordinary-app"
        self.write()
        with self.assertRaisesRegex(ValueError, "HOLD_ACCOUNTING_INTAKE_SKU_ALIAS"):
            stage_bundle(self.source, self.queue, BUILD_SHA)
        self.assertFalse(self.queue.exists())

    def test_accounting_alias_rejected_from_return_target_branch_or_display(self):
        for field, value in (
            ("identity_return_target",
             "products/jp-freelance-ledger/store/approved-identity.json"),
            ("source_branch", "codex/app-jp-freelance-ledger-release"),
            ("display_name", "JP Freelance Ledger"),
        ):
            with self.subTest(field=field):
                self.meta["slug"] = "ordinary-app"
                self.meta["request_id"] = "app-ordinary-app-" + SOURCE_SHA[:12]
                self.meta["source_branch"] = "codex/ordinary-app"
                self.meta["display_name"] = "Ordinary App"
                self.meta.pop("identity_return_target", None)
                self.meta[field] = value
                self.write()
                with self.assertRaisesRegex(ValueError, "HOLD_ACCOUNTING_INTAKE_SKU_ALIAS"):
                    stage_bundle(self.source, self.queue, BUILD_SHA)
                self.assertFalse(self.queue.exists())

    def test_accounting_cross_lane_alias_rejected_before_queue(self):
        self.meta["slug"] = "ordinary-game"
        self.meta["request_id"] = "game-ordinary-game-" + SOURCE_SHA[:12]
        self.meta["source_repository"] = (
            "https://github.com/shihuiarenjinba-png/AI-Game-Factory"
        )
        self.meta["type"] = "game"
        self.meta["product_type"] = "GAME"
        self.meta["identity_return_target"] = (
            "products/jp-freelance-ledger/store/approved-identity.json"
        )
        self.write()
        with self.assertRaisesRegex(ValueError, "HOLD_ACCOUNTING_INTAKE_SKU_ALIAS"):
            stage_bundle(self.source, self.queue, BUILD_SHA)
        self.assertFalse(self.queue.exists())

    def test_duplicate_handoff_json_keys_fail_closed(self):
        raw = json.dumps(self.meta)
        (self.source / "handoff.json").write_text(
            raw[:-1] + ', "slug": "ordinary-app"}', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "duplicate handoff JSON key"):
            stage_bundle(self.source, self.queue, BUILD_SHA)
        self.assertFalse(self.queue.exists())

    def test_boolean_schema_version_and_nonfinite_json_fail_closed(self):
        self.meta["schema_version"] = True
        self.write()
        with self.assertRaisesRegex(ValueError, "wrong schema"):
            stage_bundle(self.source, self.queue, BUILD_SHA)
        self.meta["schema_version"] = 1
        raw = json.dumps(self.meta)
        (self.source / "handoff.json").write_text(
            raw[:-1] + ', "extra": NaN}', encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "non-finite handoff JSON value"):
            stage_bundle(self.source, self.queue, BUILD_SHA)
        self.assertFalse(self.queue.exists())

    def test_other_apps_keep_existing_qa_behavior(self):
        self.meta["slug"] = "ordinary-app"
        self.meta["request_id"] = "app-ordinary-app-" + SOURCE_SHA[:12]
        self.meta["display_name"] = "Ordinary App"
        self.write()
        result = stage_bundle(self.source, self.queue, BUILD_SHA)
        self.assertEqual(result["slug"], "ordinary-app")
        self.assertFalse(result["submit_allowed"])


if __name__ == "__main__":
    unittest.main()
