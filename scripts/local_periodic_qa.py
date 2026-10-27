"""Bounded GitHub backlog -> local inbox -> Windows-checker cycle.

This worker is local-only.  It never installs, signs, archives, submits, or
claims E2E success.  A non-blocking process lock prevents overlapping 15-minute
Task Scheduler runs; the checker ledger handles exact-package idempotency.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from scripts.local_checker_queue import atomic_json, check_local_queue
from scripts.local_handoff_pull import pull


class LocalRunLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None

    def acquire(self) -> bool:
        if self.path.is_symlink():
            raise ValueError("LOCAL_QA_HOLD: linked lock file")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            return False
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


def run_cycle(inbox: Path, checker: Path, reports: Path, state_root: Path,
              puller=pull, checker_runner=check_local_queue) -> dict:
    if state_root.is_symlink():
        return {"status": "HOLD", "reason": "LOCAL_QA_STATE_ROOT_UNSAFE",
                "hold_class": "INTEGRATION_FIX", "e2e_pass": False,
                "submitted_to_store": 0}
    lock = LocalRunLock(state_root / "periodic-qa.lock")
    if not lock.acquire():
        return {"status": "HOLD", "reason": "LOCAL_QA_WORKER_ALREADY_RUNNING",
                "hold_class": "QUEUE_CAPACITY", "e2e_pass": False,
                "submitted_to_store": 0}
    try:
        pulled = puller(inbox)
        checked = checker_runner(inbox, checker, reports,
                                 state_root / "local-qa-ledger.json")
        capacity_hold = pulled.get("status") == "HOLD_LOCAL_CAPACITY"
        result = {
            "schema_version": 1,
            "status": "HOLD_LOCAL_CAPACITY" if capacity_hold else "HOLD",
            "reason": (pulled.get("reason") if capacity_hold else
                       "CHECKER_COMPLETE_GUI_INSTALL_RECEIPT_PENDING"),
            "hold_class": "QUEUE_CAPACITY" if capacity_hold else "HUMAN_APPROVAL",
            "pull": pulled, "checker": checked,
            "archive_status": "WAITING_CHECKER_AND_GUI_INSTALL_RECEIPT",
            "e2e_pass": False, "submitted_to_store": 0,
        }
        state_root.mkdir(parents=True, exist_ok=True)
        atomic_json(state_root / "last-cycle.json", result)
        return result
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        result = {"schema_version": 1, "status": "HOLD",
                  "reason": "LOCAL_QA_CYCLE_UNAVAILABLE",
                  "hold_class": "CI_INFRA" if isinstance(exc, RuntimeError) else "INTEGRATION_FIX",
                  "detail": str(exc)[:180], "e2e_pass": False,
                  "submitted_to_store": 0}
        if not state_root.is_symlink():
            atomic_json(state_root / "last-cycle.json", result)
        return result
    finally:
        lock.release()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inbox", type=Path, required=True)
    parser.add_argument("--checker", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_cycle(args.inbox, args.checker, args.reports, args.state_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"HOLD", "HOLD_LOCAL_CAPACITY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
