import copy
import json
import tempfile
from pathlib import Path
import unittest

from all_auto.identity_route import route_identity, main

EXAMPLE={
 "schema_version":1,
 "type":"app",
 "slug":"useful-tool",
 "expected_head_sha":"a"*40,
 "operator_verified":True,
 "verified_by":"authorized-operator",
 "official_evidence_url":"https://partner.microsoft.com/en-us/dashboard/apps-and-games/overview",
 "identity":{
    "store_id":"9PTEST4F0RQA",
    "name":"OkinawaDesktopTools.UsefulTool",
    "publisher":"CN=verified-publisher-subject",
    "version":"1.0.0.0",
 }
}
class IdentityRouteTests(unittest.TestCase):
    def setUp(self):self.record=copy.deepcopy(EXAMPLE)
    def test_app_routes_exact_repository(self):
        result=route_identity(self.record)
        self.assertEqual(result["repository"],"shihuiarenjinba-png/AI-App-Factory")
        self.assertEqual(result["branch"],"codex/factory-autoloop-20261026")
        self.assertEqual(result["path"],"products/useful-tool/store/approved-identity.json")
        self.assertFalse(result["applied"])
        self.assertFalse(result["store_submitted"])
        self.assertEqual(result["content"]["verified_source_sha"], self.record["expected_head_sha"])
    def test_game_routes_game_factory_not_app(self):
        self.record["type"]="game"
        result=route_identity(self.record)
        self.assertEqual(result["repository"],"shihuiarenjinba-png/AI-Game-Factory")
    def test_no_default_id(self):
        self.record["identity"].pop("store_id")
        with self.assertRaises(ValueError):route_identity(self.record)
    def test_no_unauthorized_verification(self):
        self.record["operator_verified"]=False
        with self.assertRaises(ValueError):route_identity(self.record)
    def test_no_untrusted_evidence_url(self):
        self.record["official_evidence_url"]="https://partner.microsoft.com.evil.example/path"
        with self.assertRaises(ValueError):route_identity(self.record)
    def test_no_path_escape(self):
        self.record["slug"]="../other-app"
        with self.assertRaises(ValueError):route_identity(self.record)
    def test_missing_pinned_sha(self):
        self.record["expected_head_sha"]="main"
        with self.assertRaises(ValueError):route_identity(self.record)
    def test_3d_kind_routes_only_3d_factory(self):
        self.record["type"]="3d-game"
        result=route_identity(self.record)
        self.assertEqual(result["repository"],"shihuiarenjinba-png/3d-game-factory")
        self.assertEqual(result["branch"],"codex/3d-provisioner-job-contract-20261027")
        self.assertEqual(result["path"],"products/useful-tool/store/approved-identity.json")
        self.assertFalse(result["applied"])
    def test_wrong_kind_holds(self):
        self.record["type"]="GAME_3D"
        with self.assertRaises(ValueError):route_identity(self.record)
    def test_fake_publisher_holds_if_missing_subject(self):
        self.record["identity"]["publisher"]="not-a-publisher"
        with self.assertRaises(ValueError):route_identity(self.record)
    def test_dry_run_writes_instruction_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"input.json"; destination=root/"return.json"
            source.write_text(json.dumps(self.record))
            self.assertEqual(main(["--input",str(source),"--output",str(destination)]),0)
            returned=json.loads(destination.read_text())
            self.assertFalse(returned["applied"])
            self.assertNotIn("token",returned)
if __name__=="__main__":unittest.main()
