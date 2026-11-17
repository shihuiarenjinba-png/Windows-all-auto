"""Run a bound product GUI plan with trusted UIA and local-only screenshot evidence.

The screenshot is captured but intentionally NOT marked GitHub-shareable here.
A human must review it and run review_gui_screenshot.py with its exact SHA.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from all_auto.local_qa_evidence import EvidenceStore  # noqa: E402
from all_auto.product_qa_plan import (  # noqa: E402
    ProductQAPlanHold, load_bound_plan, verify_plan_for_job,
)
from all_auto.trusted_uia import UIA_ACTIONS  # noqa: E402


def product_event_log_collector(executable_name: str):
    if not executable_name or Path(executable_name).name != executable_name:
        raise ValueError("invalid product executable name")
    needle = executable_name.casefold()

    def collect(started: str, finished: str) -> str:
        query = (
            "*[System[TimeCreated[@SystemTime>='" + started +
            "' and @SystemTime<='" + finished + "']]]"
        )
        result = subprocess.run(
            ["wevtutil", "qe", "Application", "/q:" + query,
             "/f:RenderedXml", "/c:200", "/rd:true"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
        if result.returncode:
            raise OSError("wevtutil exit " + str(result.returncode))
        raw = result.stdout.strip()
        if not raw:
            return ""
        events = re.findall(
            r"<Event(?:\s[^>]*)?>.*?</Event>", raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not events:
            raise OSError("wevtutil returned malformed event XML")
        selected = [event for event in events if needle in event.casefold()]
        return "<Events>" + "".join(selected) + "</Events>" if selected else ""

    return collect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", required=True, type=Path)
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args(argv)

    job = json.loads(args.job.read_text(encoding="utf-8"))
    plan = load_bound_plan(args.plan)
    supported = {"ARTIFACT_HASH", "PROCESS_START"} | set(UIA_ACTIONS)
    try:
        capability = verify_plan_for_job(
            plan, job=job, artifact_path=args.artifact,
            package_path=args.package, supported_test_ids=supported,
        )
    except ProductQAPlanHold as exc:
        print(json.dumps({
            "status": "PRODUCT_QA_PLAN_HOLD", "reason": str(exc),
            "product_e2e_pass": False, "release_ready": False,
            "store_submission_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    if capability["status"] != "PRODUCT_QA_PLAN_READY":
        print(json.dumps({
            **capability, "product_e2e_pass": False,
            "release_ready": False, "store_submission_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2

    root = args.state_root.resolve()
    review = root / "privacy-review"
    review.mkdir(parents=True, exist_ok=True)
    request = re.sub(r"[^A-Za-z0-9._-]", "_", job["request_id"])
    action_log = review / (request + ".uia-actions.jsonl")
    screenshot = review / (request + ".png")
    action_log.unlink(missing_ok=True)
    screenshot.unlink(missing_ok=True)

    store = EvidenceStore(root)
    worker = Path(__file__).resolve().parent / "trusted_product_qa_worker.py"
    command = [
        sys.executable, str(worker),
        "--plan", str(args.plan.resolve()),
        "--artifact", str(args.artifact.resolve()),
        "--action-log", str(action_log),
        "--screenshot-output", str(screenshot),
        "--screenshot-root", str(review),
    ]

    def attach(run_id: str, _folder: Path) -> None:
        if action_log.is_file():
            for raw in action_log.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                item = json.loads(raw)
                store.record_ui_action(
                    run_id,
                    action=str(item.get("action", "")),
                    target=str(item.get("target", "")),
                    result=str(item.get("result", "")),
                    details=item.get("details") if isinstance(item.get("details"), dict) else {},
                )
        if screenshot.is_file():
            store.add_screenshot(
                run_id, screenshot, label="product-window-final",
                privacy_reviewed_shareable=False,
            )

    result = store.execute(
        job, command, cwd=Path(__file__).resolve().parents[1],
        timeout_seconds=args.timeout_seconds,
        expected={"exit_code": 0}, gui_test=True,
        event_log_collector=product_event_log_collector(args.artifact.name),
        evidence_callback=attach,
    )
    manifest = json.loads((result.run_directory / "manifest.json").read_text(encoding="utf-8"))
    screenshots = store._jsonl(result.run_directory / "screenshot-index.jsonl")
    print(json.dumps({
        "status": result.status,
        "run_id": result.run_id,
        "run_directory": str(result.run_directory),
        "collection": manifest.get("collection"),
        "collection_complete": manifest.get("collection_complete"),
        "screenshot_review_required": True,
        "screenshots": screenshots,
        "next_step": (
            "Review the local screenshot, then run review_gui_screenshot.py "
            "with its filename and exact sha256."
        ),
        "product_e2e_pass": False,
        "release_ready": False,
        "store_submission_allowed": False,
    }, ensure_ascii=False, indent=2))
    return 0 if result.status == "TEST_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
