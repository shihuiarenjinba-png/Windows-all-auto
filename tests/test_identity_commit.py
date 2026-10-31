import base64
import copy
import json
import unittest
from all_auto.identity_commit import stage_and_commit

EXAMPLE={
    "schema_version":1,"type":"app","request_id":"app-request-0001",
    "product_type":"APP","source_factory":"AI-App-Factory",
    "source_repository":"shihuiarenjinba-png/AI-App-Factory",
    "source_branch":"codex/factory-autoloop-20261026","source_sha":"a"*40,
    "slug":"verified-tool","package_sha256":"c"*64,
    "package_family_name":"OkinawaDesktopTools.VerifiedTool_abcdefghijklm",
    "package_sid":"S-1-15-2-1-2-3-4-5-6-7","signature_status":"NOTSIGNED",
    "expected_head_sha":"a"*40,"operator_verified":True,
    "verified_by":"authenticated-operator",
    "official_evidence_url":"https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview",
    "identity":{
        "store_id":"9PTEST8F0RQA",
        "name":"OkinawaDesktopTools.VerifiedTool",
        "publisher":"CN=verified-publisher",
        "version":"1.0.0.0",
        "package_family_name":"OkinawaDesktopTools.VerifiedTool_abcdefghijklm",
        "package_sid":"S-1-15-2-1-2-3-4-5-6-7",
    }
}
class IdentityCommitTests(unittest.TestCase):
    def setUp(self):
        self.record=copy.deepcopy(EXAMPLE)
        self.queries=[]
    def api(self,path,body=None,allow_missing=False):
        self.queries.append((path,allow_missing))
        if path.endswith("/git/ref/heads/codex/factory-autoloop-20261026"):
            return {"object":{"sha":"a"*40}}
        if "manifest.json?ref=" in path:
            return {"encoding":"base64","content":base64.b64encode(
                b'{"slug":"verified-tool","kind":"app","entry":"main.py"}').decode()}
        if "approved-identity.json?ref=" in path:
            self.assertTrue(allow_missing)
            return None
        if path=="graphql":
            inp=body["variables"]["input"]
            self.assertEqual(inp["expectedHeadOid"],"a"*40)
            self.assertEqual(inp["branch"]["repositoryNameWithOwner"],
                "shihuiarenjinba-png/AI-App-Factory")
            addition=inp["fileChanges"]["additions"][0]
            self.assertEqual(addition["path"],"products/verified-tool/store/approved-identity.json")
            data=json.loads(base64.b64decode(addition["contents"]))
            self.assertEqual(data["store_id"],self.record["identity"]["store_id"])
            self.assertEqual(data["verified_source_sha"],"a"*40)
            self.assertEqual(data["package_sha256"],"c"*64)
            return {"data":{"createCommitOnBranch":{
                "commit":{"oid":"b"*40,"url":"https://github.com/example/commit"}}}}
        raise AssertionError("Unanticipated GitHub API request")

    def test_dry_run_never_calls_github(self):
        def no_network(*args,**kwargs):raise AssertionError("unexpected network access")
        result=stage_and_commit(self.record,False,api=no_network)
        self.assertFalse(result["applied"])
        self.assertEqual(result["mode"],"DRY_RUN_NO_WRITE")

    def test_authenticated_work_branch_cas_push(self):
        result=stage_and_commit(self.record,True,api=self.api)
        self.assertTrue(result["applied"])
        self.assertEqual(result["committed_sha"],"b"*40)
        self.assertEqual(len(self.queries),4)

    def test_changed_head_stops_before_write(self):
        def stale(path,body=None,allow_missing=False):
            return {"object":{"sha":"b"*40}}
        with self.assertRaisesRegex(ValueError,"HEAD changed"):
            stage_and_commit(self.record,True,api=stale)

    def test_existing_approved_identity_not_overwritten(self):
        def existing(path,body=None,allow_missing=False):
            if "approved-identity.json" in path:return {"type":"file"}
            return self.api(path,body,allow_missing)
        with self.assertRaisesRegex(ValueError,"already exists"):
            stage_and_commit(self.record,True,api=existing)

    def test_unverified_operator_never_calls_github(self):
        self.record["operator_verified"]=False
        def no_network(*args,**kwargs):raise AssertionError("network must be blocked")
        with self.assertRaisesRegex(ValueError,"operator verification"):
            stage_and_commit(self.record,True,api=no_network)

    def test_wrong_manifest_kind_never_pushes(self):
        def wrong(path,body=None,allow_missing=False):
            if "manifest.json" in path:
                return {"encoding":"base64","content":base64.b64encode(
                    b'{"slug":"verified-tool","kind":"game"}').decode()}
            return self.api(path,body,allow_missing)
        with self.assertRaisesRegex(ValueError,"mismatch"):
            stage_and_commit(self.record,True,api=wrong)

    def test_remote_graphql_conflict_does_not_claim_success(self):
        def conflicting(path,body=None,allow_missing=False):
            if path=="graphql":return {"errors":[{"message":"expectedHeadOid mismatch"}]}
            return self.api(path,body,allow_missing)
        with self.assertRaisesRegex(ValueError,"refused"):
            stage_and_commit(self.record,True,api=conflicting)

if __name__=="__main__":unittest.main()
