from __future__ import annotations
import argparse, json, os, urllib.error, urllib.request
from pathlib import Path
from uploader.core import JobLedger, UploadError, process_job

def github_download(repository, ref, path, token, target):
    url = f"https://api.github.com/repos/{repository}/contents/{path}?ref={ref}"
    headers = {"Accept":"application/vnd.github.raw+json", "X-GitHub-Api-Version":"2022-11-28"}
    if token: headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
            if response.status != 200: raise UploadError("DOWNLOAD_FAILED", f"GitHub HTTP {response.status}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                while chunk := response.read(1024*1024): stream.write(chunk)
    except urllib.error.HTTPError as exc:
        code = {401:"AUTH_FAILED",403:"PERMISSION_DENIED",404:"FILE_NOT_FOUND"}.get(exc.code,"DOWNLOAD_FAILED")
        raise UploadError(code, f"GitHub download HTTP {exc.code}") from exc
    except TimeoutError as exc: raise UploadError("TIMEOUT", "GitHub download timed out") from exc

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--config",type=Path,required=True); parser.add_argument("--workdir",type=Path,default=Path(".uploader-run")); parser.add_argument("--execute",action="store_true"); args=parser.parse_args()
    config=json.loads(args.config.read_text(encoding="utf-8")); package=args.workdir/Path(config["path"]).name
    try:
        github_download(config["repository"],config["ref"],config["path"],os.environ.get("GH_READ_TOKEN"),package)
        expected=config.get("expected_sha256"); expected=None if not expected or expected.startswith("REPLACE_") else expected
        with JobLedger(args.workdir/"ledger.sqlite3") as ledger:
            result=process_job(config,package,ledger,expected_sha256=expected,dry_run=not args.execute)
        print(json.dumps(result,sort_keys=True)); return 0
    except UploadError as exc:
        print(json.dumps({"status":"FAILED","error_code":exc.code,"message":str(exc)},sort_keys=True)); return 2

if __name__ == "__main__": raise SystemExit(main())
