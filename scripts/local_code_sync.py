"""Fetch immutable Factory product source snapshots for local Codex/QA use.

This worker never merges, pulls into an existing development checkout, runs product
code, installs packages, signs, submits, or performs CAS.  Each product is cloned
into a SHA-addressed managed snapshot after the remote branch HEAD is verified
against the pinned immutable source SHA.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

OWNER = "shihuiarenjinba-png"
MAX_ITEMS = 20
REPO_RE = re.compile(r"^" + re.escape(OWNER) + r"/[A-Za-z0-9_.-]+$")
BRANCH_RE = re.compile(r"^codex/[A-Za-z0-9._/-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


class SyncHold(RuntimeError):
    pass


def _unsafe_path(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except OSError:
        return True


def _run(*args: str, cwd: Path | None = None, timeout: int = 120) -> str:
    result = subprocess.run(
        list(args), cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, encoding="utf-8",
        timeout=timeout, check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git command failed").strip()
        raise SyncHold(detail[:220])
    if len(result.stdout) > 2_000_000:
        raise SyncHold("unexpectedly large git output")
    return result.stdout.strip()


def _normalize_job(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise SyncHold("invalid job")
    repository = raw.get("repository") or raw.get("source_repository")
    branch = raw.get("branch") or raw.get("source_branch")
    source_sha = raw.get("source_sha")
    slug = raw.get("slug")
    request_id = raw.get("request_id")
    if not isinstance(repository, str) or not REPO_RE.fullmatch(repository):
        raise SyncHold("repository is not allowlisted")
    if (not isinstance(branch, str) or not BRANCH_RE.fullmatch(branch)
            or any(part in {"", ".", ".."} for part in branch.split("/"))):
        raise SyncHold("unsafe source branch")
    if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha):
        raise SyncHold("invalid immutable source SHA")
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        raise SyncHold("invalid slug")
    # Every queued source snapshot must retain a nonempty, unambiguous job ID.
    # An optional ID lets a manually edited manifest bypass product correlation.
    if (not isinstance(request_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,179}", request_id)):
        raise SyncHold("invalid or missing request_id")
    return {
        "repository": repository,
        "branch": branch,
        "source_sha": source_sha,
        "slug": slug,
        "request_id": request_id,
    }


def _unique_json_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise SyncHold("duplicate manifest JSON key")
        result[key] = value
    return result


def load_jobs(path: Path) -> list[dict]:
    if _unsafe_path(path) or not path.is_file() or path.stat().st_size > 512_000:
        raise SyncHold("manifest missing, linked, or too large")
    try:
        data = json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=_unique_json_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SyncHold("invalid manifest JSON") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise SyncHold("unsupported manifest schema")
    raw = data.get("jobs")
    if raw is None:
        raw = data.get("items")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_ITEMS:
        raise SyncHold("manifest must contain 1..20 jobs/items")
    jobs = [_normalize_job(item) for item in raw]
    # Reject cross-product aliasing before any network access or snapshot writes.
    # A single request_id/slug/remote branch must never name two different jobs.
    for name, keys in (
        ("request_id", [j["request_id"] for j in jobs]),
        ("slug", [j["slug"] for j in jobs]),
        ("source branch", [(j["repository"], j["branch"]) for j in jobs]),
        ("source snapshot target",
         [(j["repository"], j["branch"], j["source_sha"], j["slug"]) for j in jobs]),
    ):
        if len(keys) != len(set(keys)):
            raise SyncHold("duplicate " + name + " in source sync manifest")
    return jobs


def _verify_remote_head(job: dict) -> None:
    """Fail closed if the current source branch no longer points to pinned SHA."""
    url = "https://github.com/" + job["repository"] + ".git"
    ref = "refs/heads/" + job["branch"]
    output = _run("git", "ls-remote", "--heads", url, ref, timeout=180)
    lines = output.splitlines()
    if len(lines) != 1:
        raise SyncHold("REMOTE_HEAD_CONFLICT: source branch missing or ambiguous")
    parts = lines[0].split()
    if len(parts) != 2 or parts[1] != ref or parts[0] != job["source_sha"]:
        raise SyncHold("REMOTE_HEAD_CONFLICT: source branch differs from pinned SHA")


def _verify_existing(target: Path, job: dict) -> dict:
    if _unsafe_path(target):
        raise SyncHold("existing snapshot path is linked/junction")
    if _unsafe_path(target / ".git") or not (target / ".git").is_dir():
        raise SyncHold("existing snapshot is not a safe managed git checkout")
    head = _run("git", "-C", str(target), "rev-parse", "HEAD")
    if head != job["source_sha"]:
        raise SyncHold("existing snapshot HEAD mismatch")
    status = _run("git", "-C", str(target), "status", "--porcelain")
    if status:
        raise SyncHold("existing immutable snapshot is dirty; refusing overwrite")
    origin = _run("git", "-C", str(target), "remote", "get-url", "origin")
    expected_origin = "https://github.com/" + job["repository"] + ".git"
    if origin != expected_origin:
        raise SyncHold("existing snapshot origin mismatch")
    _verify_remote_head(job)
    return {"status": "REUSED_EXACT_SNAPSHOT", "path": str(target)}


def sync_one(root: Path, job: dict) -> dict:
    repo_name = job["repository"].split("/", 1)[1]
    target = root / repo_name / job["source_sha"][:12]
    if target.exists():
        result = _verify_existing(target, job)
        return {**job, **result}

    parent = target.parent
    if _unsafe_path(root) or (parent.exists() and _unsafe_path(parent)):
        raise SyncHold("unsafe local code root")
    parent.mkdir(parents=True, exist_ok=True)

    temp = Path(tempfile.mkdtemp(prefix=".code-sync-", dir=parent))
    try:
        url = "https://github.com/" + job["repository"] + ".git"
        _run("git", "clone", "--no-checkout", "--filter=blob:none", url, str(temp), timeout=180)
        remote_ref = "refs/remotes/origin/" + job["branch"]
        _run(
            "git", "-C", str(temp), "fetch", "--no-tags", "--prune", "origin",
            "+refs/heads/" + job["branch"] + ":" + remote_ref,
            timeout=180,
        )
        observed = _run("git", "-C", str(temp), "rev-parse", remote_ref)
        if observed != job["source_sha"]:
            raise SyncHold(
                "REMOTE_HEAD_CONFLICT expected=" + job["source_sha"][:12]
                + " observed=" + observed[:12]
            )
        _run("git", "-C", str(temp), "checkout", "--detach", "--force", job["source_sha"])
        checked = _run("git", "-C", str(temp), "rev-parse", "HEAD")
        if checked != job["source_sha"]:
            raise SyncHold("checkout SHA mismatch")
        if _run("git", "-C", str(temp), "status", "--porcelain"):
            raise SyncHold("new snapshot unexpectedly dirty")
        os.replace(temp, target)
        return {
            **job,
            "status": "DOWNLOADED_EXACT_SNAPSHOT",
            "path": str(target),
        }
    finally:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)


def atomic_json(path: Path, value: dict) -> None:
    if path.exists() and _unsafe_path(path):
        raise SyncHold("receipt path is linked/junction")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".code-sync-receipt-", suffix=".json",
                                dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def sync_manifest(manifest: Path, root: Path, receipt: Path) -> dict:
    if root.exists() and _unsafe_path(root):
        raise SyncHold("local code root is linked/junction")
    root.mkdir(parents=True, exist_ok=True)
    jobs = load_jobs(manifest)
    products = [sync_one(root, job) for job in jobs]
    result = {
        "schema_version": 1,
        "status": "PASS",
        "products": products,
        "snapshots": len(products),
        "exact_sha_verified": True,
        "development_checkout_modified": False,
        "product_code_executed": False,
        "store_submission": False,
        "cas_applied": False,
    }
    atomic_json(receipt, result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = sync_manifest(args.manifest, args.root, args.receipt)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (SyncHold, OSError, subprocess.TimeoutExpired) as exc:
        result = {
            "schema_version": 1,
            "status": "HOLD",
            "reason": str(exc)[:240],
            "exact_sha_verified": False,
            "development_checkout_modified": False,
            "product_code_executed": False,
            "store_submission": False,
            "cas_applied": False,
        }
        try:
            atomic_json(args.receipt, result)
        except Exception:
            pass
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
