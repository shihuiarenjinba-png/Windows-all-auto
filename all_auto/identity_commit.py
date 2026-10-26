"""Send an authenticated Partner Center Identity back to the correct Factory.

Uses an atomic expectedHeadOid GitHub GraphQL mutation, not an AI-generated
target repository or an unguarded push. Defaults to dry-run.
Requires 'gh auth login' and contents:write permission to the chosen Factory.
"""
from __future__ import annotations
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import quote
from .identity_route import route_identity

MUTATION="""mutation($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input:$input) { commit { oid url } }
}"""

def gh_json(*args,body=None,allow_missing=False):
    command=["gh","api",*args]
    if body is not None:
        command.extend(["--input","-"])
    completed=subprocess.run(command,
        input=json.dumps(body) if body is not None else None,
        capture_output=True,text=True,encoding="utf-8",
        timeout=30,check=False)
    if completed.returncode!=0:
        if allow_missing and "HTTP 404" in completed.stderr:
            return None
        raise RuntimeError("GitHub authentication, scope, branch or conflict error")
    if len(completed.stdout)>256_000:
        raise RuntimeError("Oversized GitHub reply")
    return json.loads(completed.stdout)

def stage_and_commit(record:dict,apply:bool=False,api=gh_json)->dict:
    proposal=route_identity(record)
    if not apply:
        return {**proposal,"mode":"DRY_RUN_NO_WRITE"}
    repo=proposal["repository"]
    branch=proposal["branch"]
    sha=proposal["expected_head_sha"]
    base="repos/"+repo+"/"
    ref=api(base+"git/ref/heads/"+branch)
    if not isinstance(ref,dict) or ref.get("object",{}).get("sha")!=sha:
        raise ValueError("Factory HEAD changed; regenerate verified identity return input")
    slug=record["slug"]
    if record["type"]=="3d-game":
        # Godot prototypes are source-only and do not have the standard
        # App/Game Factory manifest.json yet. Verify real project bytes at
        # the pinned Factory branch instead of accepting an arbitrary slug.
        project=api(base+"contents/products/"+slug+"/project.godot?ref="+quote(branch,safe=""))
        if not isinstance(project,dict) or project.get("encoding")!="base64":
            raise ValueError("Source 3D Factory Godot project missing")
        raw=base64.b64decode(project["content"],validate=True)
        if len(raw)>128_000 or b"run/main_scene" not in raw:
            raise ValueError("Source 3D Factory Godot project invalid")
    else:
        manifest=api(base+"contents/products/"+slug+"/manifest.json?ref="+quote(branch,safe=""))
        if not isinstance(manifest,dict) or manifest.get("encoding")!="base64":
            raise ValueError("Source Factory product manifest not found")
        raw=base64.b64decode(manifest["content"],validate=True)
        if len(raw)>16_000:
            raise ValueError("Product manifest too large")
        product=json.loads(raw)
        if not isinstance(product,dict) or (product.get("slug")!=slug
              or product.get("kind")!=record["type"]):
            raise ValueError("Factory product identity/kind mismatch")
    # Never silently replace a previously associated product with another ID.
    existing=api(base+"contents/"+proposal["path"]+"?ref="+quote(branch,safe=""),
                 allow_missing=True)
    if existing is not None and existing.get("type")=="file":
        raise ValueError("Identity already exists; stop rather than overwrite")
    if existing is not None:
        raise ValueError("Invalid approved Identity destination")
    content=json.dumps(proposal["content"],indent=2,ensure_ascii=False)+"\n"
    body={"query":MUTATION,"variables":{"input":{
        "branch":{"repositoryNameWithOwner":repo,"branchName":branch},
        "message":{"headline":"store: return verified Partner Center identity for "+slug},
        "expectedHeadOid":sha,
        "fileChanges":{"additions":[{
            "path":proposal["path"],
            "contents":base64.b64encode(content.encode("utf-8")).decode("ascii")
        }]}
    }}}
    output=api("graphql",body=body)
    if output.get("errors"):
        raise ValueError("GitHub refused atomic identity return; inspect branch conflict")
    commit=output.get("data",{}).get("createCommitOnBranch",{}).get("commit")
    if not isinstance(commit,dict) or not isinstance(commit.get("oid"),str):
        raise ValueError("No confirmed GitHub commit was returned")
    return {**proposal,"applied":True,"committed_sha":commit["oid"],
        "commit_url":commit.get("url"),"mode":"VERIFIED_WORK_BRANCH_COMMIT"}

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True,type=Path)
    parser.add_argument("--apply",action="store_true",
        help="Commit verified Identity on the exact preapproved work branch")
    args=parser.parse_args(argv)
    try:
        if args.input.stat().st_size>32_768:raise ValueError("Identity return input too big")
        data=json.loads(args.input.read_text(encoding="utf-8"))
        result=stage_and_commit(data,apply=args.apply)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,subprocess.TimeoutExpired) as exc:
        print("IDENTITY_GITHUB_HOLD:",type(exc).__name__,str(exc)[:160],file=sys.stderr)
        return 2
if __name__=="__main__":raise SystemExit(main())
