"""Append-only, portable receipts for Store package upload attempts.

The receipt journal is intentionally separate from the SQLite retry cache and
GitHub Actions artifacts. A caller may point it at a durable checked-out store.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4


CONFIRMED_UI_STATES = {"UI_VALIDATED_SHA_UNOBSERVABLE"}


class ReceiptJournalError(RuntimeError):
    pass


def validate_receipt(value: Any) -> dict[str, Any]:
    required = ("schema_version", "product_id", "submission_id", "package_file_name", "sha256",
                "partner_center_sha256", "executed_at", "result", "partner_center_confirmation")
    if not isinstance(value, dict) or any(key not in value for key in required):
        raise ReceiptJournalError("receipt is missing required audit fields")
    component = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    if value.get("schema_version") != 1:
        raise ReceiptJournalError("receipt schema is unsupported")
    if any(not isinstance(value.get(key), str) or not component.fullmatch(value[key])
           for key in ("product_id", "submission_id")):
        raise ReceiptJournalError("receipt target identifiers are invalid")
    filename = value.get("package_file_name")
    if (not isinstance(filename, str) or not filename or filename in {".", ".."}
            or "/" in filename or "\\" in filename or "\x00" in filename
            or Path(filename).name != filename or not filename.lower().endswith(".msix")):
        raise ReceiptJournalError("receipt package filename is invalid")
    digest = value.get("sha256")
    if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)):
        raise ReceiptJournalError("receipt SHA-256 is invalid")
    if value.get("partner_center_sha256") is not None:
        raise ReceiptJournalError("Partner Center binary SHA must remain unclaimed")
    try:
        executed = value.get("executed_at")
        parsed = datetime.fromisoformat(executed.replace("Z", "+00:00")) if isinstance(executed, str) else None
    except ValueError as exc:
        raise ReceiptJournalError("receipt execution time is invalid") from exc
    if parsed is None or parsed.tzinfo is None:
        raise ReceiptJournalError("receipt execution time must include a timezone")
    allowed_results = {"SUCCEEDED", "SUCCEEDED_RECONCILED", "DUPLICATE", "DUPLICATE_CONFIRMED",
                       "DRY_RUN", "DRY_RUN_ALREADY_DONE", "FAILED", "UNKNOWN", "RECONCILE_REQUIRED",
                       "RETRY_LIMIT"}
    if value.get("result") not in allowed_results:
        raise ReceiptJournalError("receipt result is unsupported")
    if value.get("partner_center_confirmation") not in {
            "UI_VALIDATED_SHA_UNOBSERVABLE", "NOT_ATTEMPTED", "NOT_CONFIRMED", "UNKNOWN"}:
        raise ReceiptJournalError("receipt Partner Center confirmation state is invalid")
    if value.get("result") in {"SUCCEEDED", "SUCCEEDED_RECONCILED"} and digest is None:
        raise ReceiptJournalError("successful receipt requires the submitted SHA-256")
    return value


def receipt_matches_job(receipt: Any, job: Any) -> bool:
    try:
        validate_receipt(receipt)
    except ReceiptJournalError:
        return False
    return (
        receipt.get("schema_version") == 1
        and receipt.get("product_id") == job.product_id
        and receipt.get("submission_id") == job.submission_id
        and receipt.get("package_file_name") == job.file_name
        and str(receipt.get("sha256", "")).lower() == job.sha256.lower()
        and receipt.get("result") == "SUCCEEDED"
        and receipt.get("partner_center_confirmation") in CONFIRMED_UI_STATES
        and receipt.get("partner_center_sha256") is None
    )


class ReceiptJournal:
    """Durable receipt reader/writer; only exact successful receipts prove reuse."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def records(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        values: list[dict[str, Any]] = []
        for path in sorted(self.root.rglob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ReceiptJournalError("durable receipt journal contains an unreadable record") from exc
            values.append(validate_receipt(value))
        return values

    def classify(self, job: Any) -> str:
        successful = [r for r in self.records()
                      if r.get("product_id") == job.product_id
                      and r.get("submission_id") == job.submission_id
                      and r.get("result") == "SUCCEEDED"
                      and r.get("partner_center_confirmation") in CONFIRMED_UI_STATES]
        for receipt in successful:
            if receipt_matches_job(receipt, job):
                return "EXACT_SUCCESS"
        for receipt in successful:
            same_name = receipt.get("package_file_name") == job.file_name
            same_hash = str(receipt.get("sha256", "")).lower() == job.sha256.lower()
            if same_name or same_hash:
                return "IDENTITY_CONFLICT"
        return "NO_MATCH"

    def append(self, receipt: dict[str, Any]) -> Path:
        validate_receipt(receipt)
        product_id = str(receipt["product_id"])
        receipt_id = str(receipt.get("receipt_id") or uuid4().hex)
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", receipt_id):
            raise ValueError("invalid receipt id")
        value = {"schema_version": 1, **receipt, "receipt_id": receipt_id}
        path = self.root / product_id / f"{receipt_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
        return path


def new_execution_receipt(*, product_id: str, submission_id: str,
                          package_file_name: str, sha256: str | None,
                          result: str, partner_center_confirmation: str,
                          run_id: str | None = None, run_attempt: str | None = None,
                          details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "product_id": product_id,
        "submission_id": submission_id,
        "package_file_name": package_file_name,
        "sha256": sha256,
        "partner_center_sha256": None,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "result": result,
        "partner_center_confirmation": partner_center_confirmation,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "details": details or {},
    }
