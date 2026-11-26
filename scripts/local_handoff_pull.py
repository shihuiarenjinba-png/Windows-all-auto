"""Windows local pull-only worker for verified GitHub factory MSIX handoffs.

Requires GitHub CLI (gh auth login), Python 3.12. No Ollama, Store credentials,
installer execution, signing, packaging, or unattended certification.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from all_auto.handoff_bridge import stage_bundle, validate_bundle
from scripts.github_artifact_custody import github_clients, verify_queue_artifact_custody, safe_package_folder

REMOTE="shihuiarenjinba-png/Windows-all-auto"
PREFIX="verified-msix-local-qa-"
MAX_QUEUED=20
MAX_QUEUED_BYTES=2*1024*1024*1024

def gh(*args:str)->str:
    r=subprocess.run(["gh",*args],capture_output=True,text=True,encoding="utf-8",
        timeout=60,check=False)
    if r.returncode!=0:
        raise RuntimeError("GitHub authentication, API or artifact fetch failed")
    if len(r.stdout)>1_000_000:
        raise ValueError("unexpectedly large metadata")
    return r.stdout

def recent_artifacts()->list[dict]:
    # A busy 15-minute intake may publish more than 30 artifacts within the
    # two-day retention window. Never silently discard older QA packages.
    # Page the full GitHub listing, with an explicit HOLD if it is too large.
    artifacts=[]
    for page in range(1,11):
        response=json.loads(gh("api","-X","GET",
            "repos/"+REMOTE+"/actions/artifacts?per_page=100&page="+str(page)))
        arts=response.get("artifacts")
        if not isinstance(arts,list) or len(arts)>100:
            raise ValueError("malformed central GitHub artifact response")
        artifacts.extend(arts)
        if len(arts)<100:
            count=response.get("total_count")
            if type(count) is int and len(artifacts)<count:
                raise ValueError("Central QA artifact listing incomplete; retry")
            break
    else:
        raise ValueError("Central QA artifact listing exceeds 1000; HOLD rather than skip")
    choices={a["id"]:a for a in artifacts if isinstance(a,dict)
       and type(a.get("id")) is int
       and isinstance(a.get("workflow_run"),dict)
       and type(a["workflow_run"].get("id")) is int
       and isinstance(a.get("name"),str)
       and a["name"].startswith(PREFIX) and a.get("expired") is False}
    choices=sorted(choices.values(),key=lambda a:a["id"])
    verified=[]
    for artifact in choices:
        run_id=artifact["workflow_run"]["id"]
        run=json.loads(gh("api","-X","GET",
            "repos/"+REMOTE+"/actions/runs/"+str(run_id)))
        head=run.get("head_sha")
        if (run.get("name")!="Factory MSIX intake and local QA handoff"
                or run.get("status")!="completed"
                or run.get("conclusion")!="success"
                or not isinstance(head,str) or len(head)!=40
                or any(c not in "0123456789abcdef" for c in head)):
            continue
        verified.append({
            "run_id":run_id,
            "artifact_id":artifact["id"],
            "artifact_name":artifact["name"],
            "run_head_sha":head,
        })
    return verified


def record_custody_receipt(target:Path,artifact_id:int,data:dict)->Path:
    folder=target/".artifact-custody"
    if folder.is_symlink():
        raise ValueError("CUSTODY_RECEIPT_DIRECTORY_LINKED")
    folder.mkdir(exist_ok=True)
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("CUSTODY_RECEIPT_DIRECTORY_UNAVAILABLE")
    path=folder/(str(artifact_id)+".json")
    payload=json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    if path.is_symlink():
        raise ValueError("CUSTODY_RECEIPT_LINKED")
    if path.exists():
        if not path.is_file() or path.stat().st_size > 16 * 1024:
            raise ValueError("CUSTODY_RECEIPT_INVALID")
        existing=json.loads(path.read_text(encoding="utf-8"))
        if existing!=data:
            raise ValueError("CUSTODY_RECEIPT_CONFLICT")
        return path
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os,"O_NOFOLLOW"):
        flags|=os.O_NOFOLLOW
    fd=os.open(str(path),flags,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return path


def pull(target:Path)->dict:
    artifacts=recent_artifacts()
    if not artifacts:
        raise ValueError("No successful central QA handoff artifact is available")
    if target.is_symlink():raise ValueError("refusing symlink target")
    target.mkdir(parents=True,exist_ok=True)
    if target.is_symlink() or not target.is_dir():
        raise ValueError("LOCAL_QA_TARGET_UNAVAILABLE")
    token=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        token=gh("auth","token").strip()
    fetch_json,fetch_bytes=github_clients(token)
    imported=[]
    custody_receipts=[]
    total=0
    for existing in target.rglob("*.msix"):
        if existing.is_symlink():
            raise ValueError("LOCAL_PACKAGE_LINKED")
        if existing.is_file():
            total += existing.stat().st_size
    if total > MAX_QUEUED_BYTES:
        raise ValueError("Local QA inbox already exceeds 2GiB; HOLD")
    for artifact in artifacts:
        run_id=artifact["run_id"]
        artifact_id=artifact["artifact_id"]
        name=artifact["artifact_name"]
        with tempfile.TemporaryDirectory(prefix="storeqa-") as work:
            download=Path(work)
            gh("run","download",str(run_id),"-R",REMOTE,"--name",name,"--dir",str(download))
            custody=verify_queue_artifact_custody({
                "repository":REMOTE,
                "run_id":run_id,
                "artifact_id":artifact_id,
                "artifact_name":name,
                "run_head_sha":artifact["run_head_sha"],
            },download,fetch_json,fetch_bytes)
            if custody.get("status")!="CUSTODY_VERIFIED_ONLY" or custody.get("e2e_pass") is not False:
                raise ValueError("GITHUB_ARTIFACT_CUSTODY_HOLD:"+str(custody.get("reason","UNKNOWN")))
            queue=json.loads((download/"queue.json").read_text(encoding="utf-8"))
            if (queue.get("schema_version")!=1 or queue.get("mode")!="WINDOWS_LOCAL_QA_ONLY"
                    or queue.get("store_submissions")!=0):
                raise ValueError("Wrong queue schema or permission state")
            items=queue.get("items")
            if not isinstance(items,list) or not 0<=len(items)<=20 or queue.get("intake_count")!=len(items):
                raise ValueError("Invalid queue count")
            package_root=download/"packages"
            package_receipts=[]
            for item in items:
                if (not isinstance(item,dict) or item.get("submit_allowed") is not False
                        or item.get("store_id") is not None
                        or item.get("security_confirmed") is not False
                        or item.get("price_approved") is not False):
                    raise ValueError("No local QA artifact may authorize Store submission")
                slug=item.get("slug")
                checksum=item.get("package_sha256")
                size=item.get("package_bytes")
                if (not isinstance(slug,str) or not isinstance(checksum,str) or
                    type(size) is not int or size<0):
                    raise ValueError("Missing package metadata")
                folder=safe_package_folder(item)
                source=package_root
                for part in folder.parts:
                    source=source/part
                    if source.is_symlink():
                        raise ValueError("Local package path is linked")
                if not source.is_dir():raise ValueError("Missing source package directory")
                if not isinstance(item.get("source_sha"),str):
                    raise ValueError("Missing queue source SHA")
                # The queue is transport metadata, not an authority for package size,
                # identity, or provenance. Verify the actual MSIX before quota checks.
                verified=validate_bundle(source,item.get("factory_head_sha",item["source_sha"]))
                for field in ("slug","type","source_repository","source_sha",
                              "package_sha256","package_bytes","identity"):
                    if item.get(field)!=verified[field]:
                        raise ValueError("Queue metadata mismatch: "+field)
                for field in ("request_id","product_type","source_factory","source_branch",
                              "expected_head_sha","factory_head_sha","prebuilt_exe_sha256",
                              "claimed_store_id","contract_status"):
                    if field=="contract_status" and field not in item and verified.get(field)=="LEGACY_HOLD":
                        continue  # old QA-only artifact; never an E2E pass
                    if item.get(field)!=verified.get(field):
                        raise ValueError("Queue immutable metadata mismatch: "+field)
                if item.get("store_id") is not None:
                    raise ValueError("Local QA queue must not assign a Store ID")
                if item.get("security_confirmed") is True or item.get("price_approved") is True:
                    raise ValueError("Local QA queue must not assert Store approvals")
                size=verified["package_bytes"]
                prior_path=target/folder
                if prior_path.is_symlink():
                    raise ValueError("Existing local package path is linked")
                prior=prior_path.is_dir()
                if not prior:
                    if sum(1 for p in target.rglob("package.msix") if p.is_file())>=MAX_QUEUED:
                        raise ValueError("Local QA inbox full; complete/archive existing QA first")
                    if total+size>MAX_QUEUED_BYTES:
                        raise ValueError("Local QA inbox would exceed 2GiB; HOLD")
                result=stage_bundle(source,target,item.get("factory_head_sha",item["source_sha"]))
                if result["package_sha256"]!=checksum:
                    raise ValueError("Mismatch between queue and actual bytes")
                local_package=target/folder/"package.msix"
                if local_package.is_symlink() or not local_package.is_file():
                    raise ValueError("LOCAL_STAGED_PACKAGE_UNAVAILABLE")
                local_digest=hashlib.sha256()
                local_size=0
                with local_package.open("rb") as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b""):
                        local_digest.update(chunk)
                        local_size+=len(chunk)
                local_sha=local_digest.hexdigest()
                if local_sha!=checksum or local_size!=size:
                    raise ValueError("LOCAL_STAGED_BYTES_MISMATCH")
                package_receipts.append({
                    "slug":slug,
                    "request_id":result.get("request_id"),
                    "source_sha":result["source_sha"],
                    "package_sha256":checksum,
                    "package_bytes":size,
                    "local_sha256":local_sha,
                    "local_pull_status":"VERIFIED",
                })
                if not prior:
                    total+=size
                    imported.append({"slug":slug,"sha256":checksum,
                        "product_type":result.get("product_type"),
                        "request_id":result.get("request_id"),
                        "status":"DOWNLOADED_AWAITING_WINDOWS_QA"})
            receipt=dict(custody)
            receipt["local_pull_status"]="VERIFIED"
            receipt["packages"]=package_receipts
            record_custody_receipt(target,artifact_id,receipt)
            custody_receipts.append(receipt)
    return {"inspected_artifacts":len(artifacts),"new_packages":len(imported),
            "total_bytes":total,"products":imported,"custody_receipts":custody_receipts,
            "submitted_to_store":0}


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--target",type=Path,required=True)
    opts=parser.parse_args(argv)
    try:
        print(json.dumps(pull(opts.target),indent=2,ensure_ascii=False))
        return 0
    except (ValueError,RuntimeError,OSError,KeyError,TypeError,
            subprocess.TimeoutExpired,json.JSONDecodeError) as exc:
        print("LOCAL_QA_HOLD:",str(exc)[:180],file=sys.stderr)
        return 2

if __name__=="__main__":raise SystemExit(main())
