from __future__ import annotations
import argparse, json, os, re, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4
from uploader.core import JobLedger, UploadError, process_job, validate_config, verify_file
from uploader.live_gates import package_write_hold_reason
from uploader.partner_center_browser import PartnerCenterCDPConnection
from uploader.receipts import ReceiptJournal, new_execution_receipt

CONFIG_ROOT = Path(__file__).parent / "config"

def resolve_job_config(*, config_path=None, product_key=None):
    if bool(config_path) == bool(product_key):
        raise UploadError("INVALID_JOB", "Provide exactly one of --config or --product")
    if product_key is not None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", product_key):
            raise UploadError("INVALID_JOB", "Product key must be a lowercase config slug")
        config_path = CONFIG_ROOT / f"{product_key}.job.json"
    path = Path(config_path).resolve()
    if config_path is not None and product_key is not None and CONFIG_ROOT.resolve() not in path.parents:
        raise UploadError("INVALID_JOB", "Product config is outside uploader/config")
    return path

def github_download(repository, ref, path, token, target, max_bytes=4_000_000_000):
    encoded_path = quote(path, safe="/")
    encoded_ref = quote(ref, safe="")
    url = f"https://api.github.com/repos/{repository}/contents/{encoded_path}?ref={encoded_ref}"
    headers = {"Accept":"application/vnd.github.raw+json", "X-GitHub-Api-Version":"2022-11-28"}
    if token: headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
            if response.status != 200: raise UploadError("DOWNLOAD_FAILED", f"GitHub HTTP {response.status}")
            target.parent.mkdir(parents=True, exist_ok=True)
            size = 0
            too_large = False
            with target.open("xb") as stream:
                while chunk := response.read(1024*1024):
                    size += len(chunk)
                    if size > max_bytes:
                        too_large = True
                        break
                    stream.write(chunk)
            if too_large:
                target.unlink(missing_ok=True)
                raise UploadError("FILE_SIZE_LIMIT", "GitHub artifact exceeds configured max_bytes")
    except urllib.error.HTTPError as exc:
        code = {401:"AUTH_FAILED",403:"PERMISSION_DENIED",404:"FILE_NOT_FOUND"}.get(exc.code,"DOWNLOAD_FAILED")
        raise UploadError(code, f"GitHub download HTTP {exc.code}") from exc
    except TimeoutError as exc:
        target.unlink(missing_ok=True)
        raise UploadError("TIMEOUT", "GitHub download timed out") from exc
    except urllib.error.URLError as exc:
        target.unlink(missing_ok=True)
        raise UploadError("DOWNLOAD_FAILED", "GitHub package download failed") from exc

def main():
    parser = argparse.ArgumentParser(description="Validate or upload one exact MSIX to an existing Microsoft Store Draft.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path, help="Exact product job JSON")
    source.add_argument("--product", help="Registered product key under uploader/config")
    parser.add_argument("--package", type=Path, help="Use an already-downloaded local MSIX instead of downloading from GitHub")
    parser.add_argument("--workdir", type=Path, default=Path(".uploader-run"))
    parser.add_argument("--receipt-ledger", type=Path)
    parser.add_argument("--execute", action="store_true", help="Upload to the configured existing Draft, Save Packages, and verify after reload")
    args = parser.parse_args()
    config={}; package=None; job=None; journal=None; outcome="FAILED"; detail={}; code=""; browser_connection=None
    try:
        config_file=resolve_job_config(config_path=args.config, product_key=args.product)
        config=validate_config(json.loads(config_file.read_text(encoding="utf-8")))
        args.workdir.mkdir(parents=True, exist_ok=True)
        journal=ReceiptJournal(args.receipt_ledger or (args.workdir/"durable-ledger"/"receipts"))
        if args.execute and config.get("upload_approved") is not True:
            raise UploadError("UPLOAD_NOT_APPROVED", "This product job is not approved for a live package write")
        if args.execute and config.get("upload_scope") != "ONE_EXACT_MSIX_TO_EXISTING_DRAFT_PACKAGES_ONLY":
            raise UploadError("UPLOAD_SCOPE_NOT_APPROVED", "Live execution is restricted to one exact MSIX package upload/Save in an existing Draft")
        if args.execute and config.get("certification_submission_authorized") is not False:
            raise UploadError("CERTIFICATION_SCOPE_FORBIDDEN", "This uploader never submits for Certification")
        if args.execute and config.get("publish_authorized") is not False:
            raise UploadError("PUBLISH_SCOPE_FORBIDDEN", "This uploader never publishes")
        if args.execute:
            live_hold = package_write_hold_reason(config)
            if live_hold:
                raise UploadError(live_hold, "Shared Store live-write QA/approval gate did not pass")
        if args.execute and not re.fullmatch(r"[0-9a-fA-F]{64}", str(config.get("expected_sha256", ""))):
            raise UploadError("EXPECTED_SHA_REQUIRED", "Live upload requires a frozen 64-character SHA-256")
        if args.execute and not os.environ.get("PARTNER_CENTER_CDP_URL"):
            raise UploadError("BROWSER_SESSION_UNAVAILABLE", "Set the authenticated remote browser CDP secret before live execution")
        expected=config.get("expected_sha256"); expected=None if not expected or expected.startswith("REPLACE_") else expected
        if args.package is not None:
            try:
                package = args.package.expanduser().resolve(strict=True)
            except OSError as exc:
                raise UploadError("FILE_NOT_FOUND", "The supplied local MSIX path does not exist") from exc
            if not package.is_file():
                raise UploadError("FILE_NOT_FOUND", "The supplied local package path is not a file")
            configured_name = Path(config["path"]).name
            if package.name.casefold() != configured_name.casefold():
                raise UploadError("PACKAGE_FILENAME_MISMATCH",
                                  f"Expected the exact configured filename: {configured_name}")
        else:
            package=args.workdir/Path(config["path"]).name
            github_download(config["repository"],config["ref"],config["path"],os.environ.get("GH_READ_TOKEN"),package,
                            max_bytes=int(config.get("max_bytes",4_000_000_000)))
        job=verify_file(config,package,expected_sha256=expected,
                        max_bytes=int(config.get("max_bytes",4_000_000_000)))
        with JobLedger(args.workdir/"ledger.sqlite3") as ledger:
            if args.execute:
                def browser_preflight(job, package_path, *, recovery_required=False):
                    nonlocal browser_connection
                    browser_connection = PartnerCenterCDPConnection(os.environ["PARTNER_CENTER_CDP_URL"], config)
                    port = browser_connection.__enter__()
                    try:
                        preflight = port.preflight_target(job, recovery_required=recovery_required)
                    except Exception:
                        browser_connection.__exit__(None, None, None)
                        browser_connection = None
                        raise
                    return {
                        "preflight": preflight,
                        "live_adapter": lambda current_job, current_path: port.upload_save_and_reconcile(current_job, current_path),
                        "reconcile_adapter": lambda current_job, current_path, previous: port.reconcile_ambiguous_upload(current_job, current_path, previous),
                    }
                result=process_job(config,package,ledger,expected_sha256=expected,dry_run=False,
                                   live_preflight_adapter=browser_preflight,
                                   live_adapter=lambda job,path: None,
                                   receipt_journal=journal)
            else:
                result=process_job(config,package,ledger,expected_sha256=expected,dry_run=True,receipt_journal=journal)
        outcome=str(result.get("status","UNKNOWN")); detail=result
        confirmation="UI_VALIDATED_SHA_UNOBSERVABLE" if outcome in {"SUCCEEDED","SUCCEEDED_RECONCILED"} else ("UNKNOWN" if outcome=="RECONCILE_REQUIRED" else "NOT_ATTEMPTED")
        _save_run_receipt(args.workdir,config,job,outcome,confirmation,detail,journal)
        print(json.dumps(result,sort_keys=True)); return 0 if outcome not in {"RECONCILE_REQUIRED","FAILED"} else 2
    except UploadError as exc:
        code=exc.code; detail={"error_code":exc.code,"message":str(exc)}
        if config:
            args.workdir.mkdir(parents=True, exist_ok=True)
            if journal is None:
                journal=ReceiptJournal(args.receipt_ledger or (args.workdir/"durable-ledger"/"receipts"))
            _save_run_receipt(args.workdir,config,job,"FAILED",_confirmation_for_error(exc.code),detail,journal)
        print(json.dumps({"status":"FAILED","error_code":exc.code,"message":str(exc)},sort_keys=True)); return 2
    finally:
        if browser_connection is not None:
            browser_connection.__exit__(None, None, None)

def _confirmation_for_error(code: str) -> str:
    if code in {"UPLOAD_RESULT_UNKNOWN","UPLOAD_RESULT_UNCONFIRMED","RECONCILE_REQUIRED","RECONCILE_UNRESOLVED"}:
        return "UNKNOWN"
    return "NOT_CONFIRMED"

def _save_run_receipt(workdir: Path, config: dict, job, outcome: str, confirmation: str,
                      details: dict, journal: ReceiptJournal | None) -> None:
    receipt=new_execution_receipt(
        product_id=str(config.get("product_id","")),
        submission_id=str(config.get("submission_id","")),
        package_file_name=job.file_name if job else Path(str(config.get("path","unknown.msix"))).name,
        sha256=job.sha256 if job else None,
        result=outcome, partner_center_confirmation=confirmation,
        run_id=os.environ.get("GITHUB_RUN_ID"), run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
        details=details,
    )
    receipt["receipt_id"]=uuid4().hex
    # Preserve the historical receipt.json without replacing it. Every later
    # run receives its own immutable execution receipt.
    receipt_path=workdir/"receipt.json"
    if receipt_path.exists():
        receipt_path=workdir/f"receipt-{receipt['receipt_id']}.json"
    with receipt_path.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(receipt,stream,ensure_ascii=False,sort_keys=True,indent=2); stream.write("\n")
    if journal is not None:
        journal.append(receipt)

if __name__ == "__main__": raise SystemExit(main())
