"""Poll Factory Actions artifacts, verify package bytes, stage only new MSIX bundles.

GITHUB_TOKEN cannot read private cross-repository artifacts on its own. Use a
dedicated FACTORY_READ_TOKEN with actions:read on just the three Factory repos.
Never runs downloaded files and never contacts Microsoft Store.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import quote, urlparse

from scripts.github_artifact_custody import github_clients, verify_custody
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
    expected_name=("3D Store MSIX candidate build"
                   if expected_repo==OWNER+"/3d-game-factory"
                   else "Factory MSIX export")
    if data.get("name")!=expected_name or data.get("event") not in ("push","workflow_dispatch"):
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


def _git_blob_sha(raw:bytes)->str:
    return hashlib.sha1(b"blob "+str(len(raw)).encode("ascii")+b"\0"+raw).hexdigest()


def _write_once(path:Path,raw:bytes)->None:
    if path.is_symlink() or path.exists() or path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError("APP_TRANSPORT_RECEIPT_EXISTS_OR_LINKED")
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os,"O_NOFOLLOW"):
        flags|=os.O_NOFOLLOW
    fd=os.open(str(path),flags,0o600)
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _prepare_app_identity_return(downloaded:Path,repository:str,run:dict,
                                artifact:dict,source_sha:str)->None:
    """Bind a real APP artifact to the exact current source Identity and independently verify its archive."""
    if repository!=OWNER+"/AI-App-Factory":
        raise ValueError("APP_FACTORY_REPOSITORY_MISMATCH")
    handoff_path=downloaded/"handoff.json"
    if handoff_path.is_symlink() or not handoff_path.is_file() or handoff_path.stat().st_size>32*1024:
        raise ValueError("APP_HANDOFF_METADATA_UNAVAILABLE")
    handoff=json.loads(handoff_path.read_text(encoding="utf-8"))
    if not isinstance(handoff,dict):
        raise ValueError("APP_HANDOFF_METADATA_INVALID")
    branch=run.get("head_branch")
    slug=handoff.get("slug")
    identity=handoff.get("identity")
    store_id=handoff.get("store_id")
    request_id=handoff.get("request_id")
    display_name=handoff.get("display_name")
    exe_sha=handoff.get("prebuilt_exe_sha256")
    package_sha=handoff.get("package_sha256")
    package_bytes=handoff.get("package_bytes")
    if (not isinstance(branch,str) or not re.fullmatch(r"codex/[A-Za-z0-9._/-]+",branch)
            or ".." in branch or "//" in branch
            or not isinstance(slug,str) or not re.fullmatch(r"[a-z][a-z0-9-]{3,39}",slug)
            or handoff.get("type")!="app"
            or handoff.get("product_type")!="APP"
            or handoff.get("source_factory")!="AI-App-Factory"
            or handoff.get("source_repository")!="https://github.com/"+repository
            or handoff.get("source_branch")!=branch
            or handoff.get("source_sha")!=source_sha
            or handoff.get("expected_head_sha")!=source_sha
            or handoff.get("factory_head_sha")!=source_sha
            or not isinstance(request_id,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{3,127}",request_id)
            or not isinstance(store_id,str) or not re.fullmatch(r"[A-Za-z0-9]{8,32}",store_id)
            or not isinstance(display_name,str) or not 1<=len(display_name)<=100
            or not isinstance(exe_sha,str) or not re.fullmatch(r"[0-9a-f]{64}",exe_sha)
            or not isinstance(package_sha,str) or not re.fullmatch(r"[0-9a-f]{64}",package_sha)
            or type(package_bytes) is not int or package_bytes<=0
            or not isinstance(identity,dict)
            or not all(isinstance(identity.get(k),str) and identity.get(k) for k in ("name","publisher","version"))):
        raise ValueError("APP_HANDOFF_SOURCE_BINDING_INVALID")

    # The source branch must still point at the artifact's exact build SHA.
    try:
        branch_data=api("repos/"+repository+"/branches/"+quote(branch,safe=""))
    except (RuntimeError,ValueError,json.JSONDecodeError) as exc:
        raise ValueError("SOURCE_BRANCH_HEAD_UNAVAILABLE") from exc
    if branch_data.get("commit",{}).get("sha")!=source_sha:
        raise ValueError("SOURCE_BRANCH_DRIFT")

    identity_path="products/"+slug+"/store/approved-identity.json"
    try:
        source_file=api("repos/"+repository+"/contents/"+identity_path+"?ref="+source_sha)
        encoded=source_file.get("content")
        if source_file.get("encoding")!="base64" or not isinstance(encoded,str):
            raise ValueError("SOURCE_IDENTITY_ENCODING_INVALID")
        identity_bytes=base64.b64decode("".join(encoded.split()),validate=True)
    except (RuntimeError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
        raise ValueError("CURRENT_SOURCE_APPROVED_IDENTITY_UNAVAILABLE") from exc
    if not 0<len(identity_bytes)<=32*1024:
        raise ValueError("CURRENT_SOURCE_APPROVED_IDENTITY_SIZE_INVALID")
    identity_blob_sha=_git_blob_sha(identity_bytes)
    if source_file.get("sha")!=identity_blob_sha:
        raise ValueError("CURRENT_SOURCE_APPROVED_IDENTITY_BLOB_SHA_MISMATCH")
    try:
        approved=json.loads(identity_bytes.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise ValueError("CURRENT_SOURCE_APPROVED_IDENTITY_INVALID") from exc
    if not isinstance(approved,dict):
        raise ValueError("CURRENT_SOURCE_APPROVED_IDENTITY_INVALID")

    version=approved.get("version")
    verifier=approved.get("verified_by")
    evidence=approved.get("evidence_url")
    parsed=urlparse(evidence) if isinstance(evidence,str) else None
    expected_identity_path="/products/"+store_id+"/identity"
    if (approved.get("reviewed") is not True
            or approved.get("source")!="partner_center"
            or approved.get("request_id")!=request_id
            or approved.get("product_type")!="APP"
            or approved.get("source_factory")!="AI-App-Factory"
            or approved.get("source_repository")!=repository
            or approved.get("source_branch")!=branch
            or approved.get("source_sha")!=source_sha
            or approved.get("verified_source_sha")!=source_sha
            or approved.get("expected_head_sha")!=source_sha
            or approved.get("store_id")!=store_id
            or approved.get("name")!=identity.get("name")
            or approved.get("publisher")!=identity.get("publisher")
            or approved.get("version")!=identity.get("version")
            or approved.get("display_name")!=display_name
            or approved.get("package_version_gate")!="PASS"
            or approved.get("operator_verified") is not True
            or not isinstance(version,str) or not re.fullmatch(r"\d+\.\d+\.\d+\.\d+",version)
            or not isinstance(verifier,str) or not 3<=len(verifier)<=100
            or any(ord(c)<32 or ord(c)==127 for c in verifier)
            or parsed is None or parsed.scheme!="https"
            or parsed.hostname not in ("partner.microsoft.com","partnercenter.microsoft.com")
            or parsed.username or parsed.password or parsed.fragment
            or expected_identity_path.casefold() not in parsed.path.casefold()):
        raise ValueError("CURRENT_SOURCE_APPROVED_IDENTITY_OR_VERSION_HOLD")

    transport={
        "schema_version":1,
        "status":"SOURCE_BOUND_VERSION_APPROVED",
        "source_sha":source_sha,
        "expected_head_sha":source_sha,
        "factory_head_sha":source_sha,
        "source_repository":handoff["source_repository"],
        "product_type":"APP",
        "source_factory":"AI-App-Factory",
        "package_sha256":package_sha,
        "package_bytes":package_bytes,
        "identity":identity,
        "approval_source":"partner_center",
        "package_version_gate":"PASS",
        "package_version":version,
        "operator_verified":True,
        "store_submission_allowed":False,
        "certification_allowed":False,
        "publish_allowed":False,
        "approved_identity_file_sha":identity_blob_sha,
        "verified_by":verifier,
        "evidence_url":evidence,
        "request_id":request_id,
        "source_branch":branch,
        "store_id":store_id,
        "display_name":display_name,
        "prebuilt_exe_sha256":exe_sha
    }
    _write_once(downloaded/"approved-identity.json",identity_bytes)
    _write_once(downloaded/"transport_receipt.json",
                (json.dumps(transport,ensure_ascii=False,sort_keys=True)+"\n").encode("utf-8"))

    token=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN_REQUIRED_FOR_CUSTODY")
    fetch_json,fetch_bytes=github_clients(token)
    expected={
        "repository":repository,
        "run_id":run.get("id"),
        "artifact_id":artifact.get("id"),
        "source_sha":source_sha,
        "artifact_name":artifact.get("name"),
        "msix_sha256":package_sha,
        "slug":slug,
        "type":"app",
        "source_repository":handoff["source_repository"],
        "identity":identity
    }
    custody=verify_custody(expected,downloaded,fetch_json,fetch_bytes)
    if custody.get("status")!="CUSTODY_VERIFIED_ONLY":
        raise ValueError("SOURCE_ARTIFACT_CUSTODY_HOLD:"+str(custody.get("reason","UNKNOWN")))
    _write_once(downloaded/"github-custody.json",
                (json.dumps(custody,ensure_ascii=False,sort_keys=True)+"\n").encode("utf-8"))


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
            if repository==OWNER+"/AI-App-Factory":
                preview=json.loads((downloaded/"handoff.json").read_text(encoding="utf-8"))
                if isinstance(preview,dict) and preview.get("type")=="app" and preview.get("factory_head_sha") is not None:
                    _prepare_app_identity_return(downloaded,repository,run,artifact,source_sha)
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
