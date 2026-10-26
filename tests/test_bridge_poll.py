import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from all_auto.bridge_poll import candidates, verified_run, intake

SHA="a"*40
NAME="factory-msix-handoff-demo"
REPO="shihuiarenjinba-png/AI-App-Factory"
ARTIFACT={"id":123,"name":NAME,"expired":False,"workflow_run":{"id":555}}
RUN={"id":555,"conclusion":"success","name":"Factory MSIX export","event":"push",
     "path":".github/workflows/msix-export.yml",
     "head_repository":{"full_name":REPO},"head_branch":"codex/factory-bootstrap-20261026",
     "head_sha":SHA}
XML=b'<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="Demo.App" Publisher="CN=ABC" Version="1.0.0.0"/></Package>'

class PollTests(unittest.TestCase):
    def test_valid_candidates(self):
        self.assertEqual(candidates({"artifacts":[ARTIFACT]},set()),[ARTIFACT])
    def test_existing_artifact_is_skipped(self):
        self.assertEqual(candidates({"artifacts":[ARTIFACT]},{123}),[])
    def test_failed_run_cannot_transfer(self):
        with self.assertRaises(ValueError):verified_run(dict(RUN,conclusion="failure"),REPO,ARTIFACT)
    def test_wrong_repo_cannot_transfer(self):
        with self.assertRaises(ValueError):verified_run(RUN,"elsewhere/factory",ARTIFACT)
    def test_wrong_workflow_cannot_transfer(self):
        with self.assertRaises(ValueError):verified_run(dict(RUN,name="Untrusted task"),REPO,ARTIFACT)
    def test_non_codex_branch_cannot_transfer(self):
        with self.assertRaises(ValueError):verified_run(dict(RUN,head_branch="main"),REPO,ARTIFACT)

    def test_same_name_wrong_workflow_path_cannot_transfer(self):
        # Another workflow can spoof a display name, not its trusted path.
        with self.assertRaisesRegex(ValueError,"workflow path"):
            verified_run(dict(RUN,path=".github/workflows/untrusted.yml"),REPO,ARTIFACT)

    def test_missing_workflow_path_cannot_transfer(self):
        fake=dict(RUN)
        del fake["path"]
        with self.assertRaisesRegex(ValueError,"workflow path"):
            verified_run(fake,REPO,ARTIFACT)

    def test_artifact_run_id_mismatch_cannot_transfer(self):
        with self.assertRaisesRegex(ValueError,"run mismatch"):
            verified_run(dict(RUN,id=556),REPO,ARTIFACT)

    def test_missing_run_id_cannot_transfer(self):
        fake=dict(RUN)
        del fake["id"]
        with self.assertRaisesRegex(ValueError,"run mismatch"):
            verified_run(fake,REPO,ARTIFACT)


    def test_manual_dispatch_workflow_is_allowed_when_verified(self):
        self.assertEqual(verified_run(dict(RUN,event="workflow_dispatch"),REPO,ARTIFACT),SHA)

    def test_manual_dispatch_other_workflow_is_rejected(self):
        with self.assertRaises(ValueError):
            verified_run(dict(RUN,event="workflow_dispatch",name="Unknown export"),REPO,ARTIFACT)

    def test_real_bundle_moves_once_without_store_permission(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            product=root/"mock"
            product.mkdir()
            with zipfile.ZipFile(product/"package.msix","w") as z:
                z.writestr("AppxManifest.xml",XML)
                z.writestr("bin.exe",b"pretend binary")
            package=(product/"package.msix").read_bytes()
            (product/"handoff.json").write_text(json.dumps({
                "schema_version":1,"source_repository":"https://github.com/"+REPO,
                "source_sha":SHA,"type":"app","slug":"demo-app",
                "package":"package.msix","status":"QA_UNSIGNED",
                "package_sha256":hashlib.sha256(package).hexdigest(),
                "package_bytes":len(package),
                "identity":{"name":"Demo.App","publisher":"CN=ABC","version":"1.0.0.0"}
            }))
            ledger=root/"ledger.json"
            ledger.write_text('{"schema_version":1,"processed_artifacts":[]}')
            out=root/"output"
            def fake_api(route):
                if route.endswith("actions/artifacts?per_page=100"):
                    return {"artifacts":[ARTIFACT] if "AI-App-Factory" in route else []}
                return RUN
            def fake_command(*args):
                if args[0]=="run":
                    target=Path(args[-1])
                    for p in product.iterdir():
                        shutil.copyfile(p,target/p.name)
                    return ""
                raise AssertionError("Unexpected command")
            with patch.dict("os.environ",{"GH_TOKEN":"placeholder-local-test-token"}), \
                 patch("all_auto.bridge_poll.api",side_effect=fake_api), \
                 patch("all_auto.bridge_poll.command",side_effect=fake_command):
                result=intake(ledger,out)
                self.assertEqual(result["received"],1)
                queued=json.loads((out/"queue.json").read_text())
                self.assertEqual(queued["intake_count"],1)
                self.assertFalse(queued["items"][0]["submit_allowed"])
                self.assertEqual(intake(ledger,out)["received"],0)
                self.assertEqual(json.loads(ledger.read_text())["processed_artifacts"],[123])

if __name__=="__main__":unittest.main()
