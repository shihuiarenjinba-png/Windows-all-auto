"""Fail-closed sequencing for the six Group C Microsoft Store products."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "group-c-store-products/1"
ORDER = (
    "data-contract-auditor",
    "web-evidence-archiver",
    "excel-csv-privacy-cleaner",
    "image-privacy-cleaner",
    "ai-upload-guard",
    "pdf-privacy",
)
COMPLETE_STATE = "READY_FOR_CERTIFICATION_REVIEW"
STORE_ID_PATTERN = re.compile(r"^9[A-Z0-9]{11}$")


class GroupCRolloutError(ValueError):
    """Raised when rollout metadata could allow an unsafe or ambiguous action."""


def load_registry(path: str | Path) -> dict[str, Any]:
    registry = json.loads(Path(path).read_text(encoding="utf-8"))
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise GroupCRolloutError("GROUP_C_REGISTRY_SCHEMA_MISMATCH")
    if tuple(registry.get("execution_order", ())) != ORDER:
        raise GroupCRolloutError("GROUP_C_EXECUTION_ORDER_MISMATCH")
    products = registry.get("products")
    if not isinstance(products, dict) or tuple(products) != ORDER:
        raise GroupCRolloutError("GROUP_C_PRODUCT_SET_OR_ORDER_MISMATCH")
    repositories: set[str] = set()
    store_ids: set[str] = set()
    for product_id in ORDER:
        item = products[product_id]
        if item.get("submission_route") != "msix_pwa_app":
            raise GroupCRolloutError("GROUP_C_SUBMISSION_ROUTE_MISMATCH")
        repository = item.get("repository_full_name")
        if not isinstance(repository, str) or repository in repositories:
            raise GroupCRolloutError("GROUP_C_REPOSITORY_INVALID_OR_DUPLICATE")
        repositories.add(repository)
        store_id = item.get("store_id")
        if store_id is not None:
            if not isinstance(store_id, str) or not STORE_ID_PATTERN.fullmatch(store_id.upper()):
                raise GroupCRolloutError("GROUP_C_STORE_ID_INVALID")
            normalized = store_id.upper()
            if normalized in store_ids:
                raise GroupCRolloutError("GROUP_C_STORE_ID_DUPLICATE")
            store_ids.add(normalized)
    return registry


def load_receipt(root: str | Path, product: dict[str, Any]) -> dict[str, Any] | None:
    relative = product.get("receipt")
    if relative is None:
        return None
    path = Path(root) / relative
    if not path.is_file():
        raise GroupCRolloutError("GROUP_C_RECEIPT_MISSING")
    return json.loads(path.read_text(encoding="utf-8"))


def product_state(root: str | Path, product: dict[str, Any]) -> str:
    receipt = load_receipt(root, product)
    if receipt is None:
        return "READY_FOR_WINDOWS_REAL_DEVICE_QA"
    receipt_product = receipt.get("product", {})
    for key in ("name", "store_id", "draft_id", "submission_route"):
        expected = product.get(key)
        if expected is not None and receipt_product.get(key) != expected:
            raise GroupCRolloutError(f"GROUP_C_RECEIPT_{key.upper()}_MISMATCH")
    state = receipt.get("current_state")
    if not isinstance(state, str) or not state:
        raise GroupCRolloutError("GROUP_C_RECEIPT_STATE_MISSING")
    return state


def rollout_status(root: str | Path, registry: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    previous_complete = True
    for product_id in ORDER:
        product = registry["products"][product_id]
        observed = product_state(root, product)
        if previous_complete:
            effective = observed
        else:
            effective = "WAITING_FOR_PREVIOUS_PRODUCT"
        rows.append(
            {
                "product_id": product_id,
                "name": product["name"],
                "observed_state": observed,
                "effective_state": effective,
            }
        )
        previous_complete = previous_complete and observed == COMPLETE_STATE
    return rows


def next_product(root: str | Path, registry: dict[str, Any]) -> dict[str, str] | None:
    for row in rollout_status(root, registry):
        if row["effective_state"] != "WAITING_FOR_PREVIOUS_PRODUCT":
            if row["observed_state"] != COMPLETE_STATE:
                return row
    return None
