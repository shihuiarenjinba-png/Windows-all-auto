"""Independent GitHub Actions artifact custody gate. Does not certify signing or E2E."""
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ARTIFACT_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


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
            if (any(p.is_symlink() or not p.is_file() for p in children)
                    or {p.name for p in children} != {"handoff.json", "package.msix"}):
                return hold("LOCAL_BUNDLE_CONTENT_INVALID")
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


def github_clients(token):
    """Real API transport; never put token in evidence or logs."""
    if not token:
        raise ValueError("Missing GitHub token")

    def request(url):
        if not url.startswith("https://api.github.com/"):
            raise ValueError("Unexpected API URL")
        req = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "windows-e2e-custody-gate"})
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read()

    return lambda url: json.loads(request(url)), request
