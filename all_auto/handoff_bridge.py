"""Strict factory MSIX handoff contract. Never executes a received package."""
from __future__ import annotations
import argparse
from hashlib import sha1, sha256
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import zipfile
from .lane_queue import validate_immutable, relative_package_path, check_request_conflict

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
OPTIONAL={"transport_receipt.json","github-custody.json","approved-identity.json"}

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

def validate_bundle(directory:Path,expected_run_sha:str|None=None)->dict:
    if directory.is_symlink():fail("bundle directory is a symlink")
    directory=directory.resolve()
    if not directory.is_dir() or any(p.is_symlink() or not p.is_file() for p in directory.iterdir()):
        fail("bundle directory unavailable or linked files")
    names={p.name for p in directory.iterdir()}
    if not REQUIRED.issubset(names) or not names.issubset(REQUIRED|OPTIONAL):
        fail("only handoff, package and bounded central receipts permitted")
    meta_path=directory/"handoff.json"
    if meta_path.stat().st_size>32*1024: fail("oversized handoff metadata")
    data=json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or data.get("schema_version")!=1:
        fail("wrong schema")
    repo=data.get("source_repository")
    kind=data.get("type")
    transport_receipt=None
    custody_receipt=None
    receipt_path=directory/"transport_receipt.json"
    custody_path=directory/"github-custody.json"
    approved_identity_path=directory/"approved-identity.json"
    receipt_exists=receipt_path.exists()
    custody_exists=custody_path.exists()
    approved_identity_exists=approved_identity_path.exists()
    if not (receipt_exists == custody_exists == approved_identity_exists):
        fail("central identity and custody receipts must be paired with approved-identity.json")
    if receipt_exists:
        if (kind!="app" or receipt_path.stat().st_size>32*1024
                or custody_path.stat().st_size>16*1024
                or approved_identity_path.stat().st_size>32*1024):
            fail("invalid or oversized APP transport receipts")
        transport_receipt=json.loads(receipt_path.read_text(encoding="utf-8"))
        custody_receipt=json.loads(custody_path.read_text(encoding="utf-8"))
        approved_identity=json.loads(approved_identity_path.read_text(encoding="utf-8"))
        if (not isinstance(transport_receipt,dict) or not isinstance(custody_receipt,dict)
                or not isinstance(approved_identity,dict)):
            fail("transport, custody and approved Identity receipts must be JSON objects")
        approved_identity_bytes=approved_identity_path.read_bytes()
        approved_identity_git_blob_sha=sha1(
            b"blob "+str(len(approved_identity_bytes)).encode("ascii")+b"\\0"+approved_identity_bytes
        ).hexdigest()
        source=data.get("source_sha")
        if (transport_receipt.get("schema_version")!=1
                or transport_receipt.get("status")!="SOURCE_BOUND_VERSION_APPROVED"
                or transport_receipt.get("source_sha")!=source
                or transport_receipt.get("expected_head_sha")!=source
                or transport_receipt.get("factory_head_sha")!=source
                or transport_receipt.get("source_repository")!=repo
                or transport_receipt.get("product_type")!="APP"
                or transport_receipt.get("source_factory")!="AI-App-Factory"
                or transport_receipt.get("package_sha256")!=data.get("package_sha256")
                or transport_receipt.get("package_bytes")!=data.get("package_bytes")
                or transport_receipt.get("identity")!=data.get("identity")
                or transport_receipt.get("approval_source")!="partner_center"
                or transport_receipt.get("package_version_gate")!="PASS"
                or transport_receipt.get("operator_verified") is not True
                or transport_receipt.get("store_submission_allowed") is not False
                or transport_receipt.get("certification_allowed") is not False
                or transport_receipt.get("publish_allowed") is not False):
            fail("source-bound Partner Center transport receipt mismatch")
        identity_file_sha=transport_receipt.get("approved_identity_file_sha")
        if not isinstance(identity_file_sha,str) or not SHA40.fullmatch(identity_file_sha):
            fail("approved Identity file SHA missing")
        if identity_file_sha!=approved_identity_git_blob_sha:
            fail("approved Identity file SHA mismatch")
        transport_identity=transport_receipt.get("identity")
        if (not isinstance(transport_identity,dict)
                or transport_receipt.get("package_version")!=transport_identity.get("version")):
            fail("source-bound Partner Center transport receipt mismatch")
        verifier=transport_receipt.get("verified_by")
        evidence=transport_receipt.get("evidence_url")
        parsed=urlparse(evidence) if isinstance(evidence,str) else None
        if (not isinstance(verifier,str) or not 3<=len(verifier)<=100
                or any(ord(c)<32 or ord(c)==127 for c in verifier)
                or parsed is None or parsed.scheme!="https"
                or parsed.hostname not in ("partner.microsoft.com","partnercenter.microsoft.com")
                or parsed.username or parsed.password or parsed.fragment):
            fail("official Partner Center evidence invalid")
        store_id=transport_receipt.get("store_id")
        expected_identity_path="/products/"+store_id+"/identity" if isinstance(store_id,str) else ""
        if not expected_identity_path or expected_identity_path.casefold() not in parsed.path.casefold():
            fail("official Partner Center evidence does not identify this Store product")
        for key in ("request_id","product_type","source_factory","source_branch",
                    "expected_head_sha","factory_head_sha","store_id","display_name",
                    "prebuilt_exe_sha256"):
            if key not in transport_receipt:
                fail("transport receipt missing immutable field: "+key)
            if key in data and data[key]!=transport_receipt[key]:
                fail("handoff/transport receipt conflict: "+key)
            data[key]=transport_receipt[key]
        if (not isinstance(data.get("prebuilt_exe_sha256"),str)
                or not SHA64.fullmatch(data["prebuilt_exe_sha256"])):
            fail("transport receipt executable SHA invalid")
        identity_data=data.get("identity")
        if not isinstance(identity_data,dict):
            fail("APP approved identity missing")
        approved_identity_expected={
            "reviewed":True,
            "source":"partner_center",
            "request_id":data.get("request_id"),
            "product_type":"APP",
            "source_factory":"AI-App-Factory",
            "source_repository":repo.removeprefix("https://github.com/"),
            "source_branch":data.get("source_branch"),
            "source_sha":source,
            "expected_head_sha":source,
            "store_id":data.get("store_id"),
            "name":identity_data.get("name"),
            "publisher":identity_data.get("publisher"),
            "version":identity_data.get("version"),
            "package_version_gate":"PASS",
            "operator_verified":True,
            "verified_by":verifier,
            "evidence_url":evidence,
        }
        if any(approved_identity.get(key)!=value for key,value in approved_identity_expected.items()):
            fail("approved Identity file does not bind current source/request/identity/version")
        if (custody_receipt.get("status")!="CUSTODY_VERIFIED_ONLY"
                or custody_receipt.get("e2e_pass") is not False
                or custody_receipt.get("source_sha")!=source
                or custody_receipt.get("msix_sha256")!=data.get("package_sha256")
                or type(custody_receipt.get("run_id")) is not int or custody_receipt["run_id"]<=0
                or type(custody_receipt.get("artifact_id")) is not int or custody_receipt["artifact_id"]<=0
                or custody_receipt.get("repository")!=repo.removeprefix("https://github.com/")
                or not isinstance(custody_receipt.get("archive_sha256"),str)
                or not SHA64.fullmatch(custody_receipt["archive_sha256"])):
            fail("independent GitHub artifact custody receipt invalid")
    if not isinstance(repo,str) or repo not in REPOSITORY_KINDS:
        fail("untrusted source repository")
    # The 3D lane is distinct from the ordinary game lane all the way to QA.
    expected_kind=REPOSITORY_KINDS[repo]
    if kind!=expected_kind: fail("source factory / product type mismatch")
    slug=data.get("slug")
    if not isinstance(slug,str) or not SLUG.fullmatch(slug):
        fail("invalid slug")
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
    if transport_receipt is not None:
        result["transport_receipt_sha256"]=sha256(receipt_path.read_bytes()).hexdigest()
        result["approved_identity_file_sha"]=approved_identity_git_blob_sha
        result["transport_receipt"]=transport_receipt
        result["github_artifact_custody"]=custody_receipt
    return result

def stage_bundle(source:Path,target:Path,expected_run_sha:str|None=None)->dict:
    info=validate_bundle(source,expected_run_sha)
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
            "transport_receipt_sha256", "approved_identity_file_sha",
            "transport_receipt", "github_artifact_custody",
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
        for receipt_name in ("transport_receipt.json","github-custody.json","approved-identity.json"):
            receipt_source=source/receipt_name
            if receipt_source.exists():
                shutil.copyfile(receipt_source,dest/receipt_name)
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
