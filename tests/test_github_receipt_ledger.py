from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from uploader.github_receipt_ledger import GitHubLedger, GitHubLedgerError
from uploader.receipts import new_execution_receipt


class FakeGitHubLedger(GitHubLedger):
    def __init__(self, *, head=None, tree=None):
        super().__init__("owner/repo", "not-a-real-token")
        self.head = head
        self.tree = tree
        self.calls = []

    def request(self, method, path, body=None, *, missing_ok=False):
        self.calls.append((method, path, body))
        if method == "GET" and path.startswith("/contents/"):
            return None
        if method == "GET" and path == "/git/ref/heads/store-uploader-ledger":
            return None if self.head is None else {"object": {"sha": self.head}}
        if method == "GET" and path == f"/git/commits/{self.head}":
            return {"tree": {"sha": self.tree}}
        if method == "GET" and path.startswith("/git/trees/"):
            return {"truncated": False, "tree": []}
        if method == "POST" and path == "/git/trees":
            return {"sha": "a" * 40}
        if method == "POST" and path == "/git/commits":
            self.commit_body = body
            return {"sha": "b" * 40}
        if method == "POST" and path == "/git/refs":
            self.created_ref = body
            return {"ref": body["ref"]}
        if method == "PATCH" and path == "/git/refs/heads/store-uploader-ledger":
            self.updated_ref = body
            return {"ref": path}
        raise AssertionError((method, path, body))


class GitHubReceiptLedgerTests(unittest.TestCase):
    def receipt(self):
        value = new_execution_receipt(
            product_id="9PDL4ZWSB45P", submission_id="1152921505702212222",
            package_file_name="DataContractAuditor.msix", sha256="a" * 64,
            result="SUCCEEDED", partner_center_confirmation="UI_VALIDATED_SHA_UNOBSERVABLE",
        )
        value["receipt_id"] = "receipt-123"
        return value

    def test_first_receipt_creates_orphan_data_branch(self):
        ledger = FakeGitHubLedger()
        ledger.append(self.receipt())
        self.assertEqual(ledger.created_ref["ref"], "refs/heads/store-uploader-ledger")
        self.assertEqual(ledger.commit_body["parents"], [])
        body = next(call[2] for call in ledger.calls if call[0] == "POST" and call[1] == "/git/trees")
        self.assertTrue(body["tree"][0]["path"].startswith("receipts/9PDL4ZWSB45P/"))

    def test_existing_branch_receipt_append_is_non_force_update(self):
        ledger = FakeGitHubLedger(head="c" * 40, tree="d" * 40)
        ledger.append(self.receipt())
        self.assertEqual(ledger.commit_body["parents"], ["c" * 40])
        self.assertEqual(ledger.updated_ref["force"], False)
        self.assertEqual(ledger.updated_ref["sha"], "b" * 40)

    def test_truncated_durable_tree_fails_closed(self):
        class Truncated(FakeGitHubLedger):
            def request(self, method, path, body=None, *, missing_ok=False):
                if method == "GET" and path.startswith("/git/trees/"):
                    return {"truncated": True, "tree": []}
                return super().request(method, path, body, missing_ok=missing_ok)
        ledger = Truncated(head="c" * 40, tree="d" * 40)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(GitHubLedgerError, "truncated"):
                ledger.load_product("9PDL4ZWSB45P", Path(tmp))


if __name__ == "__main__":
    unittest.main()
