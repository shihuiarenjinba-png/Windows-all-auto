"""Build common model prompts and score strict Windows QA analysis outputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .schemas import CLASSIFICATIONS, CONFIDENCES, OWNERS


BENCHMARK_KEYS = {"case_id", "classification", "recommended_owner",
                  "observed_excerpt", "missing_evidence", "confidence"}


def load_cases(cases_path: Path, expected_path: Path) -> tuple[list[dict], dict[str, dict]]:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    expected_list = json.loads(expected_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not 20 <= len(cases) <= 50:
        raise ValueError("benchmark requires 20-50 cases")
    expected = {item["id"]: item for item in expected_list}
    if len(expected) != len(cases) or {x["id"] for x in cases} != set(expected):
        raise ValueError("case/expected IDs differ")
    return cases, expected


def build_prompt(cases: list[dict]) -> str:
    return """You are being benchmarked as a bounded Windows QA log analyst.
Return JSON only: an array with exactly one object per input case, in the same
order. Each object must have exactly these fields:
case_id, classification, recommended_owner, observed_excerpt,
missing_evidence, confidence.
classification must use the supplied allowed values. recommended_owner must
use the supplied owners. observed_excerpt must be one exact substring of that
case's log, or an empty string if no safe observation is possible.
missing_evidence must be an array of strings. confidence must be LOW, MEDIUM,
or HIGH. Do not infer Identity, Version, PASS/FAIL changes, Store permission,
commands, or root causes not in the log. Use UNKNOWN when uncertain.

Allowed classifications:
""" + json.dumps(sorted(CLASSIFICATIONS)) + """

Allowed owners:
""" + json.dumps(sorted(OWNERS)) + """

Cases:
""" + json.dumps(cases, ensure_ascii=False, sort_keys=True)


def _parse_array(path: Path) -> tuple[list[Any], bool]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return (value if isinstance(value, list) else []), isinstance(value, list)
    except (OSError, json.JSONDecodeError):
        return [], False


def score_model(cases: list[dict], expected: dict[str, dict], result_path: Path) -> dict[str, Any]:
    values, valid_top = _parse_array(result_path)
    by_id = {item.get("case_id"): item for item in values if isinstance(item, dict)}
    valid = classification = owner = critical_miss = hallucination = 0
    details = []
    for case in cases:
        exp = expected[case["id"]]
        raw = by_id.get(case["id"])
        errors = ["missing result"] if raw is None else []
        analysis = raw if isinstance(raw, dict) else None
        if isinstance(raw, dict):
            if set(raw) != BENCHMARK_KEYS:
                errors.append("fields differ")
            if raw.get("case_id") != case["id"]:
                errors.append("case_id mismatch")
            if raw.get("classification") not in CLASSIFICATIONS:
                errors.append("invalid classification")
            if raw.get("recommended_owner") not in OWNERS:
                errors.append("invalid owner")
            if raw.get("confidence") not in CONFIDENCES:
                errors.append("invalid confidence")
            missing = raw.get("missing_evidence")
            if not isinstance(missing, list) or any(not isinstance(x, str) for x in missing):
                errors.append("invalid missing_evidence")
            excerpt = raw.get("observed_excerpt")
            if not isinstance(excerpt, str):
                errors.append("invalid observed_excerpt")
            elif excerpt and excerpt not in case["log"]:
                errors.append("observed_excerpt not present in evidence")
        is_valid = not errors
        valid += int(is_valid)
        class_ok = bool(analysis and analysis.get("classification") == exp["classification"])
        owner_ok = bool(analysis and analysis.get("recommended_owner") == exp["owner"])
        classification += int(class_ok)
        owner += int(owner_ok)
        missed = bool(exp["critical"] and not class_ok)
        critical_miss += int(missed)
        hallucinated = any("not present in evidence" in error for error in errors)
        hallucination += int(hallucinated)
        details.append({"id": case["id"], "valid": is_valid,
                        "classification_correct": class_ok, "owner_correct": owner_ok,
                        "critical_miss": missed, "hallucination": hallucinated,
                        "errors": errors})
    total = len(cases)
    return {"cases": total, "valid_top_level_json": valid_top,
            "valid_json_rate": round(valid / total, 4),
            "classification_accuracy": round(classification / total, 4),
            "owner_routing_accuracy": round(owner / total, 4),
            "critical_miss": critical_miss, "hallucination": hallucination,
            "details": details}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prompt = sub.add_parser("prompt")
    prompt.add_argument("--cases", type=Path, required=True)
    prompt.add_argument("--expected", type=Path, required=True)
    prompt.add_argument("--out", type=Path, required=True)
    score = sub.add_parser("score")
    score.add_argument("--cases", type=Path, required=True)
    score.add_argument("--expected", type=Path, required=True)
    score.add_argument("--result", action="append", required=True,
                       help="model=path")
    score.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    cases, expected = load_cases(args.cases, args.expected)
    if args.command == "prompt":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(build_prompt(cases), encoding="utf-8")
        return 0
    report = {}
    for spec in args.result:
        model, path = spec.split("=", 1)
        report[model] = score_model(cases, expected, Path(path))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                   sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
