"""Strict factory MSIX handoff contract. Never executes a received package."""
from __future__ import annotations
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

OWNER="shihuiarenjinba-png"
SLUG=re.compile(r"^[a-z][a-z0-9-]{3,39}$")
SHA40=re.compile(r"^[a-f0-9]{40}$")
SHA64=re.compile(r"^[a-f0-9]{64}$")
REPO=re.compile(r"^https://github\.com/shihuiarenjinba-png/(AI-App-Factory|AI-Game-Factory)$")
MAX_BYTES=300*1024*1024
REQUIRED={"handoff.json","package.msix"}

def fail(message):
    raise ValueError("HANDOFF_HOLD: "+message)

def inspect_msix(package:Path)->dict:
    if package.is_symlink() or not package.is_file() or not 0 < package.stat().st_size <= MAX_BYTES:
        fail("missing, linked or oversized MSIX")
    digest=sha256()
    with package.open("rb") as stream:
        for piece in iter(lambda:stream.read(1024*1024),b""):
            digest.update(piece)
    try:
        with zipfile.ZipFile(package) as z:
            members=z.infolist()
            if not 1 <= len(members) <= 2000:
                fail("unexpected MSIX entries")
            for info in members:
                name=info.filename.replace("\\","/")
                if (name.startswith("/") or ".." in name.split("/") or
                    info.file_size>MAX_BYTES or
                    (info.compress_size and info.file_size>100*info.compress_size)):
                    fail("unsafe MSIX ZIP entry")
            matches=[m for m in members if m.filename.lower()=="appxmanifest.xml"]
            if len(matches)!=1 or matches[0].file_size>2*1024*1024:
                fail("AppxManifest.xml missing or oversized")
            root=ET.fromstring(z.read(matches[0]))
    except (zipfile.BadZipFile,ET.ParseError,RuntimeError,KeyError,OSError) as exc:
        fail("not a readable MSIX: "+type(exc).__name__)
    identity=next((e for e in root.iter() if e.tag.endswith("}Identity") or e.tag=="Identity"),None)
    if identity is None: fail("MSIX package identity missing")
    return {"name":identity.attrib.get("Name"),"publisher":identity.attrib.get("Publisher"),
            "version":identity.attrib.get("Version"),"sha256":digest.hexdigest(),
            "bytes":package.stat().st_size}

def validate_bundle(directory:Path,expected_run_sha:str|None=None)->dict:
    directory=directory.resolve()
    if not directory.is_dir() or any(p.is_symlink() for p in directory.iterdir()):
        fail("bundle directory unavailable or linked files")
    if {p.name for p in directory.iterdir()}!=REQUIRED:
        fail("only handoff.json + package.msix permitted")
    meta_path=directory/"handoff.json"
    if meta_path.stat().st_size>32*1024: fail("oversized handoff metadata")
    data=json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or data.get("schema_version")!=1:
        fail("wrong schema")
    repo=data.get("source_repository")
    kind=data.get("type")
    if not isinstance(repo,str) or not REPO.fullmatch(repo):
        fail("untrusted source repository")
    expected_kind="app" if repo.endswith("/AI-App-Factory") else "game"
    if kind!=expected_kind: fail("source factory / product type mismatch")
    slug=data.get("slug")
    if not isinstance(slug,str) or not SLUG.fullmatch(slug):
        fail("invalid slug")
    sha=data.get("source_sha")
    if not isinstance(sha,str) or not SHA40.fullmatch(sha):
        fail("invalid source commit")
    if expected_run_sha is not None and sha!=expected_run_sha:
        fail("artifact provenance / Actions head SHA mismatch")
    if data.get("package")!="package.msix" or data.get("status")!="QA_UNSIGNED":
        fail("no approved package handoff state")
    file_hash=data.get("package_sha256")
    if not isinstance(file_hash,str) or not SHA64.fullmatch(file_hash):
        fail("invalid hash")
    details=inspect_msix(directory/"package.msix")
    if details["sha256"]!=file_hash or details["bytes"]!=data.get("package_bytes"):
        fail("MSIX bytes or hash mismatch")
    approved=data.get("identity")
    if not isinstance(approved,dict) or any(details.get(k)!=approved.get(k) or
        not isinstance(details.get(k),str) or not details.get(k)
        for k in ("name","publisher","version")):
        fail("MSIX embedded identity mismatch")
    return {
       "schema_version":1,"slug":slug,"type":kind,"source_repository":repo,
       "source_sha":sha,"package_sha256":file_hash,"package_bytes":details["bytes"],
       "identity":{k:details[k] for k in ("name","publisher","version")},
       "local_action":"WINDOWS_INSTALL_UI_QA_ONLY",
       "security_confirmed":False,"price_approved":False,
       "store_id":None,"submit_allowed":False
    }

def stage_bundle(source:Path,target:Path,expected_run_sha:str|None=None)->dict:
    info=validate_bundle(source,expected_run_sha)
    # Keep packages out of git and move only the one already independently checked.
    dest=target/(info["slug"]+"-"+info["package_sha256"][:12])
    if dest.exists():
        other=validate_bundle(dest,expected_run_sha)
        if other["package_sha256"]!=info["package_sha256"]:
            fail("existing target package changed")
        return info
    if target.is_symlink():fail("unsafe destination")
    target.mkdir(parents=True,exist_ok=True)
    dest.mkdir()
    try:
        shutil.copyfile(source/"handoff.json",dest/"handoff.json")
        shutil.copyfile(source/"package.msix",dest/"package.msix")
        validate_bundle(dest,expected_run_sha)
    except BaseException:
        shutil.rmtree(dest,ignore_errors=True)
        raise
    return info

def main(argv=None)->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",required=True,type=Path)
    ap.add_argument("--target",required=True,type=Path)
    ap.add_argument("--run-sha")
    args=ap.parse_args(argv)
    try:
        result=stage_bundle(args.source,args.target,args.run_sha)
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except (ValueError,OSError,TypeError,KeyError,json.JSONDecodeError) as e:
        print(str(e),file=sys.stderr)
        return 2

if __name__=="__main__":raise SystemExit(main())
