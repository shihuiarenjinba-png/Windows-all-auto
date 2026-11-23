from __future__ import annotations
import argparse, json, os, re, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import quote
from uploader.core import JobLedger, UploadError, process_job, validate_config
from uploader.partner_center_browser import PartnerCenterCDPConnection

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
    parser=argparse.ArgumentParser(); source=parser.add_mutually_exclusive_group(required=True); source.add_argument("--config",type=Path); source.add_argument("--product"); parser.add_argument("--workdir",type=Path,default=Path(".uploader-run")); parser.add_argument("--execute",action="store_true"); args=parser.parse_args()
    try:
        config_file=resolve_job_config(config_path=args.config, product_key=args.product)
        config=validate_config(json.loads(config_file.read_text(encoding="utf-8")))
        if args.execute and config.get("upload_approved") is not True:
            raise UploadError("UPLOAD_NOT_APPROVED", "This product job is not approved for a live package write")
        if args.execute and not re.fullmatch(r"[0-9a-fA-F]{64}", str(config.get("expected_sha256", ""))):
            raise UploadError("EXPECTED_SHA_REQUIRED", "Live upload requires a frozen 64-character SHA-256")
        if args.execute and not os.environ.get("PARTNER_CENTER_CDP_URL"):
            raise UploadError("BROWSER_SESSION_UNAVAILABLE", "Set the authenticated remote browser CDP secret before live execution")
        package=args.workdir/Path(config["path"]).name
        github_download(config["repository"],config["ref"],config["path"],os.environ.get("GH_READ_TOKEN"),package,
                        max_bytes=int(config.get("max_bytes",4_000_000_000)))
        expected=config.get("expected_sha256"); expected=None if not expected or expected.startswith("REPLACE_") else expected
        with JobLedger(args.workdir/"ledger.sqlite3") as ledger:
            if args.execute:
                def browser_operation(job, package_path, *, reconcile=False):
                    with PartnerCenterCDPConnection(os.environ["PARTNER_CENTER_CDP_URL"], config) as port:
                        if reconcile:
                            return port.reconcile_ambiguous_upload(job, package_path)
                        return port.upload_save_and_reconcile(job, package_path)
                result=process_job(config,package,ledger,expected_sha256=expected,dry_run=False,
                                   live_adapter=lambda job,path: browser_operation(job,path),
                                   reconcile_adapter=lambda job,path: browser_operation(job,path,reconcile=True))
            else:
                result=process_job(config,package,ledger,expected_sha256=expected,dry_run=True)
        print(json.dumps(result,sort_keys=True)); return 0
    except UploadError as exc:
        print(json.dumps({"status":"FAILED","error_code":exc.code,"message":str(exc)},sort_keys=True)); return 2

if __name__ == "__main__": raise SystemExit(main())
