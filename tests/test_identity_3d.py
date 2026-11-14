"""3D official Identity cannot be written to an arbitrary or missing Godot source."""
import base64
import copy
import json
import unittest

from all_auto.identity_commit import stage_and_commit

RECORD={
 "schema_version":1, "type":"3d-game",
 "request_id":"3d-request-0001","product_type":"GAME_3D",
 "source_factory":"3d-game-factory",
 "source_repository":"shihuiarenjinba-png/3d-game-factory",
 "source_branch":"codex/3d-real-msix-build-path-20261027","source_sha":"c"*40,
 "slug":"experimental-3d-1",
 "expected_head_sha":"c"*40,
 "package_sha256":"e"*64,
 "package_family_name":"OkinawaDesktopTools.Experiment3D_abcdefghijklm",
 "package_sid":"S-1-15-2-1-2-3-4-5-6-7","signature_status":"NOTSIGNED",
 "operator_verified":True,"verified_by":"operator-confirmed",
 "official_evidence_url":"https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview",
 "identity":{
   "store_id":"9PTEST3D0001","name":"OkinawaDesktopTools.Experiment3D",
   "publisher":"CN=verified-publisher","version":"1.0.0.0",
   "package_family_name":"OkinawaDesktopTools.Experiment3D_abcdefghijklm",
   "package_sid":"S-1-15-2-1-2-3-4-5-6-7"
 }
}
class Test3DIdentityReturn(unittest.TestCase):
    def setUp(self):
        self.record=copy.deepcopy(RECORD)
        self.calls=[]
    def api(self,path,body=None,allow_missing=False):
        self.calls.append(path)
        if path.endswith("/git/ref/heads/codex/3d-real-msix-build-path-20261027"):
            return {"object":{"sha":"c"*40}}
        if "project.godot?ref=" in path:
            return {"encoding":"base64","content":base64.b64encode(
                b'[application]\nrun/main_scene="res://scenes/main.tscn"\n').decode()}
        if "approved-identity.json?ref=" in path:
            self.assertTrue(allow_missing)
            return None
        if path=="graphql":
            inp=body["variables"]["input"]
            self.assertEqual(inp["branch"]["repositoryNameWithOwner"],
                "shihuiarenjinba-png/3d-game-factory")
            self.assertEqual(inp["branch"]["branchName"],
                "codex/3d-real-msix-build-path-20261027")
            self.assertEqual(inp["expectedHeadOid"],"c"*40)
            addition=inp["fileChanges"]["additions"][0]
            self.assertEqual(addition["path"],
                "products/experimental-3d-1/store/approved-identity.json")
            meta=json.loads(base64.b64decode(addition["contents"]))
            self.assertEqual(meta["store_id"],RECORD["identity"]["store_id"])
            self.assertEqual(meta["verified_source_sha"],"c"*40)
            return {"data":{"createCommitOnBranch":{"commit":{
                "oid":"d"*40,"url":"https://github.com/example/commit"}}}}
        raise AssertionError("unexpected API request "+path)
    def test_3d_dry_run_never_calls_api(self):
        def abort(*args,**kwargs):raise AssertionError("no network permitted")
        r=stage_and_commit(self.record,False,api=abort)
        self.assertFalse(r["applied"])
        self.assertEqual(r["repository"],"shihuiarenjinba-png/3d-game-factory")
    def test_3d_verified_godot_project_can_return_identity(self):
        r=stage_and_commit(self.record,True,api=self.api)
        self.assertTrue(r["applied"])
        self.assertEqual(r["committed_sha"],"d"*40)
        self.assertEqual(len(self.calls),4)
    def test_3d_missing_project_must_not_commit(self):
        def missing(path,body=None,allow_missing=False):
            if "project.godot" in path:return None
            return self.api(path,body,allow_missing)
        with self.assertRaisesRegex(ValueError,"Godot project missing"):
            stage_and_commit(self.record,True,api=missing)
        self.assertNotIn("graphql",self.calls)
    def test_3d_project_without_main_scene_rejected(self):
        def wrong(path,body=None,allow_missing=False):
            if "project.godot" in path:
                return {"encoding":"base64","content":base64.b64encode(
                    b'[application]\n').decode()}
            return self.api(path,body,allow_missing)
        with self.assertRaisesRegex(ValueError,"Godot project invalid"):
            stage_and_commit(self.record,True,api=wrong)
        self.assertNotIn("graphql",self.calls)
    def test_3d_new_head_holds(self):
        def stale(path,body=None,allow_missing=False):
            return {"object":{"sha":"e"*40}}
        with self.assertRaisesRegex(ValueError,"HEAD changed"):
            stage_and_commit(self.record,True,api=stale)
    def test_3d_already_registered_cannot_overwrite(self):
        def existing(path,body=None,allow_missing=False):
            if "approved-identity.json" in path:return {"type":"file"}
            return self.api(path,body,allow_missing)
        with self.assertRaisesRegex(ValueError,"already exists"):
            stage_and_commit(self.record,True,api=existing)
    def test_never_route_3d_to_app_factory(self):
        result=stage_and_commit(self.record,False,api=lambda *a,**k:None)
        self.assertNotIn("AI-App-Factory",result["repository"])
        self.assertNotIn("AI-Game-Factory",result["repository"])

if __name__=="__main__":unittest.main()
