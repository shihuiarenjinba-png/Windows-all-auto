"""Offline trust-boundary tests. Mock responses are not live Factory evidence."""
import base64
import hashlib
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.accounting_immutable_github_reader import (
    AccountingImmutableReadHold, read_accounting_immutable_text,
)

REPO = "shihuiarenjinba-png/AI-App-Factory"
SHA = "a" * 40
PATH = "products/jp-freelance-ledger/market-scope.json"
US_PATH = "products/us-bookkeeping-desk/US_COMPLIANCE_SCOPE.md"


def response(path=PATH, raw=b'{"store_markets":["JP"]}', **changes):
    blob = hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()
    payload = {
        "type": "file", "path": path, "encoding": "base64",
        "size": len(raw), "sha": blob,
        "content": base64.b64encode(raw).decode("ascii"),
    }
    payload.update(changes)
    return subprocess.CompletedProcess([], 0, json.dumps(payload), "")


class AccountingImmutableGithubReaderTests(unittest.TestCase):
    @patch("scripts.accounting_immutable_github_reader.subprocess.run")
    def test_exact_commit_and_path(self, run):
        run.return_value = response()
        self.assertEqual(
            read_accounting_immutable_text(REPO, PATH, SHA),
            '{"store_markets":["JP"]}',
        )
        args = run.call_args.args[0]
        self.assertEqual(args, [
            "gh", "api", "--method", "GET",
            f"repos/{REPO}/contents/{PATH}?ref={SHA}",
        ])
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertEqual(run.call_args.kwargs["timeout"], 45)

    @patch("scripts.accounting_immutable_github_reader.subprocess.run")
    def test_us_document_is_allowed_for_us_only(self, run):
        run.return_value = response(US_PATH, b"Form 3115 cash accrual")
        self.assertIn("Form 3115", read_accounting_immutable_text(REPO, US_PATH, SHA))
        run.assert_called_once()

    @patch("scripts.accounting_immutable_github_reader.subprocess.run")
    def test_wrong_repo_sha_path_and_country_fail_before_io(self, run):
        cases = [
            ("another/repo", PATH, SHA),
            (REPO, PATH, "main"),
            (REPO, PATH, "A" * 40),
            (REPO, PATH + "/../store-description.txt", SHA),
            (REPO, "products/jp-bookkeeping-desk/US_COMPLIANCE_SCOPE.md", SHA),
            (REPO, "products/unknown/market-scope.json", SHA),
            (REPO, "products/us-bookkeeping-desk/market-fit.json", SHA),
            (REPO, "products/us-bookkeeping-desk/store/approved-identity.json", SHA),
        ]
        for repo, path, sha in cases:
            with self.subTest(repo=repo, path=path, sha=sha):
                with self.assertRaises(AccountingImmutableReadHold):
                    read_accounting_immutable_text(repo, path, sha)
        run.assert_not_called()

    @patch("scripts.accounting_immutable_github_reader.subprocess.run")
    def test_api_error_is_secret_safe(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "token=SECRET")
        with self.assertRaisesRegex(
            AccountingImmutableReadHold, "^HOLD_ACCOUNTING_GITHUB_UNAVAILABLE$"
        ) as raised:
            read_accounting_immutable_text(REPO, PATH, SHA)
        self.assertNotIn("SECRET", str(raised.exception))

    @patch("scripts.accounting_immutable_github_reader.subprocess.run")
    def test_mismatched_blob_or_size_fails(self, run):
        for override in ({"sha": "f" * 40}, {"size": 999}):
            with self.subTest(override=override):
                run.return_value = response(**override)
                with self.assertRaisesRegex(
                    AccountingImmutableReadHold, "BLOB_MISMATCH"
                ):
                    read_accounting_immutable_text(REPO, PATH, SHA)

    @patch("scripts.accounting_immutable_github_reader.subprocess.run")
    def test_directory_wrong_path_and_oversize_fail(self, run):
        for override in (
            {"type": "dir"}, {"path": US_PATH},
            {"size": 65537}, {"size": True}, {"encoding": "utf-8"},
        ):
            with self.subTest(override=override):
                run.return_value = response(**override)
                with self.assertRaisesRegex(
                    AccountingImmutableReadHold, "CONTENT_INVALID"
                ):
                    read_accounting_immutable_text(REPO, PATH, SHA)

    @patch("scripts.accounting_immutable_github_reader.subprocess.run")
    def test_invalid_base64_or_utf8_fail(self, run):
        run.return_value = response(content="@@@")
        with self.assertRaisesRegex(AccountingImmutableReadHold, "CONTENT_INVALID"):
            read_accounting_immutable_text(REPO, PATH, SHA)
        run.return_value = response(raw=b"\xff")
        with self.assertRaisesRegex(AccountingImmutableReadHold, "CONTENT_INVALID"):
            read_accounting_immutable_text(REPO, PATH, SHA)

    @patch("scripts.accounting_immutable_github_reader.subprocess.run")
    def test_duplicate_json_metadata_key_fails(self, run):
        item = json.loads(response().stdout)
        run.return_value = subprocess.CompletedProcess(
            [], 0, '{"path":"fake","path":' + json.dumps(PATH) +
            ',' + ",".join(json.dumps(k) + ":" + json.dumps(v)
                           for k, v in item.items() if k != "path") + "}", "",
        )
        with self.assertRaisesRegex(AccountingImmutableReadHold, "DUPLICATE_KEY"):
            read_accounting_immutable_text(REPO, PATH, SHA)

    @patch("scripts.accounting_immutable_github_reader.subprocess.run")
    def test_unavailable_subprocess_and_large_response_fail(self, run):
        run.side_effect = OSError("secret token")
        with self.assertRaisesRegex(AccountingImmutableReadHold, "UNAVAILABLE"):
            read_accounting_immutable_text(REPO, PATH, SHA)
        run.side_effect = None
        run.return_value = subprocess.CompletedProcess([], 0, "x" * (256 * 1024 + 1), "")
        with self.assertRaisesRegex(AccountingImmutableReadHold, "RESPONSE_INVALID"):
            read_accounting_immutable_text(REPO, PATH, SHA)


    @patch("scripts.accounting_immutable_github_reader.subprocess.run")
    def test_authenticated_factory_wrapper_still_holds_without_actions(self, run):
        from scripts.accounting_immutable_github_reader import (
            check_accounting_e2e_with_authenticated_factory,
        )
        from scripts.accounting_e2e_gate import AccountingE2EHold

        job = {
            "slug": "jp-freelance-ledger", "product_type": "APP",
            "source_repository": REPO, "source_branch": "codex/reviewed",
            "source_sha": SHA, "request_id": "app-jp-freelance-ledger-aaaaaaaaaaaa",
            "identity_return_target":
                "products/jp-freelance-ledger/store/approved-identity.json",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
            "market_fit_gate": "MARKET_FIT_PASS",
            "market_fit_evidence_verified": True,
            "status": "PRE_IDENTITY_READY",
        }
        scope = json.dumps({
            "store_markets": ["JP"], "store_language": "ja-JP",
            "currency": "JPY", "country_profile": "Japan",
            "cross_market_sale": False,
        }).encode("utf-8")
        run.return_value = response(raw=scope)
        with self.assertRaisesRegex(AccountingE2EHold, "CI_NOT_VERIFIED"):
            check_accounting_e2e_with_authenticated_factory(
                job, phase="PRE_IDENTITY")
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
