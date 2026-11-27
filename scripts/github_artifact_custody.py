"""Independent GitHub Actions artifact custody gate. Does not certify signing or E2E."""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

from all_auto.lane_queue import relative_package_path
from urllib.parse import urlparse, urlsplit

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ARTIFACT_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
MAX_RESPONSE_BYTES = 320 * 1024 * 1024


def hold(reason):
    return {"status": "HOLD", "reason": reason, "e2e_pass": False}


def verify_custody(expected, local_bundle, fetch_json, fetch_bytes):
    """Verify GitHub run, artifact archive digest, original handoff and local bytes.

    Factory MSIX export artifacts contain exactly handoff.json + package.msix.
    A package-only archive is retained for the narrow legacy adapter. This gate
    never promotes a producer-supplied receipt to E2E PASS.
    """
    try:
        if not isinstance(expected, dict):
            return hold("EXPECTED_INVALID")
        repository = expected["repository"]
        owner, repo = repository.split("/")
        run_id, artifact_id = expected["run_id"], expected["artifact_id"]
        head = expected["source_sha"]
        name = expected["artifact_name"]
        digest = expected["msix_sha256"]
        if not all(type(v) is int and v > 0 for v in (run_id, artifact_id)):
            return hold("ARTIFACT_IDS_INVALID")
        if (not HEX40.fullmatch(head) or not HEX64.fullmatch(digest)
                or not isinstance(name, str) or not name):
            return hold("PIN_INVALID")

        local = Path(local_bundle)
        if local.is_symlink():
            return hold("LOCAL_BUNDLE_LINKED")
        bundle_mode = local.is_dir()
        if bundle_mode:
            children = list(local.iterdir())
            names = {p.name for p in children}
            allowed = {"handoff.json", "package.msix", "transport_receipt.json", "approved-identity.json"}
            if (any(p.is_symlink() or not p.is_file() for p in children)
                    or not {"handoff.json", "package.msix"}.issubset(names)
                    or not names.issubset(allowed)):
                return hold("LOCAL_BUNDLE_CONTENT_INVALID")
            transport_path = local / "transport_receipt.json"
            identity_path = local / "approved-identity.json"
            if transport_path.exists() != identity_path.exists():
                return hold("LOCAL_APPROVED_IDENTITY_RECEIPTS_UNPAIRED")
            transport = None
            approved_identity = None
            if transport_path.exists():
                if (transport_path.stat().st_size > 32 * 1024
                        or identity_path.stat().st_size > 32 * 1024):
                    return hold("LOCAL_TRANSPORT_RECEIPT_INVALID")
                transport = json.loads(transport_path.read_text(encoding="utf-8"))
                approved_identity = json.loads(identity_path.read_text(encoding="utf-8"))
                if not isinstance(transport, dict) or not isinstance(approved_identity, dict):
                    return hold("LOCAL_TRANSPORT_RECEIPT_INVALID")
                identity_bytes = identity_path.read_bytes()
                identity_git_blob_sha = hashlib.sha1(
                    b"blob " + str(len(identity_bytes)).encode("ascii") + b"\0" + identity_bytes
                ).hexdigest()
                transport_identity = transport.get("identity")
                evidence = transport.get("evidence_url")
                parsed = urlparse(evidence) if isinstance(evidence, str) else None
                store_id = transport.get("store_id")
                expected_identity_path = "/products/" + store_id + "/identity" if isinstance(store_id, str) else ""
                source_repository = transport.get("source_repository")
                expected_identity_repository = (
                    source_repository.removeprefix("https://github.com/")
                    if isinstance(source_repository, str) else None
                )
                if (transport.get("status") != "SOURCE_BOUND_VERSION_APPROVED"
                        or transport.get("approval_source") != "partner_center"
                        or transport.get("source_sha") != head
                        or transport.get("expected_head_sha") != head
                        or transport.get("factory_head_sha") != head
                        or transport.get("package_sha256") != digest
                        or transport.get("package_version_gate") != "PASS"
                        or transport.get("operator_verified") is not True
                        or transport.get("store_submission_allowed") is not False
                        or transport.get("certification_allowed") is not False
                        or transport.get("publish_allowed") is not False
                        or not isinstance(transport_identity, dict)
                        or transport.get("package_version") != transport_identity.get("version")
                        or transport.get("approved_identity_file_sha") != identity_git_blob_sha
                        or not isinstance(transport.get("verified_by"), str)
                        or not 3 <= len(transport.get("verified_by")) <= 100
                        or parsed is None or parsed.scheme != "https"
                        or parsed.hostname not in ("partner.microsoft.com", "partnercenter.microsoft.com")
                        or parsed.username or parsed.password or parsed.fragment
                        or not expected_identity_path
                        or expected_identity_path.casefold() not in parsed.path.casefold()
                        or approved_identity.get("reviewed") is not True
                        or approved_identity.get("source") != "partner_center"
                        or approved_identity.get("request_id") != transport.get("request_id")
                        or approved_identity.get("product_type") != "APP"
                        or approved_identity.get("source_factory") != "AI-App-Factory"
                        or approved_identity.get("source_repository") != expected_identity_repository
                        or approved_identity.get("source_branch") != transport.get("source_branch")
                        or approved_identity.get("source_sha") != head
                        or approved_identity.get("expected_head_sha") != head
                        or approved_identity.get("store_id") != store_id
                        or approved_identity.get("name") != transport_identity.get("name")
                        or approved_identity.get("publisher") != transport_identity.get("publisher")
                        or approved_identity.get("version") != transport.get("package_version")
                        or approved_identity.get("package_version_gate") != "PASS"
                        or approved_identity.get("operator_verified") is not True
                        or approved_identity.get("verified_by") != transport.get("verified_by")
                        or approved_identity.get("evidence_url") != evidence):
                    return hold("LOCAL_APPROVED_IDENTITY_BINDING_INVALID")
            local_handoff = (local / "handoff.json").read_bytes()
            local_path = local / "package.msix"
        else:
            local_path = local
            local_handoff = None
        if not local_path.is_file() or local_path.suffix.lower() != ".msix":
            return hold("LOCAL_MSIX_MISSING")

        base = "https://api.github.com/repos/{}/{}/actions".format(owner, repo)
        run = fetch_json(base + "/runs/" + str(run_id))
        artifact = fetch_json(base + "/artifacts/" + str(artifact_id))
        if (run.get("head_sha") != head or run.get("status") != "completed"
                or run.get("conclusion") != "success"):
            return hold("RUN_HEAD_OR_STATUS_MISMATCH")
        if (artifact.get("workflow_run", {}).get("id") != run_id
                or artifact.get("workflow_run", {}).get("head_sha") != head):
            return hold("ARTIFACT_RUN_MISMATCH")
        if (artifact.get("id") != artifact_id or artifact.get("name") != name
                or artifact.get("expired") is not False):
            return hold("ARTIFACT_ID_NAME_OR_EXPIRY_MISMATCH")

        archive = fetch_bytes(base + "/artifacts/" + str(artifact_id) + "/zip")
        archive_sha = hashlib.sha256(archive).hexdigest()
        api_digest = artifact.get("digest")
        match = ARTIFACT_DIGEST.fullmatch(api_digest) if isinstance(api_digest, str) else None
        if not match:
            return hold("ARTIFACT_ARCHIVE_DIGEST_MISSING")
        if match.group(1) != archive_sha:
            return hold("ARTIFACT_ARCHIVE_DIGEST_MISMATCH")

        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            members = z.infolist()
            names = [m.filename.replace("\\", "/") for m in members]
            if (any(m.is_dir() for m in members)
                    or len(names) != len(set(names))
                    or len([n.casefold() for n in names]) != len(set(n.casefold() for n in names))
                    or z.testzip() is not None):
                return hold("ARTIFACT_CORRUPT_OR_AMBIGUOUS")
            if bundle_mode:
                if set(names) != {"handoff.json", "package.msix"}:
                    return hold("ARTIFACT_BUNDLE_CONTENT_INVALID")
                artifact_handoff = z.read("handoff.json")
                artifact_msix = z.read("package.msix")
                if artifact_handoff != local_handoff:
                    return hold("HANDOFF_BYTES_DIFFER")
                handoff = json.loads(artifact_handoff.decode("utf-8"))
                if (not isinstance(handoff, dict)
                        or handoff.get("schema_version") != 1
                        or handoff.get("package") != "package.msix"
                        or handoff.get("status") != "QA_UNSIGNED"
                        or handoff.get("source_sha") != head
                        or handoff.get("package_sha256") != digest
                        or handoff.get("package_bytes") != len(artifact_msix)
                        or not isinstance(handoff.get("identity"), dict)):
                    return hold("HANDOFF_PROVENANCE_MISMATCH")
                for key in ("slug", "type", "source_repository", "identity"):
                    if key in expected and handoff.get(key) != expected[key]:
                        return hold("HANDOFF_EXPECTED_MISMATCH_" + key)
                if transport is not None:
                    for key in ("source_repository", "request_id", "product_type", "source_factory",
                                "source_branch", "expected_head_sha", "factory_head_sha", "store_id",
                                "display_name", "prebuilt_exe_sha256", "identity"):
                        if handoff.get(key) != transport.get(key):
                            return hold("LOCAL_TRANSPORT_HANDOFF_MISMATCH")
                    if (transport.get("source_sha") != handoff.get("source_sha")
                            or transport.get("package_sha256") != handoff.get("package_sha256")
                            or transport.get("package_bytes") != len(artifact_msix)):
                        return hold("LOCAL_TRANSPORT_HANDOFF_MISMATCH")
            else:
                if len(members) != 1 or members[0].is_dir() or not names[0].lower().endswith(".msix"):
                    return hold("ARTIFACT_CONTENT_INVALID")
                artifact_msix = z.read(members[0])

        local_bytes = local_path.read_bytes()
        if (hashlib.sha256(artifact_msix).hexdigest() != digest
                or hashlib.sha256(local_bytes).hexdigest() != digest):
            return hold("INDEPENDENT_BYTES_MISMATCH")
        if artifact_msix != local_bytes:
            return hold("LOCAL_ARTIFACT_BYTES_DIFFER")
        return {
            "status": "CUSTODY_VERIFIED_ONLY", "e2e_pass": False,
            "msix_sha256": digest, "archive_sha256": archive_sha,
            "run_id": run_id, "artifact_id": artifact_id,
            "artifact_name": name, "repository": repository, "source_sha": head,
            "signature": "NOT_VERIFIED", "checker": "NOT_VERIFIED", "gui": "NOT_VERIFIED",
        }
    except (KeyError, AttributeError, TypeError, ValueError, OSError,
            zipfile.BadZipFile, RuntimeError, UnicodeDecodeError, json.JSONDecodeError):
        return hold("EVIDENCE_UNAVAILABLE_OR_INVALID")


def verify_queue_artifact_custody(expected, local_artifact, fetch_json, fetch_bytes):
    """Verify a republished Windows QA queue artifact and its extracted local bytes.

    This is separate from verify_custody(), which verifies a single Factory
    handoff bundle. It proves archive custody only; it never proves product E2E.
    """
    try:
        if not isinstance(expected, dict):
            return hold("EXPECTED_INVALID")
        repository = expected["repository"]
        if not isinstance(repository, str) or repository.count("/") != 1:
            return hold("REPOSITORY_INVALID")
        owner, repo = repository.split("/")
        run_id = expected["run_id"]
        artifact_id = expected["artifact_id"]
        head = expected["run_head_sha"]
        name = expected["artifact_name"]
        if not all(type(v) is int and v > 0 for v in (run_id, artifact_id)):
            return hold("ARTIFACT_IDS_INVALID")
        if (not HEX40.fullmatch(head) or not isinstance(name, str)
                or not name.startswith("verified-msix-local-qa-")):
            return hold("PIN_INVALID")

        local = Path(local_artifact)
        if local.is_symlink() or not local.is_dir():
            return hold("LOCAL_ARTIFACT_MISSING")
        root_items = list(local.iterdir())
        if (any(p.is_symlink() for p in root_items)
                or {p.name for p in root_items} != {"queue.json", "packages"}):
            return hold("LOCAL_QUEUE_CONTENT_INVALID")
        queue_path = local / "queue.json"
        package_root = local / "packages"
        if (queue_path.is_symlink() or not queue_path.is_file()
                or queue_path.stat().st_size > 1024 * 1024
                or package_root.is_symlink() or not package_root.is_dir()):
            return hold("LOCAL_QUEUE_CONTENT_INVALID")
        queue_bytes = queue_path.read_bytes()
        queue = json.loads(queue_bytes.decode("utf-8"))
        items = queue.get("items") if isinstance(queue, dict) else None
        if not isinstance(items, list) or not 1 <= len(items) <= 20:
            return hold("QUEUE_ITEMS_INVALID")

        base = "https://api.github.com/repos/{}/{}/actions".format(owner, repo)
        run = fetch_json(base + "/runs/" + str(run_id))
        artifact = fetch_json(base + "/artifacts/" + str(artifact_id))
        if (run.get("name") != "Factory MSIX intake and local QA handoff"
                or run.get("path") != ".github/workflows/factory-msix-intake.yml"
                or run.get("status") != "completed"
                or run.get("conclusion") != "success"
                or run.get("head_sha") != head
                or run.get("event") not in ("schedule", "workflow_dispatch", "push")):
            return hold("RUN_HEAD_OR_STATUS_MISMATCH")
        if (run.get("head_repository", {}).get("full_name") != repository
                or not isinstance(run.get("head_branch"), str)
                or not run["head_branch"].startswith("codex/")):
            return hold("RUN_REPOSITORY_OR_BRANCH_MISMATCH")
        workflow = artifact.get("workflow_run", {})
        if (artifact.get("id") != artifact_id or artifact.get("name") != name
                or artifact.get("expired") is not False
                or workflow.get("id") != run_id
                or workflow.get("head_sha") != head):
            return hold("ARTIFACT_RUN_OR_IDENTITY_MISMATCH")

        archive = fetch_bytes(base + "/artifacts/" + str(artifact_id) + "/zip")
        if not isinstance(archive, (bytes, bytearray)) or len(archive) > MAX_RESPONSE_BYTES:
            return hold("ARTIFACT_ARCHIVE_UNAVAILABLE_OR_OVERSIZED")
        archive_sha = hashlib.sha256(archive).hexdigest()
        api_digest = artifact.get("digest")
        match = ARTIFACT_DIGEST.fullmatch(api_digest) if isinstance(api_digest, str) else None
        if not match:
            return hold("ARTIFACT_ARCHIVE_DIGEST_MISSING")
        if match.group(1) != archive_sha:
            return hold("ARTIFACT_ARCHIVE_DIGEST_MISMATCH")

        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            infos = z.infolist()
            all_names = []
            files = {}
            for info in infos:
                raw_name = info.filename
                if not isinstance(raw_name, str) or not raw_name or "\\" in raw_name:
                    return hold("ARTIFACT_PATH_INVALID")
                normalized = raw_name[:-1] if info.is_dir() else raw_name
                parts = normalized.split("/")
                if (normalized.startswith("/")
                        or any(part in ("", ".", "..") for part in parts)
                        or ":" in parts[0]):
                    return hold("ARTIFACT_PATH_INVALID")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    return hold("ARTIFACT_SYMLINK_REJECTED")
                folded = normalized.casefold()
                if folded in all_names:
                    return hold("ARTIFACT_DUPLICATE_PATH")
                all_names.append(folded)
                if not info.is_dir():
                    files[normalized] = info
            if z.testzip() is not None:
                return hold("ARTIFACT_CORRUPT")
            if "queue.json" not in files or z.read("queue.json") != queue_bytes:
                return hold("QUEUE_BYTES_DIFFER")

            expected_files = {"queue.json"}
            package_records = []
            for item in items:
                if not isinstance(item, dict):
                    return hold("QUEUE_ITEM_INVALID")
                folder = relative_package_path(item)
                local_folder = package_root / folder
                if local_folder.is_symlink() or not local_folder.is_dir():
                    return hold("LOCAL_PACKAGE_BUNDLE_MISSING")
                children = list(local_folder.iterdir())
                child_names = {p.name for p in children}
                receipt_names = {"transport_receipt.json", "github-custody.json", "approved-identity.json"}
                present_receipts = child_names & receipt_names
                if (any(p.is_symlink() or not p.is_file() for p in children)
                        or not {"handoff.json", "package.msix"}.issubset(child_names)
                        or not child_names.issubset({"handoff.json", "package.msix"} | receipt_names)
                        or (present_receipts and present_receipts != receipt_names)):
                    return hold("LOCAL_PACKAGE_BUNDLE_INVALID")
                local_package_sha = None
                local_package_bytes = None
                for child in children:
                    if child.name == "handoff.json" and child.stat().st_size > 32 * 1024:
                        return hold("HANDOFF_METADATA_OVERSIZED")
                    if child.name == "package.msix" and child.stat().st_size > 300 * 1024 * 1024:
                        return hold("LOCAL_MSIX_OVERSIZED")
                    if child.name == "transport_receipt.json" and child.stat().st_size > 32 * 1024:
                        return hold("TRANSPORT_RECEIPT_OVERSIZED")
                    if child.name == "github-custody.json" and child.stat().st_size > 16 * 1024:
                        return hold("CUSTODY_RECEIPT_OVERSIZED")
                    if child.name == "approved-identity.json" and child.stat().st_size > 32 * 1024:
                        return hold("APPROVED_IDENTITY_OVERSIZED")
                    archive_name = "packages/{}/{}".format(folder, child.name)
                    if archive_name not in files:
                        return hold("ARTIFACT_PACKAGE_FILE_MISSING")
                    local_bytes = child.read_bytes()
                    if z.read(archive_name) != local_bytes:
                        return hold("LOCAL_ARTIFACT_BYTES_DIFFER")
                    expected_files.add(archive_name)
                    if child.name == "package.msix":
                        local_package_bytes = local_bytes
                        local_package_sha = hashlib.sha256(local_bytes).hexdigest()
                if local_package_bytes is None:
                    return hold("LOCAL_MSIX_MISSING")
                package_records.append({
                    "slug": item.get("slug"),
                    "request_id": item.get("request_id"),
                    "source_sha": item.get("source_sha"),
                    "package_sha256": local_package_sha,
                    "package_bytes": len(local_package_bytes),
                    "local_sha256": local_package_sha,
                })
            if set(files) != expected_files:
                return hold("ARTIFACT_EXTRA_OR_MISSING_FILES")

        return {
            "status": "CUSTODY_VERIFIED_ONLY",
            "e2e_pass": False,
            "repository": repository,
            "run_id": run_id,
            "artifact_id": artifact_id,
            "artifact_name": name,
            "run_head_sha": head,
            "archive_sha256": archive_sha,
            "queue_sha256": hashlib.sha256(queue_bytes).hexdigest(),
            "packages": package_records,
            "signature": "NOT_VERIFIED",
            "checker": "NOT_VERIFIED",
            "gui": "NOT_VERIFIED",
        }
    except (KeyError, AttributeError, TypeError, ValueError, OSError,
            zipfile.BadZipFile, RuntimeError, UnicodeDecodeError, json.JSONDecodeError):
        return hold("EVIDENCE_UNAVAILABLE_OR_INVALID")

class _SafeCrossOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow HTTPS artifact redirects without forwarding GitHub credentials cross-origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urlsplit(req.full_url)
        new = urlsplit(newurl)
        if (new.scheme != "https" or not new.hostname
                or new.username or new.password):
            return None
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None

        def origin(parts):
            return (parts.scheme.lower(), parts.hostname.lower(),
                    parts.port or 443)

        if origin(old) != origin(new):
            for name in ("Authorization", "Proxy-Authorization", "Cookie"):
                redirected.remove_header(name)
                for mapping in (redirected.headers, redirected.unredirected_hdrs):
                    for key in list(mapping):
                        if key.lower() == name.lower():
                            mapping.pop(key, None)
        return redirected

def github_clients(token):
    """Real API transport; never put token in evidence or logs."""
    if not token:
        raise ValueError("Missing GitHub token")
    opener = urllib.request.build_opener(_SafeCrossOriginRedirectHandler())

    def request(url):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "api.github.com"
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise ValueError("Unexpected API URL")
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "windows-e2e-custody-gate"})
        with opener.open(req, timeout=30) as response:
            length = response.headers.get("Content-Length")
            if length is not None:
                try:
                    if int(length) > MAX_RESPONSE_BYTES:
                        raise ValueError("GitHub response exceeds custody size limit")
                except ValueError as exc:
                    if str(exc).startswith("GitHub response"):
                        raise
                    raise ValueError("Invalid GitHub response length") from exc
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                raise ValueError("GitHub response exceeds custody size limit")
            return data

    return lambda url: json.loads(request(url)), request

def _read_expected(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024:
        raise ValueError("EXPECTED_METADATA_UNAVAILABLE")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("EXPECTED_METADATA_INVALID")
    return data


def _write_receipt_once(path: Path, data: dict) -> None:
    if path.is_symlink() or path.exists():
        raise ValueError("RECEIPT_EXISTS_OR_LINKED")
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ValueError("RECEIPT_PARENT_UNAVAILABLE")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(path), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify GitHub Actions artifact archive bytes against a local MSIX; never asserts product E2E."
    )
    parser.add_argument("--expected", required=True, type=Path,
                        help="JSON with repository, run_id, artifact_id, source_sha, artifact_name and msix_sha256")
    parser.add_argument("--local-bundle", required=True, type=Path,
                        help="Downloaded handoff bundle directory or exact local .msix file")
    parser.add_argument("--output", required=True, type=Path,
                        help="New receipt path; for a bundle directory use github-custody.json inside that directory")
    args = parser.parse_args(argv)
    try:
        expected = _read_expected(args.expected)
        if args.output.is_symlink() or args.output.exists():
            raise ValueError("RECEIPT_EXISTS_OR_LINKED")
        if args.output.parent.is_symlink() or not args.output.parent.is_dir():
            raise ValueError("RECEIPT_PARENT_UNAVAILABLE")
        if args.local_bundle.is_dir():
            if (args.output.name != "github-custody.json"
                    or args.output.parent.resolve() != args.local_bundle.resolve()):
                raise ValueError("BUNDLE_RECEIPT_PATH_INVALID")
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN_REQUIRED")
        fetch_json, fetch_bytes = github_clients(token)
        result = verify_custody(expected, args.local_bundle, fetch_json, fetch_bytes)
        if result.get("status") != "CUSTODY_VERIFIED_ONLY":
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 2
        _write_receipt_once(args.output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except ValueError as exc:
        reason = str(exc)
        allowed = {
            "EXPECTED_METADATA_UNAVAILABLE", "EXPECTED_METADATA_INVALID",
            "RECEIPT_EXISTS_OR_LINKED", "RECEIPT_PARENT_UNAVAILABLE",
            "BUNDLE_RECEIPT_PATH_INVALID", "GITHUB_TOKEN_REQUIRED",
        }
        if reason not in allowed:
            reason = "CUSTODY_PREFLIGHT_INVALID"
        print(json.dumps({"status": "HOLD", "reason": reason, "e2e_pass": False}),
              file=sys.stderr)
        return 2
    except (OSError, TypeError, KeyError, json.JSONDecodeError):
        print(json.dumps({"status": "HOLD", "reason": "CUSTODY_PREFLIGHT_UNAVAILABLE", "e2e_pass": False}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
