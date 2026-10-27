"""Windows local pull-only worker for verified GitHub factory MSIX handoffs.

Requires GitHub CLI (gh auth login), Python 3.12. No Ollama, Store credentials,
installer execution, signing, packaging, or unattended certification.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from all_auto.handoff_bridge import stage_bundle, validate_bundle
from all_auto.lane_queue import relative_package_path

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

def recent_artifacts()->list[tuple[int,str]]:
    # A busy intake may publish many artifacts during the central retention
    # window. Never silently discard older QA packages.
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
    for a in choices:
        run_id=a["workflow_run"]["id"]
        run=json.loads(gh("api","-X","GET",
            "repos/"+REMOTE+"/actions/runs/"+str(run_id)))
        if (run.get("name")!="Factory MSIX intake and local QA handoff" or
            run.get("conclusion")!="success"):
            continue
        verified.append((run_id,a["name"]))
    return verified

def pull(target:Path)->dict:
    artifacts=recent_artifacts()
    if not artifacts:
        raise ValueError("No successful central QA handoff artifact is available")
    if target.is_symlink():raise ValueError("refusing symlink target")
    target.mkdir(parents=True,exist_ok=True)
    imported=[]
    total=sum(p.stat().st_size for p in target.rglob("*.msix") if p.is_file())
    for run_id,name in artifacts:
        with tempfile.TemporaryDirectory(prefix="storeqa-") as work:
            download=Path(work)
            gh("run","download",str(run_id),"-R",REMOTE,"--name",name,"--dir",str(download))
            queue=json.loads((download/"queue.json").read_text(encoding="utf-8"))
            if queue.get("schema_version")!=1 or queue.get("mode")!="WINDOWS_LOCAL_QA_ONLY":
                raise ValueError("Wrong queue schema or permission state")
            items=queue.get("items")
            if not isinstance(items,list) or not 0<=len(items)<=20 or queue.get("intake_count")!=len(items):
                raise ValueError("Invalid queue count")
            package_root=download/"packages"
            for item in items:
                if not isinstance(item,dict) or item.get("submit_allowed") is not False:
                    raise ValueError("No local QA artifact may authorize Store submission")
                slug=item.get("slug")
                checksum=item.get("package_sha256")
                size=item.get("package_bytes")
                if (not isinstance(slug,str) or not isinstance(checksum,str) or
                    type(size) is not int or size<0):
                    raise ValueError("Missing package metadata")
                folder=relative_package_path(item)
                source=package_root/folder
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
                prior=(target/folder).is_dir()
                if not prior:
                    queued=sum(1 for p in target.rglob("package.msix") if p.is_file())
                    if queued>=MAX_QUEUED:
                        return {"status":"HOLD_LOCAL_CAPACITY",
                                "reason":"LOCAL_QA_INBOX_FULL",
                                "inspected_artifacts":len(artifacts),
                                "new_packages":len(imported),"total_bytes":total,
                                "products":imported,"remote_backlog_preserved":True,
                                "submitted_to_store":0}
                    if total+size>MAX_QUEUED_BYTES:
                        return {"status":"HOLD_LOCAL_CAPACITY",
                                "reason":"LOCAL_QA_INBOX_BYTES_LIMIT",
                                "inspected_artifacts":len(artifacts),
                                "new_packages":len(imported),"total_bytes":total,
                                "products":imported,"remote_backlog_preserved":True,
                                "submitted_to_store":0}
                result=stage_bundle(source,target,item.get("factory_head_sha",item["source_sha"]))
                if result["package_sha256"]!=checksum:
                    raise ValueError("Mismatch between queue and actual bytes")
                if not prior:
                    total+=size
                    imported.append({"slug":slug,"sha256":checksum,
                        "product_type":result.get("product_type"),
                        "request_id":result.get("request_id"),
                        "status":"DOWNLOADED_AWAITING_WINDOWS_QA"})
    return {"status":"OK","inspected_artifacts":len(artifacts),
            "new_packages":len(imported),"total_bytes":total,
            "products":imported,"remote_backlog_preserved":True,
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
