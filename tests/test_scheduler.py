import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from all_auto.scheduler import compile_report, inspect, inventory, main

PRODUCT={"id":"testapp","type":"app","repository":"safe-repo","ref":"codex/release"}
SHA="a"*40

def good(route):
    if "/commits/" in route:return {"sha":SHA}
    return {"workflow_runs":[{"head_sha":SHA,"status":"completed",
            "conclusion":"success","event":"push","id":42}]}

class SchedulerTests(unittest.TestCase):
    def _list(self,products):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path=Path(self.tmp.name)/"inventory.json"
        path.write_text(json.dumps({"schema_version":1,"products":products}))
        return path

    def test_matching_sha_success_is_only_candidate(self):
        item=inspect(PRODUCT,good)
        self.assertEqual(item["status"],"WINDOWS_INSPECTION_CANDIDATE")
        self.assertEqual(item["store_submission"],"NOT_ATTEMPTED")
        self.assertEqual(item["ci_run_id"],42)

    def test_queue_approval_is_always_false(self):
        report,queue=compile_report([PRODUCT],good)
        self.assertEqual(report["submissions_made"],0)
        self.assertEqual(queue["total"],1)
        self.assertFalse(queue["tasks"][0]["store_submission_allowed"])
        self.assertFalse(queue["tasks"][0]["security_confirmed"])
        self.assertIsNone(queue["tasks"][0]["approved_identity"])
        self.assertIsNone(queue["tasks"][0]["approved_price"])

    def test_nonmatching_sha_is_hold(self):
        def fetch(route):
            if "/commits/" in route:return {"sha":SHA}
            return {"workflow_runs":[{"head_sha":"b"*40,"status":"completed",
                     "conclusion":"success","event":"push"}]}
        self.assertEqual(inspect(PRODUCT,fetch)["status"],"HOLD")

    def test_failed_job_does_not_pass(self):
        def fetch(route):
            if "/commits/" in route:return {"sha":SHA}
            return {"workflow_runs":[{"head_sha":SHA,"status":"completed",
                     "conclusion":"failure","event":"push"}]}
        self.assertEqual(inspect(PRODUCT,fetch)["status"],"HOLD")

    def test_source_not_found_is_hold(self):
        def fetch(route):raise HTTPError("https://api.github.com",404,"missing",None,None)
        self.assertEqual(inspect(PRODUCT,fetch)["reason"],"PRIVATE_REPO_OR_INVALID_REF")

    def test_invalid_commit_sha_is_hold(self):
        self.assertEqual(inspect(PRODUCT,lambda r:{"sha":"NOT_A_SHA"})["status"],"HOLD")

    def test_missing_runs_is_hold(self):
        def fetch(route):
            return {"sha":SHA} if "/commits/" in route else {}
        self.assertEqual(inspect(PRODUCT,fetch)["reason"],"NO_VERIFIABLE_CI_DATA")

    def test_reject_duplicate(self):
        with self.assertRaises(ValueError):inventory(self._list([PRODUCT,PRODUCT]))

    def test_reject_repo_path_injection(self):
        with self.assertRaises(ValueError):
            inventory(self._list([dict(PRODUCT,repository="../../unsafe")]))

    def test_reject_unapproved_security(self):
        with self.assertRaises(ValueError):
            inventory(self._list([dict(PRODUCT,security_confirmed=True)]))

    def test_reject_extra_product_types(self):
        with self.assertRaises(ValueError):
            inventory(self._list([dict(PRODUCT,type="unknown")]))

    def test_reject_more_than_100(self):
        with self.assertRaises(ValueError):
            inventory(self._list([dict(PRODUCT,id="app"+str(i)) for i in range(101)]))

    def test_offline_never_promotes_to_sale(self):
        file=self._list([PRODUCT])
        out=file.parent/"out"
        self.assertEqual(main(["--inventory",str(file),"--out",str(out),"--offline"]),0)
        report=json.loads((out/"report.json").read_text())
        self.assertEqual(report["counts"].get("WINDOWS_INSPECTION_CANDIDATE",0),0)
        queue=json.loads((out/"local-qa-queue.json").read_text())
        self.assertEqual(queue["total"],0)

    def test_both_app_game_accepted(self):
        rows=inventory(self._list([PRODUCT,dict(PRODUCT,id="testgame",type="game")]))
        self.assertEqual({r["type"] for r in rows},{"app","game"})

    def test_empty_inventory_rejected(self):
        with self.assertRaises(ValueError):inventory(self._list([]))

if __name__=="__main__":
    unittest.main()
