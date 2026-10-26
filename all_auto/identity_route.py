"""Validate official Store identity evidence and select the exact Factory return path.

This module never registers or guesses Microsoft IDs and never contacts GitHub.
The returned proposal needs an authenticated operator/worker to verify evidence,
compare expected HEAD and push to the indicated *work branch*.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

OWNER="shihuiarenjinba-png"
TARGETS={
  "app": ("AI-App-Factory","codex/factory-autoloop-20261026"),
  "game": ("AI-Game-Factory","codex/factory-autoloop-20261026"),
  "3d-game": ("3d-game-factory","codex/3d-factory-bootstrap-20261026"),
}
SLUG=re.compile(r"^[a-z][a-z0-9-]{3,39}$")
SHA40=re.compile(r"^[a-f0-9]{40}$")
STORE_ID=re.compile(r"^[A-Za-z0-9]{8,32}$")
NAME=re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,49}$")
VERSION=re.compile(r"^\d{1,5}(?:\.\d{1,5}){3}$")

def route_identity(record:dict)->dict:
    if not isinstance(record,dict) or record.get("schema_version")!=1:
        raise ValueError("identity return contract unsupported")
    kind=record.get("type")
    if kind not in TARGETS:raise ValueError("only app/game/3d-game Factory supported")
    slug=record.get("slug")
    if not isinstance(slug,str) or not SLUG.fullmatch(slug):
        raise ValueError("unsafe product slug")
    sha=record.get("expected_head_sha")
    if not isinstance(sha,str) or not SHA40.fullmatch(sha):
        raise ValueError("exact expected GitHub branch HEAD required")
    identity=record.get("identity")
    if not isinstance(identity,dict):raise ValueError("official Store identity missing")
    for key,pattern in (("store_id",STORE_ID),("name",NAME),("version",VERSION)):
        value=identity.get(key)
        if not isinstance(value,str) or not pattern.fullmatch(value):
            raise ValueError("invalid official Identity field: "+key)
    publisher=identity.get("publisher")
    if not isinstance(publisher,str) or not publisher.startswith("CN=") or len(publisher)>512:
        raise ValueError("official Publisher missing")
    evidence=record.get("official_evidence_url")
    if not isinstance(evidence,str):
        raise ValueError("official Partner Center evidence required")
    url=urlparse(evidence)
    if (url.scheme!="https" or url.hostname not in
        ("partner.microsoft.com","partnercenter.microsoft.com") or
        url.username or url.password or url.fragment):
        raise ValueError("untrusted Partner Center evidence URL")
    if record.get("operator_verified") is not True:
        raise ValueError("authenticated operator verification missing")
    verifier=record.get("verified_by")
    if not isinstance(verifier,str) or not 3<=len(verifier)<=100 or any(x in verifier for x in ("\n","\r","\x00")):
        raise ValueError("operator identifier missing")
    repo,branch=TARGETS[kind]
    product_dir="products/"+slug+"/store/"
    content={
       "reviewed":True,"source":"partner_center",
       "store_id":identity["store_id"],"name":identity["name"],
       "publisher":publisher,"version":identity["version"],
       "verified_by":verifier,"evidence_url":evidence
    }
    for label in ("display_name","publisher_display_name"):
        value=identity.get(label)
        if isinstance(value,str) and 1<=len(value)<=100:
            content[label]=value
    return {
       "schema_version":1,"operation":"PROPOSE_WORK_BRANCH_IDENTITY_RETURN",
       "repository":OWNER+"/"+repo,"branch":branch,
       "expected_head_sha":sha,
       "path":product_dir+"approved-identity.json",
       "content":content,"applied":False,"store_submitted":False,
       "note":"Check actual Microsoft account evidence and compare branch HEAD before any write."
    }

def main(argv=None)->int:
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    args=p.parse_args(argv)
    try:
        if args.input.stat().st_size>32_768:
            raise ValueError("input is too large")
        result=route_identity(json.loads(args.input.read_text(encoding="utf-8")))
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(result["repository"],result["branch"],result["path"],"HOLD until verified branch write")
        return 0
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print("IDENTITY_RETURN_HOLD:",type(exc).__name__,str(exc)[:160],file=sys.stderr)
        return 2
if __name__=="__main__":raise SystemExit(main())
