"""Read and append receipts to a dedicated GitHub data-only branch."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path, PurePosixPath
import re
import urllib.error
import urllib.request

from uploader.receipts import ReceiptJournalError, validate_receipt


LEDGER_BRANCH_PREFIX = "store-uploader-ledger-"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class GitHubLedgerError(RuntimeError):
    pass


class GitHubLedger:
    def __init__(self, repository: str, token: str, *, api_url: str = "https://api.github.com"):
        if not REPOSITORY_RE.fullmatch(repository):
            raise GitHubLedgerError("repository must be owner/name")
        if not token:
            raise GitHubLedgerError("GitHub token is unavailable")
        self.repository = repository
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.base = f"{self.api_url}/repos/{repository}"

    def request(self, method: str, path: str, body: dict | None = None, *, missing_ok: bool = False) -> dict | None:
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            raise GitHubLedgerError(f"GitHub receipt ledger request failed ({exc.code})") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise GitHubLedgerError("GitHub receipt ledger request failed") from exc

    @staticmethod
    def branch_for_product(product_id: str) -> str:
        if not SAFE_COMPONENT_RE.fullmatch(product_id):
            raise GitHubLedgerError("invalid Product ID for receipt branch")
        return LEDGER_BRANCH_PREFIX + product_id

    def _head(self, product_id: str) -> tuple[str, str] | None:
        branch = self.branch_for_product(product_id)
        ref = self.request("GET", f"/git/ref/heads/{branch}", missing_ok=True)
        if ref is None:
            return None
        commit_sha = ref.get("object", {}).get("sha")
        if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-f]{40,64}", commit_sha):
            raise GitHubLedgerError("receipt branch returned an invalid ref")
        commit = self.request("GET", f"/git/commits/{commit_sha}")
        tree_sha = commit.get("tree", {}).get("sha")
        if not isinstance(tree_sha, str) or not re.fullmatch(r"[0-9a-f]{40,64}", tree_sha):
            raise GitHubLedgerError("receipt branch returned an invalid tree")
        return commit_sha, tree_sha

    @staticmethod
    def _receipt_path(receipt: dict) -> str:
        product_id = receipt.get("product_id")
        receipt_id = receipt.get("receipt_id")
        if not isinstance(product_id, str) or not SAFE_COMPONENT_RE.fullmatch(product_id):
            raise GitHubLedgerError("receipt has an invalid Product ID")
        if not isinstance(receipt_id, str) or not SAFE_COMPONENT_RE.fullmatch(receipt_id):
            raise GitHubLedgerError("receipt has an invalid receipt id")
        return f"receipts/{product_id}/{receipt_id}.json"

    def load_product(self, product_id: str, destination: Path) -> int:
        if not SAFE_COMPONENT_RE.fullmatch(product_id):
            raise GitHubLedgerError("invalid Product ID for ledger restore")
        branch = self.branch_for_product(product_id)
        head = self._head(product_id)
        if head is None:
            return 0
        _, tree_sha = head
        tree = self.request("GET", f"/git/trees/{tree_sha}?recursive=1")
        if tree.get("truncated") is True:
            raise GitHubLedgerError("receipt tree was truncated; refusing an incomplete duplicate check")
        prefix = f"receipts/{product_id}/"
        entries = [item for item in tree.get("tree", [])
                   if isinstance(item, dict) and item.get("type") == "blob"
                   and isinstance(item.get("path"), str) and item["path"].startswith(prefix)
                   and item["path"].endswith(".json")]
        count = 0
        for item in entries:
            relative = PurePosixPath(item["path"])
            if any(part in {".", ".."} for part in relative.parts) or len(relative.parts) != 3:
                raise GitHubLedgerError("receipt ledger contains an unsafe path")
            blob_sha = item.get("sha")
            if not isinstance(blob_sha, str) or not re.fullmatch(r"[0-9a-f]{40,64}", blob_sha):
                raise GitHubLedgerError("receipt ledger contains an invalid blob reference")
            blob = self.request("GET", f"/git/blobs/{blob_sha}")
            if blob.get("encoding") != "base64" or not isinstance(blob.get("content"), str):
                raise GitHubLedgerError("receipt blob has an unsupported encoding")
            try:
                raw = base64.b64decode("".join(blob["content"].split()), validate=True)
                value = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GitHubLedgerError("receipt blob is invalid JSON") from exc
            if not isinstance(value, dict) or value.get("product_id") != product_id or value.get("schema_version") != 1:
                raise GitHubLedgerError("receipt blob identity does not match its ledger path")
            try:
                validate_receipt(value)
            except ReceiptJournalError as exc:
                raise GitHubLedgerError("receipt blob failed audit schema validation") from exc
            out = destination / relative.parts[1] / relative.parts[2]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(raw)
            count += 1
        return count

    def append(self, receipt: dict) -> str:
        if not isinstance(receipt, dict) or not receipt.get("receipt_id"):
            raise GitHubLedgerError("execution receipt is incomplete")
        try:
            validate_receipt(receipt)
        except ReceiptJournalError as exc:
            raise GitHubLedgerError("execution receipt failed audit schema validation") from exc
        path = self._receipt_path(receipt)
        payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        content = payload.encode("utf-8")

        product_id = str(receipt["product_id"])
        branch = self.branch_for_product(product_id)
        existing_file = self.request("GET", f"/contents/{path}?ref={branch}", missing_ok=True)
        if existing_file is not None:
            try:
                existing_content = base64.b64decode(existing_file["content"]).decode("utf-8")
            except (KeyError, ValueError, UnicodeDecodeError) as exc:
                raise GitHubLedgerError("existing receipt could not be verified") from exc
            if existing_content == payload:
                return str(existing_file.get("sha", "already-present"))
            raise GitHubLedgerError("receipt id already exists with different content")

        head = self._head(product_id)
        entry = [{"path": path, "mode": "100644", "type": "blob", "content": payload}]
        tree_body = {"tree": entry}
        parents: list[str] = []
        if head is not None:
            parent_sha, base_tree = head
            tree_body["base_tree"] = base_tree
            parents = [parent_sha]
        tree = self.request("POST", "/git/trees", tree_body)
        new_commit = self.request("POST", "/git/commits", {
            "message": f"store: record upload receipt {receipt['receipt_id']}",
            "tree": tree["sha"], "parents": parents,
        })
        if head is None:
            self.request("POST", "/git/refs", {
                "ref": f"refs/heads/{branch}", "sha": new_commit["sha"],
            })
        else:
            self.request("PATCH", f"/git/refs/heads/{branch}", {
                "sha": new_commit["sha"], "force": False,
            })
        return str(new_commit["sha"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product")
    parser.add_argument("--destination", type=Path, default=Path(".uploader-run/durable-ledger/receipts"))
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN", "")
    ledger = GitHubLedger(args.repository, token, api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    if args.receipt:
        value = json.loads(args.receipt.read_text(encoding="utf-8"))
        print(json.dumps({"status": "PERSISTED", "commit": ledger.append(value)}, sort_keys=True))
        return 0
    if not args.product:
        raise GitHubLedgerError("--product is required when restoring the receipt ledger")
    restored = ledger.load_product(args.product, args.destination)
    print(json.dumps({"status": "RESTORED", "receipt_count": restored}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GitHubLedgerError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, sort_keys=True))
        raise SystemExit(2)
