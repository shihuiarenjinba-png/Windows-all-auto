"""Read-only batch4 archive/resume preflight; never authenticates, downloads or applies CAS.

This CLI does not trust persisted GitHub return evidence as physical Windows
proof. POST jobs are NO_WORK to prevent duplicate product creation/CAS; PRE jobs
can reuse only locally supplied exact immutable ZIP bytes. No network or writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


class ContractHold(ValueError):
    """A mismatch must fail closed rather than reuse another product's bytes."""


def _strict_json(data: bytes):
    def unique_pairs(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ContractHold("DUPLICATE_JSON_KEY")
            out[key] = value
        return out
    try:
        return json.loads(data, object_pairs_hook=unique_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ContractHold("NONFINITE_JSON")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractHold("INVALID_JSON") from exc


def _same(*values):
    return len(set(values)) == 1


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive_check(path: Path, job: dict, item: dict, record: dict) -> str:
    if not path.is_file() or path.is_symlink():
        return "HOLD_LOCAL_ARCHIVE_MISSING_OR_LINKED"
    try:
        if path.stat().st_size != record["archive_bytes"]:
            return "HOLD_ARCHIVE_BYTE_SIZE_MISMATCH"
        if _sha(path.read_bytes()) != record["archive_sha256"]:
            return "HOLD_ARCHIVE_SHA256_MISMATCH"
        with zipfile.ZipFile(path) as z:
            members = z.namelist()
            expected = {"registration-handoff.json", "exe-receipt.json",
                        job["slug"] + ".exe"}
            if len(members) != 3 or set(members) != expected:
                return "HOLD_ARCHIVE_MEMBERS_MISMATCH"
            if z.testzip() is not None:
                return "HOLD_ARCHIVE_CRC"
            handoff = _strict_json(z.read("registration-handoff.json"))
            exe_receipt = _strict_json(z.read("exe-receipt.json"))
            exe = z.read(job["slug"] + ".exe")
    except (OSError, zipfile.BadZipFile, RuntimeError, KeyError,
            ContractHold, ValueError):
        return "HOLD_ARCHIVE_INVALID"
    if not all((
        handoff.get("slug") == job["slug"],
        handoff.get("repo") == job["source_repository"],
        handoff.get("source_branch") == job["source_branch"],
        handoff.get("source_sha") == job["source_sha"],
        handoff.get("request_id") == job["request_id"],
        handoff.get("partner_center_registration_type") == job["registration_type"],
        handoff.get("partner_center_selection") == job["partner_center_selection"],
        handoff.get("product_type") == "APP",
        exe_receipt.get("slug") == job["slug"],
        exe_receipt.get("source_sha") == job["source_sha"],
        exe_receipt.get("source_branch") == job["source_branch"],
        exe_receipt.get("request_id") == job["request_id"],
        exe_receipt.get("source_repository") == job["source_repository"],
        exe_receipt.get("executable_sha256") == job["expected_exe_sha256"],
        exe_receipt.get("executable_bytes") == job["expected_exe_bytes"],
        _sha(exe) == job["expected_exe_sha256"],
        len(exe) == job["expected_exe_bytes"],
        record["exe_sha256"] == job["expected_exe_sha256"],
        item["exe_sha256"] == job["expected_exe_sha256"],
    )):
        return "HOLD_ARCHIVE_EMBEDDED_BINDING_MISMATCH"
    return "READ_ONLY_ARCHIVE_REUSE_VERIFIED__IDENTITY_RETURN_PENDING"


def build_plan(ledger: dict, archive_dir: Path | None = None) -> dict:
    batch = ledger["multi_product_partner_center_batch_4"]
    jobs = ledger["rotation_cohorts"]["app_jobs"]
    pipeline = {p["product"]: p for p in ledger["post_identity_pipeline"]["products"]}
    preserved = ledger["revision_review_reconciliation"][
        "artifact_byte_preservation_20261102"]
    extra = ledger["revision_review_reconciliation"]["artifact_byte_preservation_image_20261102"]
    records = {r["artifact_id"]: r for r in preserved["records"] + extra["records"]}
    if len(jobs) != 4 or len(batch["products"]) != 4:
        raise ContractHold("BATCH4_COUNT_MISMATCH")
    for field in ("request_id", "slug", "source_sha", "identity_return_target"):
        values = [j[field] for j in jobs]
        if len(set(values)) != 4:
            raise ContractHold("BATCH4_CROSS_PRODUCT_COLLISION_" + field.upper())
    if not (batch["cloud_preflight_discovered_count"] == 4 and
            batch["local_batch_discovered_count"] == 0 and
            batch["processed_count"] == 0 and
            batch["trigger_proof"] == "BATCH_SCHEDULE_TRIGGER_NOT_PROVEN"):
        raise ContractHold("BATCH4_PHYSICAL_PROOF_CONFLICT")
    results = []
    for idx, (job, item) in enumerate(zip(jobs, batch["products"]), 1):
        name = job["display_name"]
        p = pipeline[name]
        if not all((
            item["batch_index"] == idx,
            item["product"] == name,
            _same(job["slug"], item["slug"]),
            _same(job["request_id"], item["request_id"], p["request_id"]),
            _same(job["source_sha"], item["source_sha"], p["source_sha"]),
            _same(job["source_repository"], item["source_repository"], p["source_repository"]),
            _same(job["source_branch"], item["source_branch"], p["source_branch"]),
            _same(job["registration_type"], item["registration_type"], "MSIX_OR_PWA_APP"),
            _same(job["partner_center_selection"], item["partner_center_selection"], "MSIX or PWA app"),
            job["identity_return_target"] == p["identity_return_target"] ==
                "products/" + job["slug"] + "/store/approved-identity.json",
            job["factory_artifact_id"] == item["artifact_id"],
            job["factory_artifact_zip_sha256"] == item["artifact_zip_sha256"],
            job["factory_artifact_expiry_utc"] == item["artifact_expiry_utc"],
            job["expected_exe_sha256"] == item["exe_sha256"],
            not job["identity_cas_allowed"],
        )):
            raise ContractHold("BATCH4_JOB_BINDING_CONFLICT_" + str(idx))
        if job["status"] == "POST_IDENTITY_READY":
            if not (p["state"] == "POST_IDENTITY_READY" and
                    item["current_identity_state"] == "POST_IDENTITY_READY" and
                    job["identity_return_commit_sha"] ==
                    item["identity_return_commit_sha"] ==
                    p["identity_return_commit_sha"] and
                    isinstance(job["identity_return_commit_sha"], str) and
                    len(job["identity_return_commit_sha"]) == 40 and
                    item["local_operator_return_status"].startswith("GITHUB_RETURN_VERIFIED")):
                raise ContractHold("POST_IDENTITY_RETURN_CONFLICT_" + str(idx))
            action = "NO_WORK_POST_IDENTITY__NO_PRODUCT_CREATE_NO_CAS"
        elif job["status"] == "PRE_IDENTITY_READY":
            if not (p["identity_return_commit_sha"] is None and
                    item["identity_return_commit_sha"] is None and
                    item["current_identity_state"] == "PRE_IDENTITY_READY" and
                    item["local_operator_return_status"] == "LOCAL_OPERATOR_RETURN_PENDING"):
                raise ContractHold("PRE_IDENTITY_UNEXPECTED_RETURN_" + str(idx))
            record = records.get(item["artifact_id"])
            if record is None:
                action = "HOLD_ARCHIVE_NOT_PRESERVED__NO_AUTO_DOWNLOAD"
            elif not all((
                record["slug"] == job["slug"],
                record["archive_sha256"] == item["artifact_zip_sha256"],
                record["exe_sha256"] == job["expected_exe_sha256"],
                record["github_expiry_utc"] == item["artifact_expiry_utc"],
                record["library_readback_sha256_verified"] is True,
                record["package_kind"] == "PRE_IDENTITY_UNSIGNED_EXE_NOT_MSIX",
            )):
                action = "HOLD_ARCHIVE_CUSTODY_CONFLICT"
            elif archive_dir is None:
                action = "HOLD_LOCAL_ARCHIVE_BYTES_NOT_MOUNTED"
            else:
                action = _archive_check(archive_dir /
                                        ("artifact-" + str(item["artifact_id"]) + ".zip"),
                                        job, item, record)
        else:
            raise ContractHold("UNSUPPORTED_BATCH4_STATE_" + str(idx))
        results.append({"batch_index": idx, "product": name,
                        "request_id": job["request_id"], "source_sha": job["source_sha"],
                        "identity_return_target": job["identity_return_target"],
                        "artifact_id": item["artifact_id"], "action": action})
    app_post = sum(j["status"] == "POST_IDENTITY_READY" for j in jobs)
    all_post = sum(p["state"] == "POST_IDENTITY_READY"
                   for p in ledger["post_identity_pipeline"]["products"])
    if app_post != 2 or all_post != 3:
        raise ContractHold("POST_IDENTITY_COUNT_SCOPE_CONFLICT")
    return {"mode": "READ_ONLY_NO_NETWORK_NO_CAS_NO_STORE",
            "app_post_identity": app_post, "all_lane_post_identity": all_post,
            "cloud_discovered": 4, "physical_local_discovered": 0,
            "physical_local_processed": 0, "scheduled_trigger_proven": False,
            "physical_windows_pass": False, "real_msix_pass": False,
            "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=Path(__file__).resolve().parents[1] /
                        "ops" / "active_e2e_handoff.json")
    parser.add_argument("--archive-dir", type=Path, default=None,
                        help="Existing exact ZIPs only; never downloads")
    args = parser.parse_args()
    try:
        ledger = _strict_json(args.ledger.read_bytes())
        result = build_plan(ledger, args.archive_dir)
    except (ContractHold, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "HOLD_CONTRACT", "error": str(exc)}))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
