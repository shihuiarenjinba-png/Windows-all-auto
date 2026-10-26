"""Read-only 15-minute Store portfolio source/CI monitor.

Never signs, prices, uploads, creates products or submits to Microsoft Store.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

OWNER="shihuiarenjinba-png"
NAME=re.compile(r"^[A-Za-z0-9_.-]{1,85}$")
ID=re.compile(r"^[a-z][a-z0-9_-]{2,60}$")
REF=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,120}$")
SHA=re.compile(r"^[a-fA-F0-9]{40}$")

def inventory(path:Path)->list[dict[str,str]]:
    if path.stat().st_size > 100_000:
        raise ValueError("inventory is too large")
    body=json.loads(path.read_text(encoding="utf-8"))
    rows=body.get("products") if isinstance(body,dict) and body.get("schema_version")==1 else None
    if not isinstance(rows,list) or not 1 <= len(rows) <= 100:
        raise ValueError("inventory must have 1-100 products")
    seen=set()
    result=[]
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError("non-object product")
        id_,kind,repo,ref=(row.get(k) for k in ("id","type","repository","ref"))
        if not isinstance(id_,str) or not ID.fullmatch(id_) or id_ in seen:
            raise ValueError("invalid or duplicate product id")
        if kind not in ("app","game"):
            raise ValueError("invalid product type")
        if not isinstance(repo,str) or not NAME.fullmatch(repo) or repo in (".",".."):
            raise ValueError("invalid GitHub repo")
        if not isinstance(ref,str) or not REF.fullmatch(ref) or ".." in ref or "//" in ref:
            raise ValueError("invalid ref")
        if row.get("security_confirmed") is True or row.get("auto_submit") is True:
            raise ValueError("inventory cannot grant security or publication approval")
        seen.add(id_)
        result.append({"id":id_,"type":kind,"repository":repo,"ref":ref})
    return result

def api(route:str)->Any:
    if not route.startswith("/repos/"+OWNER+"/"):
        raise ValueError("unapproved GitHub API scope")
    token=os.environ.get("GITHUB_TOKEN","")
    request=Request("https://api.github.com"+route,headers={
        "Accept":"application/vnd.github+json",
        "User-Agent":"WindowsAllAuto-QuarterHourly",
        **({"Authorization":"Bearer "+token} if token else {})})
    with urlopen(request,timeout=12) as response:
        data=response.read(800001)
    if len(data)>800000:
        raise ValueError("GitHub reply over size limit")
    return json.loads(data)

def inspect(row:dict[str,str],get:Callable[[str],Any])->dict[str,Any]:
    base="/repos/"+OWNER+"/"+row["repository"]
    result={**row,"repository_url":"https://github.com/"+OWNER+"/"+row["repository"],
            "source_sha":None,"ci":"UNVERIFIED","status":"HOLD",
            "reason":"SOURCE_UNVERIFIED","store_submission":"NOT_ATTEMPTED",
            "windows_qa":"NOT_TESTED","msix":"UNVERIFIED"}
    try:
        commit=get(base+"/commits/"+quote(row["ref"],safe=""))
        sha=commit.get("sha") if isinstance(commit,dict) else None
        if not isinstance(sha,str) or not SHA.fullmatch(sha):
            result["reason"]="BAD_SOURCE_SHA"
            return result
        result["source_sha"]=sha.lower()
        checks=get(base+"/actions/runs?head_sha="+sha+"&per_page=25")
        runs=checks.get("workflow_runs") if isinstance(checks,dict) else None
        if not isinstance(runs,list):
            result["reason"]="NO_VERIFIABLE_CI_DATA"
            return result
        accepted=[r for r in runs if isinstance(r,dict) and
                 str(r.get("head_sha","")).lower()==sha.lower() and
                 r.get("status")=="completed" and
                 r.get("conclusion")=="success" and
                 r.get("event") in ("push","pull_request","workflow_dispatch")]
        if not accepted:
            result["reason"]="NO_SUCCESSFUL_CI_AT_CURRENT_SHA"
            return result
        accepted.sort(key=lambda x:str(x.get("created_at","")),reverse=True)
        result["ci"]="SUCCESS_AT_SOURCE_SHA"
        result["ci_run_id"]=accepted[0].get("id")
        result["status"]="WINDOWS_INSPECTION_CANDIDATE"
        result["reason"]="GUI_MSIX_IDENTITY_SECURITY_PRICE_REVIEW_REQUIRED"
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,KeyError) as exc:
        if isinstance(exc,HTTPError) and exc.code in (401,403,404):
            result["reason"]="PRIVATE_REPO_OR_INVALID_REF"
        else:
            result["reason"]="GITHUB_READ_FAILED"
    return result

def compile_report(rows:list[dict[str,str]],get:Callable[[str],Any])->tuple[dict,dict]:
    results=[inspect(r,get) for r in rows]
    counts=dict(Counter(r["status"] for r in results))
    report={"schema_version":1,"mode":"READ_ONLY_CI_SCAN",
            "generated_at_utc":datetime.now(timezone.utc).isoformat(),
            "total":len(results),"counts":counts,"products":results,
            "store_uploads_attempted":0,"drafts_saved":0,"submissions_made":0}
    tasks=[{"id":r["id"],"type":r["type"],"repository":r["repository_url"],
            "ref":r["ref"],"sha":r["source_sha"],
            "next_action":"WINDOWS_GUI_MSIX_QA",
            "security_confirmed":False,"approved_identity":None,
            "approved_price":None,"store_submission_allowed":False}
           for r in results if r["status"]=="WINDOWS_INSPECTION_CANDIDATE"]
    queue={"schema_version":1,"mode":"LOCAL_INSPECTION_ONLY",
           "total":len(tasks),"tasks":tasks}
    return report,queue

def markdown_report(report:dict)->str:
    lines=["# 15-minute product source verification","",
           "**Read-only. No Windows QA, MSIX verification or Store write attempted.**","",
           "Total: "+str(report["total"]),
           "Inspection candidates: "+str(report["counts"].get("WINDOWS_INSPECTION_CANDIDATE",0)),
           "HOLD: "+str(report["counts"].get("HOLD",0)),"",
           "| Product | Kind | Source SHA | CI | Status | Missing gate |",
           "|---|---|---|---|---|---|"]
    for r in report["products"]:
        lines.append("| "+" | ".join([r["id"],r["type"],
            (r["source_sha"] or "UNKNOWN")[:12],r["ci"],r["status"],r["reason"]])+" |")
    lines.append("\nSecurity, Store Identity, price, and human approval are never inferred.\n")
    return "\n".join(lines)

def main(argv:list[str]|None=None)->int:
    p=argparse.ArgumentParser()
    p.add_argument("--inventory",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--offline",action="store_true")
    args=p.parse_args(argv)
    try:
        rows=inventory(args.inventory)
        def offline(_route):
            raise ValueError("offline cannot confirm GitHub status")
        report,queue=compile_report(rows,offline if args.offline else api)
        args.out.mkdir(parents=True,exist_ok=True)
        (args.out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        (args.out/"local-qa-queue.json").write_text(json.dumps(queue,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        (args.out/"report.md").write_text(markdown_report(report),encoding="utf-8")
        path=os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with Path(path).open("a",encoding="utf-8") as f:
                f.write(markdown_report(report)+"\n")
        print("INSPECTION_FINISHED",json.dumps(report["counts"]))
        return 0
    except (ValueError,OSError,TypeError,KeyError) as exc:
        print("CONFIG_HOLD:",type(exc).__name__,str(exc)[:140],file=sys.stderr)
        return 2

if __name__=="__main__":
    raise SystemExit(main())
