"""Poll Factory Actions artifacts, verify package bytes, stage only new MSIX bundles.

GITHUB_TOKEN cannot read private cross-repository artifacts on its own. Use a
dedicated FACTORY_READ_TOKEN with actions:read on just the three Factory repos.
Never runs downloaded files and never contacts Microsoft Store.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .handoff_bridge import stage_bundle, validate_bundle

OWNER="shihuiarenjinba-png"
FACTORIES=("AI-App-Factory","AI-Game-Factory","3d-game-factory")
PREFIX="factory-msix-handoff-"
MAX_PER_FACTORY=6  # 3 lanes x 6 <= 20 local pull queue item limit
MAX_ARTIFACT_PAGES=10

def command(*parts:str)->str:
    result=subprocess.run(["gh",*parts],capture_output=True,text=True,
        encoding="utf-8",timeout=45,check=False)
    if result.returncode:
        raise RuntimeError("GitHub authenticated artifact operation failed")
    if len(result.stdout)>1_000_000:
        raise RuntimeError("GitHub metadata exceeded safe size")
    return result.stdout

def api(route:str)->dict:
    result=json.loads(command("api","-X","GET",route))
    if not isinstance(result,dict):
        raise ValueError("GitHub API response is not object")
    return result

def all_artifacts(repository:str)->dict:
    """Read the complete bounded artifact backlog, never only the newest 100.

    GitHub lists newest artifacts first. A fixed first-page query can starve
    older unprocessed products forever under sustained factory production.
    Fail closed if the listing changes mid-scan or exceeds the safe bound.
    """
    combined=[]
    expected_total=None
    for page in range(1,MAX_ARTIFACT_PAGES+1):
        payload=api("repos/"+repository+"/actions/artifacts?per_page=100&page="+str(page))
        count=payload.get("total_count")
        items=payload.get("artifacts")
        if type(count) is not int or count<0 or not isinstance(items,list) or len(items)>100:
            raise ValueError("invalid Factory artifact page")
        if count>MAX_ARTIFACT_PAGES*100:
            raise ValueError("Factory artifact backlog exceeds safe scan bound; HOLD")
        if expected_total is None:
            expected_total=count
        elif count!=expected_total:
            raise ValueError("Factory artifact listing changed during scan; retry")
        combined.extend(items)
        if len(items)<100:
            if len(combined)!=expected_total:
                raise ValueError("Factory artifact listing incomplete; retry")
            return {"artifacts":combined}
    if len(combined)!=expected_total:
        raise ValueError("Factory artifact listing incomplete at scan bound; retry")
    return {"artifacts":combined}

def candidates(payload:dict,processed:set[int])->list[dict]:
    items=payload.get("artifacts")
    if not isinstance(items,list):raise ValueError("GitHub artifact list invalid")
    valid=[]
    for a in items:
        if (isinstance(a,dict) and isinstance(a.get("id"),int)
            and a["id"] not in processed
            and isinstance(a.get("name"),str)
            and a["name"].startswith(PREFIX)
            and a.get("expired") is False
            and isinstance(a.get("workflow_run"),dict)
            and isinstance(a["workflow_run"].get("id"),int)):
            valid.append(a)
    return sorted(valid,key=lambda x:x["id"])[:MAX_PER_FACTORY]

def verified_run(data:dict,expected_repo:str,artifact:dict)->str:
    if not isinstance(data,dict) or data.get("conclusion")!="success":
        raise ValueError("source run not successful")
    if data.get("name")!="Factory MSIX export" or data.get("event") not in ("push","workflow_dispatch"):
        raise ValueError("source workflow or event is untrusted")
    # Workflow display names are not unique: a different workflow can use the
    # same name and upload a lookalike artifact. Bind provenance to the exact
    # reviewed MSIX export workflow file and the artifact's actual run ID.
    if data.get("path")!=".github/workflows/msix-export.yml":
        raise ValueError("source workflow path is untrusted")
    if (type(data.get("id")) is not int or
        data["id"]!=artifact.get("workflow_run",{}).get("id")):
        raise ValueError("artifact workflow run mismatch")
    if data.get("head_repository",{}).get("full_name")!=expected_repo:
        raise ValueError("source repository mismatch")
    ref=data.get("head_branch")
    if not isinstance(ref,str) or not ref.startswith("codex/"):
        raise ValueError("unapproved build branch")
    sha=data.get("head_sha")
    if not isinstance(sha,str) or len(sha)!=40:
        raise ValueError("missing source commit SHA")
    return sha

def intake(ledger_path:Path,out:Path)->dict:
    if not os.environ.get("GH_TOKEN"):
        raise ValueError("FACTORY_READ_TOKEN unavailable")
    ledger=json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger.get("schema_version")!=1 or not isinstance(ledger.get("processed_artifacts"),list):
        raise ValueError("invalid intake ledger")
    processed=set(ledger["processed_artifacts"])
    request_sources=ledger.get("request_sources",{})
    if not isinstance(request_sources,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in request_sources.items()):
        raise ValueError("invalid immutable request ledger")
    if any(type(i) is not int or i<=0 for i in processed):
        raise ValueError("corrupt artifact ledger")
    staged=[]
    attempted=0
    for factory in FACTORIES:
        repository=OWNER+"/"+factory
        payload=all_artifacts(repository)
        for artifact in candidates(payload,processed):
            attempted+=1
            run_id=artifact["workflow_run"]["id"]
            run=api("repos/"+repository+"/actions/runs/"+str(run_id))
            source_sha=verified_run(run,repository,artifact)
            name=artifact["name"]
            if not name[len(PREFIX):].replace("-","").isalnum():
                raise ValueError("unsafe artifact name")
            downloaded=out/"incoming"/factory/str(artifact["id"])
            downloaded.mkdir(parents=True,exist_ok=False)
            command("run","download",str(run_id),"-R",repository,
                "--name",name,"--dir",str(downloaded))
            checked=validate_bundle(downloaded,source_sha)
            if checked.get("source_branch") and checked["source_branch"]!=run["head_branch"]:
                raise ValueError("Factory source_branch / Actions branch mismatch")
            if checked.get("request_id"):
                key=checked["product_type"]+":"+checked["request_id"]
                prior=request_sources.get(key)
                if prior is not None and prior!=checked["source_sha"]:
                    raise ValueError("HANDOFF_CONFLICT: request_id changed source_sha")
            result=stage_bundle(downloaded,out/"packages",source_sha)
            if checked.get("request_id"):
                request_sources[key]=checked["source_sha"]
            result["factory_run_id"]=run_id
            result["factory_artifact_id"]=artifact["id"]
            staged.append(result)
            processed.add(artifact["id"])
    (out/"queue.json").write_text(json.dumps({
        "schema_version":1,"mode":"WINDOWS_LOCAL_QA_ONLY",
        "intake_count":len(staged),"items":staged,
        "store_submissions":0},indent=2)+"\n",encoding="utf-8")
    # Persist only small integer IDs. Packages stay in short-retention Actions artifacts.
    ledger["processed_artifacts"]=sorted(processed)[-1500:]
    ledger["request_sources"]=request_sources
    ledger_path.write_text(json.dumps(ledger,indent=2)+"\n",encoding="utf-8")
    shutil.rmtree(out/"incoming",ignore_errors=True)
    return {"received":len(staged),"scanned":attempted}

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--ledger",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        args.out.mkdir(parents=True,exist_ok=True)
        print(json.dumps(intake(args.ledger,args.out)))
        return 0
    except (ValueError,RuntimeError,OSError,TypeError,KeyError,
            subprocess.TimeoutExpired,json.JSONDecodeError) as exc:
        print("BRIDGE_HOLD:",str(exc)[:160],file=sys.stderr)
        return 2

if __name__=="__main__":raise SystemExit(main())
