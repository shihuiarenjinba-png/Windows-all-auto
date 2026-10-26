"""Durable offline queue ledger; does not execute Partner Center writes.

UNKNOWN cannot be resumed automatically. The owner must reconcile in Partner Center.
Pre-operator preflight states may be refreshed because no remote side effect has occurred yet.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


PRE_OPERATOR_STATES = {"READY_FOR_WINDOWS_QA", "HOLD", "BLOCKED"}
REMOTE_GUARD_STATES = {"PENDING_OPERATOR", "UNKNOWN"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(product: dict[str, Any], preflight_row: dict[str, Any]) -> str:
    identity = product.get("approved_identity") or {}
    payload = {
        "product_id": product.get("id"),
        "store_id": identity.get("store_id"),
        "source_sha": product.get("source_sha"),
        "package_sha256": preflight_row.get("package_sha256"),
        "version": identity.get("version"),
        "submission_kind": product.get("submission_kind"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class QueueLedger:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS jobs(
            job_key TEXT PRIMARY KEY, product_id TEXT NOT NULL,
            store_id TEXT, fingerprint TEXT NOT NULL, status TEXT NOT NULL,
            reason TEXT NOT NULL, created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL)"""
        )
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS events(
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, job_key TEXT NOT NULL,
            old_status TEXT, new_status TEXT NOT NULL, reason TEXT NOT NULL,
            timestamp_utc TEXT NOT NULL)"""
        )

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def add_product(self, product: dict[str, Any], preflight_row: dict[str, Any]) -> dict[str, str]:
        key = fingerprint(product, preflight_row)
        product_id = str(product["id"])
        identity = product.get("approved_identity") or {}
        store_id = str(identity.get("store_id") or "")
        status = str(preflight_row["status"])
        if status not in PRE_OPERATOR_STATES:
            raise ValueError("Illegal preflight status")
        reason = ",".join(preflight_row.get("findings") or [])

        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.db.execute(
                "SELECT status,reason FROM jobs WHERE job_key=?", (key,)
            ).fetchone()
            if old:
                old_status, old_reason = str(old[0]), str(old[1])
                # Before any operator/remote stage, the latest preflight is authoritative.
                # This prevents a stale READY from surviving a newly discovered HOLD/BLOCK
                # and also allows a repaired HOLD/BLOCK to become READY without a new job.
                if old_status in PRE_OPERATOR_STATES:
                    if old_status != status or old_reason != reason:
                        now = _now()
                        self.db.execute(
                            "UPDATE jobs SET status=?,reason=?,updated_utc=? WHERE job_key=?",
                            (status, reason, now, key),
                        )
                        event_reason = "preflight refreshed" + (f": {reason}" if reason else "")
                        self.db.execute(
                            "INSERT INTO events(job_key,old_status,new_status,reason,timestamp_utc) "
                            "VALUES(?,?,?,?,?)",
                            (key, old_status, status, event_reason, now),
                        )
                    self.db.execute("COMMIT")
                    return {"job_key": key, "status": status, "reason": reason}
                # Once operator/remote handling starts, re-enqueue is read-only.
                self.db.execute("COMMIT")
                return {"job_key": key, "status": old_status, "reason": old_reason}

            if store_id:
                # A Store Product ID mapped to a different local product is always a
                # dangerous identity collision, regardless of the other job's state.
                identity_collision = self.db.execute(
                    "SELECT job_key FROM jobs WHERE store_id=? AND product_id<>? LIMIT 1",
                    (store_id, product_id),
                ).fetchone()
                if identity_collision:
                    status = "BLOCKED"
                    reason = "STORE_ID_PRODUCT_COLLISION"
                else:
                    # A different fingerprint for the same product may only coexist when
                    # all prior candidates are still HOLD/BLOCKED (no remote side effect).
                    conflict = self.db.execute(
                        "SELECT job_key FROM jobs WHERE store_id=? AND product_id=? "
                        "AND status IN ('READY_FOR_WINDOWS_QA','PENDING_OPERATOR','UNKNOWN') LIMIT 1",
                        (store_id, product_id),
                    ).fetchone()
                    if conflict:
                        status = "HOLD"
                        reason = "PRIOR_STORE_OUTCOME_UNCONFIRMED"

            now = _now()
            self.db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
                (key, product_id, store_id, key, status, reason, now, now),
            )
            self.db.execute(
                "INSERT INTO events(job_key,old_status,new_status,reason,timestamp_utc) VALUES(?,NULL,?,?,?)",
                (key, status, reason, now),
            )
            self.db.execute("COMMIT")
            return {"job_key": key, "status": status, "reason": reason}
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def require_operator(self, job_key: str) -> None:
        """Advance ONLY to human verification; this does not upload anything."""
        self._transition(job_key, "READY_FOR_WINDOWS_QA", "PENDING_OPERATOR", "human Windows verification required")

    def record_ambiguous_result(self, job_key: str) -> None:
        """Called only after the operator determines an attempted remote write was ambiguous."""
        self._transition(job_key, "PENDING_OPERATOR", "UNKNOWN", "remote outcome must be reconciled manually")

    def _transition(self, key: str, expected: str, target: str, reason: str) -> None:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cur = self.db.execute(
                "UPDATE jobs SET status=?,reason=?,updated_utc=? WHERE job_key=? AND status=?",
                (target, reason, _now(), key, expected),
            )
            if cur.rowcount != 1:
                raise ValueError("Illegal, stale, or duplicate state transition")
            self.db.execute(
                "INSERT INTO events(job_key,old_status,new_status,reason,timestamp_utc) VALUES(?,?,?,?,?)",
                (key, expected, target, reason, _now()),
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def rows(self) -> list[dict[str, Any]]:
        cur = self.db.execute(
            "SELECT job_key,product_id,store_id,status,reason,updated_utc FROM jobs ORDER BY created_utc,job_key"
        )
        return [dict(zip(("job_key","product_id","store_id","status","reason","updated_utc"), row))
                for row in cur.fetchall()]
