"""Independent GitHub Actions artifact custody gate. Does not certify MSIX signing or E2E."""
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

def hold(reason):
    return {"status": "HOLD", "reason": reason, "e2e_pass": False}

def verify_custody(expected, local_msix, fetch_json, fetch_bytes):
    """Verify run/artifact metadata from GitHub and actual downloaded bytes.
    fetch_json and fetch_bytes must be authenticated trusted API clients.
    No receipt supplied by the producer can self-certify VERIFIED.
    """
    try:
        if not isinstance(expected, dict):
            return hold("EXPECTED_INVALID")
        owner, repo = expected["repository"].split("/")
        run_id, artifact_id = expected["run_id"], expected["artifact_id"]
        head, name, digest = expected["source_sha"], expected["artifact_name"], expected["msix_sha256"]
        if not all(type(v) is int and v > 0 for v in (run_id, artifact_id)):
            return hold("ARTIFACT_IDS_INVALID")
        if not HEX40.fullmatch(head) or not HEX64.fullmatch(digest) or not name:
            return hold("PIN_INVALID")
        base = "https://api.github.com/repos/{}/{}/actions".format(owner, repo)
        run = fetch_json(base + "/runs/" + str(run_id))
        artifact = fetch_json(base + "/artifacts/" + str(artifact_id))
        if run.get("head_sha") != head or run.get("status") != "completed" or run.get("conclusion") != "success":
            return hold("RUN_HEAD_OR_STATUS_MISMATCH")
        if artifact.get("workflow_run", {}).get("id") != run_id or artifact.get("workflow_run", {}).get("head_sha") != head:
            return hold("ARTIFACT_RUN_MISMATCH")
        if artifact.get("id") != artifact_id or artifact.get("name") != name or artifact.get("expired") is not False:
            return hold("ARTIFACT_ID_NAME_OR_EXPIRY_MISMATCH")
        archive = fetch_bytes(base + "/artifacts/" + str(artifact_id) + "/zip")
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            members = z.infolist()
            if len(members) != 1 or members[0].is_dir() or not members[0].filename.lower().endswith(".msix"):
                return hold("ARTIFACT_CONTENT_INVALID")
            if z.testzip() is not None:
                return hold("ARTIFACT_CORRUPT")
            artifact_msix = z.read(members[0])
        local_path = Path(local_msix)
        if not local_path.is_file() or local_path.suffix.lower() != ".msix":
            return hold("LOCAL_MSIX_MISSING")
        local_bytes = local_path.read_bytes()
        if hashlib.sha256(artifact_msix).hexdigest() != digest or hashlib.sha256(local_bytes).hexdigest() != digest:
            return hold("INDEPENDENT_BYTES_MISMATCH")
        if artifact_msix != local_bytes:
            return hold("LOCAL_ARTIFACT_BYTES_DIFFER")
        return {"status": "CUSTODY_VERIFIED_ONLY", "e2e_pass": False,
                "msix_sha256": digest, "run_id": run_id, "artifact_id": artifact_id,
                "signature": "NOT_VERIFIED", "checker": "NOT_VERIFIED", "gui": "NOT_VERIFIED"}
    except (KeyError, AttributeError, TypeError, ValueError, OSError, zipfile.BadZipFile, RuntimeError):
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
