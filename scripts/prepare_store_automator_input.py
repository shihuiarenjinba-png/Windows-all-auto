from __future__ import annotations
import argparse, json
from pathlib import Path
from all_auto.store_product_handoff import (
    normalize_store_product_handoff, to_windows_automator_input
)

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--handoff",required=True,type=Path)
    p.add_argument("--package-path",required=True)
    p.add_argument("--images-dir",required=True)
    p.add_argument("--output",required=True,type=Path)
    p.add_argument("--allow-hold",action="store_true")
    a=p.parse_args()
    raw=json.loads(a.handoff.read_text(encoding="utf-8"))
    n=normalize_store_product_handoff(raw)
    if not n["ready_for_automator_draft"] and not a.allow_hold:
        print(json.dumps({"status":"HOLD","missing":n["missing_for_draft"]},ensure_ascii=False,indent=2))
        return 2
    automator=to_windows_automator_input(n,package_path=a.package_path,images_dir=a.images_dir)
    payload={
        "schema_version":"windows-all-auto/store-automator-input-1",
        "status":"READY_FOR_AUTOMATOR_DRAFT" if n["ready_for_automator_draft"] else "HOLD",
        "missing":n["missing_for_draft"],
        "handoff":n,
        "windows_automator_input":automator,
        "certification_submit_approved":False,
        "publish_approved":False,
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":payload["status"],"output":str(a.output),"missing":payload["missing"]},ensure_ascii=False))
    return 0 if n["ready_for_automator_draft"] else 2

if __name__=="__main__": raise SystemExit(main())
