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

from all_auto.handoff_bridge import stage_bundle

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

def latest_artifact()->tuple[int,str]:
    response=json.loads(gh("api","-X","GET",
        "repos/"+REMOTE+"/actions/artifacts?per_page=100"))
    arts=response.get("artifacts")
    if not isinstance(arts,list):
        raise ValueError("malformed central GitHub artifact response")
    choices=[a for a in arts if isinstance(a,dict)
       and isinstance(a.get("id"),int)
       and isinstance(a.get("workflow_run"),dict)
       and isinstance(a["workflow_run"].get("id"),int)
       and isinstance(a.get("name"),str)
       and a["name"].startswith(PREFIX) and a.get("expired") is False]
    if not choices:raise ValueError("No QA handoff artifact available")
    selected=max(choices,key=lambda a:a["id"])
    run_id=selected["workflow_run"]["id"]
    run=json.loads(gh("api","-X","GET","repos/"+REMOTE+"/actions/runs/"+str(run_id)))
    if (run.get("name")!="Factory MSIX intake and local QA handoff" or
        run.get("conclusion")!="success"):
        raise ValueError("Untrusted central intake workflow")
    return run_id,selected["name"]

def pull(target:Path)->dict:
    run_id,name=latest_artifact()
    if target.is_symlink():raise ValueError("refusing symlink target")
    target.mkdir(parents=True,exist_ok=True)
    existing=[p for p in target.iterdir() if p.is_dir()]
    if len(existing)>=MAX_QUEUED:
        raise ValueError("Local QA inbox full. Archive or process products first.")
    with tempfile.TemporaryDirectory(prefix="storeqa-") as work:
        download=Path(work)
        gh("run","download",str(run_id),"-R",REMOTE,"--name",name,"--dir",str(download))
        queue=json.loads((download/"queue.json").read_text(encoding="utf-8"))
        if queue.get("schema_version")!=1 or queue.get("mode")!="WINDOWS_LOCAL_QA_ONLY":
            raise ValueError("Wrong queue schema or permission state")
        items=queue.get("items")
        if not isinstance(items,list) or not 0<=len(items)<=20 or queue.get("intake_count")!=len(items):
            raise ValueError("Invalid queue count")
        entries=[]
        package_root=download/"packages"
        for item in items:
            if not isinstance(item,dict) or item.get("submit_allowed") is not False:
                raise ValueError("No local QA artifact may authorize Store submission")
            slug=item.get("slug")
            checksum=item.get("package_sha256")
            if not isinstance(slug,str) or not isinstance(checksum,str):
                raise ValueError("Missing package identity")
            source=package_root/(slug+"-"+checksum[:12])
            if not source.is_dir():raise ValueError("Missing source package directory")
            result=stage_bundle(source,target,item.get("source_sha"))
            if result["package_sha256"]!=checksum:
                raise ValueError("Mismatch between local queue and actual bytes")
            entries.append({"slug":slug,"sha256":checksum,
                "status":"DOWNLOADED_AWAITING_WINDOWS_QA"})
        total=sum(p.stat().st_size for p in target.rglob("*.msix") if p.is_file())
        if total>MAX_QUEUED_BYTES:
            raise ValueError("Local QA inbox exceeded 2GiB; stop before more downloads")
    return {"run_id":run_id,"downloaded_or_verified":len(entries),"total_bytes":total,
            "products":entries,"submitted_to_store":0}

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
