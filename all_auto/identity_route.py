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
  "3d-game": ("3d-game-factory","codex/3d-real-msix-build-path-20261027"),
}
SLUG=re.compile(r"^[a-z][a-z0-9-]{3,39}$")
REQUEST_ID=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{3,127}$")
SHA40=re.compile(r"^[a-f0-9]{40}$")
SHA64=re.compile(r"^[a-f0-9]{64}$")
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
    if kind=="3d-game":
        expected_trace={
          "product_type":"GAME_3D",
          "source_factory":"3d-game-factory",
          "source_repository":"shihuiarenjinba-png/3d-game-factory",
          "source_branch":"codex/3d-real-msix-build-path-20261027",
          "source_sha":sha,
        }
        request_id=record.get("request_id")
        if not isinstance(request_id,str) or not REQUEST_ID.fullmatch(request_id):
            raise ValueError("3D identity return requires original request_id")
        for key,expected in expected_trace.items():
            if record.get(key)!=expected:
                raise ValueError("3D manufacturing correlation mismatch: "+key)
        package_sha=record.get("local_package_sha256")
        if not isinstance(package_sha,str) or not SHA64.fullmatch(package_sha):
            raise ValueError("3D identity return requires local package SHA-256")
        if record.get("local_package_kind") not in ("exe","msix","appx"):
            raise ValueError("3D identity return has invalid local package kind")
        signature_status=record.get("local_signature_status")
        if not isinstance(signature_status,str) or not signature_status or len(signature_status)>80:
            raise ValueError("3D identity return requires local signature status")
    identity=record.get("identity")
    if not isinstance(identity,dict):raise ValueError("official Store identity missing")
    for key,pattern in (("store_id",STORE_ID),("name",NAME),("version",VERSION)):
        value=identity.get(key)
        if not isinstance(value,str) or not pattern.fullmatch(value):
            raise ValueError("invalid official Identity field: "+key)
    publisher=identity.get("publisher")
    if not isinstance(publisher,str) or not publisher.startswith("CN=") or len(publisher)>512:
        raise ValueError("official Publisher missing")
    if kind=="3d-game":
        pfn=identity.get("package_family_name")
        sid=identity.get("package_sid")
        if not isinstance(pfn,str) or not 3<=len(pfn)<=256 or any(ch.isspace() for ch in pfn):
            raise ValueError("official Package Family Name missing")
        if not isinstance(sid,str) or not sid.startswith("S-1-15-2-") or len(sid)>512:
            raise ValueError("official Package SID missing")
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
    # Persist the exact Factory source SHA that was authenticated alongside
    # the Partner Center identity. Downstream MSIX builders must compare this
    # value with the product source before packaging; the identity commit itself
    # advances branch HEAD, so relying only on the post-commit HEAD loses the
    # provenance link to the reviewed game/app bytes.
    content={
       "reviewed":True,"source":"partner_center",
       "store_id":identity["store_id"],"name":identity["name"],
       "publisher":publisher,"version":identity["version"],
       "verified_source_sha":sha,
       "verified_by":verifier,"evidence_url":evidence
    }
    if kind=="3d-game":
        content.update({
           "request_id":record["request_id"],"product_type":record["product_type"],
           "source_factory":record["source_factory"],
           "source_repository":record["source_repository"],
           "source_branch":record["source_branch"],"slug":slug,
           "expected_head_sha":sha,
           "local_package_sha256":record["local_package_sha256"],
           "local_package_kind":record["local_package_kind"],
           "local_signature_status":record["local_signature_status"],
           "package_family_name":identity["package_family_name"],
           "package_sid":identity["package_sid"],
        })
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
