"""CLI preflight for a GitHub Factory QA-plan handoff bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from all_auto.product_qa_plan_intake import (
    ProductQAPlanIntakeError, load_handoff_bundle,
)


def main(argv=None) -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--bundle",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        accepted=load_handoff_bundle(args.bundle)
    except ProductQAPlanIntakeError as exc:
        print(json.dumps({"status":"QA_PLAN_HOLD","reason":str(exc)},ensure_ascii=False))
        return 2
    print(json.dumps({
        "status":"QA_PLAN_ACCEPTED",
        "source_repository":accepted.source_repository,
        "source_sha":accepted.source_sha,
        "source_branch":accepted.source_branch,
        "product_type":accepted.product_type,
        "slug":accepted.slug,
        "package_sha256":accepted.package_sha256,
        "executable_sha256":accepted.executable_sha256,
        "executable_path":accepted.executable_path,
        "application_id":accepted.application_id,
        "qa_plan_sha256":accepted.qa_plan_sha256,
        "steps":[{
            "step_id":step["step_id"],
            "test_id":step["test_id"],
            "required":step["required"],
            "requires":step["requires"],
            "parameters":step["parameters"],
            "on_fail":step["on_fail"],
        } for step in accepted.plan["steps"]],
        "allowed_diagnostics":accepted.plan["allowed_diagnostics"],
        "product_e2e_pass":False,
        "release_ready":False,
        "store_submission_allowed":False,
    },ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
