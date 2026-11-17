from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--exe-sha256", required=True)
    p.add_argument("--event-id", action="append", required=True, type=int)
    p.add_argument("--policy-name", required=True)
    p.add_argument("--policy-guid", required=True)
    p.add_argument("--raw-evidence", type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()

    if a.output.exists() or a.output.is_symlink():
        raise SystemExit("refusing to overwrite existing Code Integrity evidence")

    exe_sha = a.exe_sha256.strip().lower()
    if len(exe_sha) != 64 or any(ch not in "0123456789abcdef" for ch in exe_sha):
        raise SystemExit("exe-sha256 must be exactly 64 hexadecimal characters")

    event_ids = sorted(set(a.event_id))
    if not set(event_ids).intersection({3033, 3077}):
        raise SystemExit("at least one block-class event id 3033/3077 is required")
    if not a.policy_name.strip():
        raise SystemExit("policy-name is required")
    if not a.policy_guid.strip():
        raise SystemExit("policy-guid is required")

    evidence = {
        "schema_version": "code-integrity-block-evidence/1",
        "status": "APPLICATION_CONTROL_BLOCKED",
        "exe_sha256": exe_sha,
        "event_ids": event_ids,
        "blocking_event_ids": sorted(set(event_ids).intersection({3033, 3077})),
        "supplemental_event_ids": sorted(set(event_ids).difference({3033, 3077})),
        "policy_name": a.policy_name.strip(),
        "policy_guid": a.policy_guid.strip(),
        "launch_attempts": 1,
        "process_started": False,
        "security_bypass_used": False,
        "security_policy_modified": False,
        "certificate_store_modified": False,
        "alternate_bypass_used": False,
        "msix_installed": False,
        "partner_center_write_performed": False,
        "package_uploaded": False,
        "certification_submitted": False,
        "published": False,
    }
    if a.raw_evidence is not None:
        if not a.raw_evidence.is_file():
            raise SystemExit("raw-evidence path does not exist")
        evidence["raw_evidence_path"] = str(a.raw_evidence)
        evidence["raw_evidence_sha256"] = sha256_file(a.raw_evidence)

    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "output": str(a.output),
                "blocking_event_ids": evidence["blocking_event_ids"],
                "original_raw_evidence_preserved": True,
                "store_write_performed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
