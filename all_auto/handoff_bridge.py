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
from .lane_queue import validate_immutable, relative_package_path, check_request_conflict
from .accounting_intake_gate import (require_accounting_package_attestation,
                                     reject_accounting_metadata_alias)

OWNER="shihuiarenjinba-png"
SLUG=re.compile(r"^[a-z][a-z0-9-]{3,39}$")
SHA40=re.compile(r"^[a-f0-9]{40}$")
SHA64=re.compile(r"^[a-f0-9]{64}$")
REPOSITORY_KINDS={
    "https://github.com/shihuiarenjinba-png/AI-App-Factory":"app",
    "https://github.com/shihuiarenjinba-png/AI-Game-Factory":"game",
    "shihuiarenjinba-png/3d-game-factory":"3d-game",
}
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
            # Windows package paths are case-insensitive. Duplicate payload
            # names (not only metadata names) make inspection ambiguous.
            normalized_names=[m.filename.replace("\\","/").casefold() for m in members]
            if len(normalized_names)!=len(set(normalized_names)):
                fail("duplicate MSIX ZIP member names")
            for info in members:
                name=info.filename.replace("\\","/")
                if (name.startswith("/") or ".." in name.split("/") or
                    info.file_size>MAX_BYTES or
                    (info.compress_size and info.file_size>100*info.compress_size)):
                    fail("unsafe MSIX ZIP entry")
            # A generic ZIP with a forged AppxManifest.xml is not an MSIX.
            # Require the package metadata parts produced by MakeAppx before
            # an artifact can enter the local Windows QA queue.
            required_parts={
                "appxmanifest.xml":"Package",
                "appxblockmap.xml":"BlockMap",
                "[content_types].xml":"Types",
            }
            parsed={}
            for name,expected_root in required_parts.items():
                matches=[m for m in members if m.filename.casefold()==name]
                if len(matches)!=1 or not 0<matches[0].file_size<=2*1024*1024:
                    fail("required MSIX metadata missing or invalid: "+name)
                document=ET.fromstring(z.read(matches[0]))
                if document.tag.rsplit("}",1)[-1]!=expected_root:
                    fail("invalid MSIX metadata root: "+name)
                parsed[name]=document
            root=parsed["appxmanifest.xml"]
            # New APP Identity-return handoffs bind the exact pre-Identity EXE
            # to the embedded MSIX payload, not just the outer ZIP checksum.
            applications=[e for e in root.iter()
                          if e.tag.rsplit("}",1)[-1]=="Application"]
            executable_sha256=None
            if len(applications)==1:
                exe=applications[0].attrib.get("Executable","").replace("\\","/")
                parts=exe.split("/")
                if (exe.lower().endswith(".exe") and
                        all(part and part not in (".","..") and
                            not part.endswith((" ",".")) and ":" not in part
                            for part in parts)):
                    payloads=[m for m in members if
                              m.filename.replace("\\","/").casefold()==exe.casefold()]
                    if len(payloads)==1 and not payloads[0].is_dir() and 0<payloads[0].file_size<=MAX_BYTES:
                        digest_exe=sha256()
                        with z.open(payloads[0]) as stream:
                            for chunk in iter(lambda:stream.read(1024*1024),b""):
                                digest_exe.update(chunk)
                        executable_sha256=digest_exe.hexdigest()
    except (zipfile.BadZipFile,ET.ParseError,RuntimeError,KeyError,OSError) as exc:
        fail("not a readable MSIX: "+type(exc).__name__)
    identity=next((e for e in root.iter() if e.tag.endswith("}Identity") or e.tag=="Identity"),None)
    if identity is None: fail("MSIX package identity missing")
    return {"name":identity.attrib.get("Name"),"publisher":identity.attrib.get("Publisher"),
            "version":identity.attrib.get("Version"),"sha256":digest.hexdigest(),
            "bytes":package.stat().st_size,
            "executable_sha256":executable_sha256}

def _unique_handoff_pairs(pairs):
    """Reject duplicate keys at every JSON depth, not just the outer object."""
    result = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate handoff JSON key")
        result[key] = value
    return result


def _reject_nonfinite_handoff(_value):
    fail("non-finite handoff JSON value")


def validate_bundle(directory:Path,expected_run_sha:str|None=None)->dict:
    if directory.is_symlink():fail("bundle directory is a symlink")
    directory=directory.resolve()
    if not directory.is_dir() or any(p.is_symlink() for p in directory.iterdir()):
        fail("bundle directory unavailable or linked files")
    if {p.name for p in directory.iterdir()}!=REQUIRED:
        fail("only handoff.json + package.msix permitted")
    meta_path=directory/"handoff.json"
    if meta_path.stat().st_size>32*1024: fail("oversized handoff metadata")
    data=json.loads(meta_path.read_text(encoding="utf-8"),
                    object_pairs_hook=_unique_handoff_pairs,
                    parse_constant=_reject_nonfinite_handoff)
    if type(data) is not dict or type(data.get("schema_version")) is not int or data["schema_version"]!=1:
        fail("wrong schema")
    repo=data.get("source_repository")
    kind=data.get("type")
    if not isinstance(repo,str) or repo not in REPOSITORY_KINDS:
        fail("untrusted source repository")
    # The 3D lane is distinct from the ordinary game lane all the way to QA.
    expected_kind=REPOSITORY_KINDS[repo]
    if kind!=expected_kind: fail("source factory / product type mismatch")
    slug=data.get("slug")
    if not isinstance(slug,str) or not SLUG.fullmatch(slug):
        fail("invalid slug")
    # Check the untrusted *full* handoff before normalization discards fields.
    # This also rejects cross-lane relabeling that preserves an accounting
    # Identity-return target or a recognizable accounting Factory branch.
    reject_accounting_metadata_alias(data)
    sha=data.get("source_sha")
    if not isinstance(sha,str) or not SHA40.fullmatch(sha):
        fail("invalid source commit")
    factory_head=data.get("factory_head_sha")
    if factory_head is not None:
        if kind not in ("app","game") or not isinstance(factory_head,str) or not SHA40.fullmatch(factory_head):
            fail("invalid APP Identity-return factory HEAD")
        if kind=="app":
            required={
                "expected_head_sha":sha,"product_type":"APP",
            "source_factory":"AI-App-Factory",
        }
            if any(data.get(key)!=value for key,value in required.items()):
                fail("APP Identity-return immutable contract mismatch")
        if kind=="app" and (not isinstance(data.get("source_branch"),str)
                or not re.fullmatch(r"codex/[A-Za-z0-9._/-]+",data["source_branch"])
                or ".." in data["source_branch"] or "//" in data["source_branch"]
                or not isinstance(data.get("request_id"),str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{3,127}",data["request_id"])
                or not isinstance(data.get("display_name"),str)
                or not 1<=len(data["display_name"])<=100
                or any(ord(c)<32 or ord(c)==127 for c in data["display_name"])
                or not isinstance(data.get("store_id"),str)
                or not re.fullmatch(r"[A-Za-z0-9]{8,32}",data["store_id"])
                or not isinstance(data.get("prebuilt_exe_sha256"),str)
                or not SHA64.fullmatch(data["prebuilt_exe_sha256"])):
            fail("APP Identity-return provenance fields missing")
    immutable=validate_immutable(data,kind)
    build_head=immutable.get("factory_build_head",factory_head or sha)
    if expected_run_sha is not None and build_head!=expected_run_sha:
        fail("artifact provenance / Actions head SHA mismatch")
    if data.get("package")!="package.msix" or data.get("status")!="QA_UNSIGNED":
        fail("no approved package handoff state")
    file_hash=data.get("package_sha256")
    if not isinstance(file_hash,str) or not SHA64.fullmatch(file_hash):
        fail("invalid hash")
    details=inspect_msix(directory/"package.msix")
    if details["sha256"]!=file_hash or details["bytes"]!=data.get("package_bytes"):
        fail("MSIX bytes or hash mismatch")
    if factory_head is not None and kind=="app" and details["executable_sha256"]!=data["prebuilt_exe_sha256"]:
        fail("APP pre-Identity EXE payload SHA mismatch")
    approved=data.get("identity")
    if not isinstance(approved,dict) or any(details.get(k)!=approved.get(k) or
        not isinstance(details.get(k),str) or not details.get(k)
        for k in ("name","publisher","version")):
        fail("MSIX embedded identity mismatch")
    result={
       "schema_version":1,"slug":slug,"type":kind,"source_repository":repo,
       "source_sha":sha,"package_sha256":file_hash,"package_bytes":details["bytes"],
       "identity":{k:details[k] for k in ("name","publisher","version")},
       "local_action":"WINDOWS_INSTALL_UI_QA_ONLY",
       "security_confirmed":False,"price_approved":False,
       "store_id":None,"submit_allowed":False
    }
    if factory_head is not None and kind=="app":
        result.update({
            "factory_head_sha":factory_head,"expected_head_sha":sha,
            "request_id":data["request_id"],"product_type":"APP",
            "source_factory":"AI-App-Factory",
            "source_branch":data["source_branch"],
            "display_name":data["display_name"],
            "prebuilt_exe_sha256":data["prebuilt_exe_sha256"],
            "claimed_store_id":data["store_id"],
        })
    result.update(immutable)
    return result

def stage_bundle(source:Path,target:Path,expected_run_sha:str|None=None,*,accounting_attestor=None)->dict:
    info=validate_bundle(source,expected_run_sha)
    # Enforce on every attempt, including idempotent replay, before touching QA state.
    # The normal bridge has no trusted accounting adapter and therefore HOLDS.
    require_accounting_package_attestation(info,attest=accounting_attestor)
    # A symlinked queue must never be accepted, including the idempotent
    # fast path when a matching package already exists behind the link.
    if target.is_symlink():fail("unsafe destination")
    # Keep packages out of git and move only the one already independently checked.
    check_request_conflict(target,info)
    dest=target/relative_package_path(info)
    if dest.parent.is_symlink():fail("unsafe local QA lane")
    if dest.exists():
        other=validate_bundle(dest,expected_run_sha)
        # A matching package hash does not establish matching provenance. Two
        # Factory lanes (or source commits) may produce identical MSIX bytes.
        # Never reuse the earlier receipt for a different source product.
        provenance_fields=(
            "source_repository", "source_sha", "slug", "type",
            "package_sha256", "package_bytes", "identity",
            "factory_head_sha", "expected_head_sha", "request_id",
            "product_type", "source_factory", "source_branch", "display_name",
            "prebuilt_exe_sha256", "claimed_store_id",
        )
        if any(other.get(key)!=info.get(key) for key in provenance_fields):
            fail("existing target package or provenance changed")
        return info
    target.mkdir(parents=True,exist_ok=True)
    dest.parent.mkdir(parents=True,exist_ok=True)
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
