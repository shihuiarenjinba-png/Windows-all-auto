"""Worker status output must distinguish evidence return from product E2E."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import local_qa_evidence_worker as worker


class _Result:
    run_id = "20261116T000000Z-0000000000000000"
    status = "TEST_PASS"

    def __init__(self, run_directory: Path):
        self.run_directory = run_directory


class _Store:
    result: _Result

    def __init__(self, _root):
        pass

    def recover_interrupted(self):
        return []

    def execute(self, *_args, **_kwargs):
        return self.result

    def prune_verified(self, **_kwargs):
        return {"deleted_runs": 0, "freed_bytes": 0, "remaining_bytes": 0}


class WorkerStatusTests(unittest.TestCase):
    def test_evidence_return_success_never_claims_product_or_store_success(self):
        local_tmp = Path.cwd() / ".test-tmp"
        local_tmp.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=local_tmp) as name:
            root = Path(name)
            run = root / "run"
            run.mkdir()
            manifest = {
                "evidence_return_e2e_pass": True,
                "product_e2e_pass": False,
                "e2e_pass": False,
                "release_ready": False,
                "store_submission_allowed": False,
                "user_product_approval": False,
                "user_price_approval": False,
            }
            (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            _Store.result = _Result(run)
            job = {"unused": True}
            profile = {"command": ["trusted.exe"],
                       "allowed_executables": ["trusted.exe"], "cwd": str(root)}
            output = io.StringIO()
            with (patch.object(worker, "EvidenceStore", _Store),
                  patch.object(worker, "_load", side_effect=[job, profile]),
                  patch.object(worker, "GitHubContentsTransport", return_value=object()),
                  patch.object(worker, "process_retry_queue",
                               return_value={"verified": 1, "failed": 0,
                                             "deferred": 0, "locked": 0}),
                  redirect_stdout(output)):
                code = worker.main(["--state-root", str(root),
                                    "--job", str(root / "job.json"),
                                    "--profile", str(root / "profile.json")])
            value = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(value["evidence_return_e2e_pass"])
            for field in ("product_e2e_pass", "e2e_pass", "release_ready",
                          "store_submission_allowed", "user_product_approval",
                          "user_price_approval"):
                self.assertFalse(value[field])


if __name__ == "__main__":
    unittest.main()
