import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from all_auto.bridge_poll import all_artifacts, candidates, verified_run, intake, MAX_PER_FACTORY

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

    def test_paged_factory_artifacts_include_oldest_unprocessed(self):
        calls=[]
        def fake_api(route):
            calls.append(route)
            page=int(route.rsplit("page=",1)[-1])
            ids=range(101,1,-1) if page==1 else [1]
            return {"total_count":101,"artifacts":[
                {"id":i,"name":NAME,"expired":False,
                 "workflow_run":{"id":555}} for i in ids]}
        with patch("all_auto.bridge_poll.api",side_effect=fake_api):
            payload=all_artifacts(REPO)
        self.assertEqual(len(calls),2)
        self.assertEqual(len(payload["artifacts"]),101)
        self.assertEqual([a["id"] for a in candidates(payload,set())],
                         list(range(1,MAX_PER_FACTORY+1)))

    def test_factory_backlog_cannot_silently_truncate(self):
        with patch("all_auto.bridge_poll.api",return_value={
            "total_count":120,"artifacts":[ARTIFACT]}):
            with self.assertRaisesRegex(ValueError,"listing incomplete"):
                all_artifacts(REPO)

    def test_factory_backlog_over_limit_is_hold(self):
        with patch("all_auto.bridge_poll.api",return_value={
            "total_count":1001,"artifacts":[ARTIFACT]}):
            with self.assertRaisesRegex(ValueError,"safe scan bound"):
                all_artifacts(REPO)

    def test_factory_page_count_change_is_hold(self):
        def fake_api(route):
            page=int(route.rsplit("page=",1)[-1])
            return {"total_count":101 if page==1 else 102,
                    "artifacts":[ARTIFACT]* (100 if page==1 else 1)}
        with patch("all_auto.bridge_poll.api",side_effect=fake_api):
            with self.assertRaisesRegex(ValueError,"changed during scan"):
                all_artifacts(REPO)

    def test_per_factory_budget_fits_local_qa_queue(self):
        self.assertLessEqual(3*MAX_PER_FACTORY,20)
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

    def test_3d_factory_uses_distinct_allowlisted_workflow(self):
        repo="shihuiarenjinba-png/3d-game-factory"
        run=dict(RUN,name="3D Store MSIX candidate build",event="workflow_dispatch",
                 head_repository={"full_name":repo},head_branch="codex/3d-product-demo")
        self.assertEqual(verified_run(run,repo,ARTIFACT),SHA)
        with self.assertRaisesRegex(ValueError,"workflow or event"):
            verified_run(dict(run,name="Factory MSIX export"),repo,ARTIFACT)

    def test_real_bundle_moves_once_without_store_permission(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            product=root/"mock"
            product.mkdir()
            with zipfile.ZipFile(product/"package.msix","w") as z:
                z.writestr("AppxManifest.xml",XML)
                z.writestr("AppxBlockMap.xml",b"<BlockMap/>")
                z.writestr("[Content_Types].xml",b"<Types/>")
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
                if "/actions/artifacts?per_page=100&page=" in route:
                    items=[ARTIFACT] if "AI-App-Factory" in route else []
                    return {"total_count":len(items),"artifacts":items}
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


class AppIdentityReturnTransportTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.fixture=self.root/"factory-artifact"
        self.fixture.mkdir()
        self.source_sha=SHA
        self.branch="codex/factory-bootstrap-20261026"
        self.store_id="9PTESTING"
        self.request_id="app-sample-app-aaaaaaaa"
        self.identity={"name":"Demo.App","publisher":"CN=ABC","version":"1.0.0.0"}
        self.exe=b"fixture-exe"
        with zipfile.ZipFile(self.fixture/"package.msix","w") as z:
            z.writestr("AppxManifest.xml",XML)
            z.writestr("AppxBlockMap.xml",b"<BlockMap/>")
            z.writestr("[Content_Types].xml",b"<Types/>")
            z.writestr("main.exe",self.exe)
        package=(self.fixture/"package.msix").read_bytes()
        self.handoff={
            "schema_version":1,"source_repository":"https://github.com/"+REPO,
            "source_sha":self.source_sha,"expected_head_sha":self.source_sha,
            "factory_head_sha":self.source_sha,"type":"app","slug":"sample-app",
            "package":"package.msix","status":"QA_UNSIGNED",
            "package_bytes":len(package),"package_sha256":hashlib.sha256(package).hexdigest(),
            "identity":self.identity,"request_id":self.request_id,"product_type":"APP",
            "source_factory":"AI-App-Factory","source_branch":self.branch,
            "store_id":self.store_id,"display_name":"Sample App",
            "prebuilt_exe_sha256":hashlib.sha256(self.exe).hexdigest()
        }
        self.handoff_bytes=json.dumps(self.handoff,separators=(",",":")).encode("utf-8")
        (self.fixture/"handoff.json").write_bytes(self.handoff_bytes)
        self.approved={
            "schema_version":"1.0","reviewed":True,"source":"partner_center",
            "request_id":self.request_id,"product_type":"APP","source_factory":"AI-App-Factory",
            "source_repository":REPO,"source_branch":self.branch,
            "source_sha":self.source_sha,"verified_source_sha":self.source_sha,
            "expected_head_sha":self.source_sha,"store_id":self.store_id,
            "name":self.identity["name"],"publisher":self.identity["publisher"],
            "version":self.identity["version"],"display_name":"Sample App",
            "package_version_gate":"PASS","operator_verified":True,
            "verified_by":"fixture-operator",
            "evidence_url":"https://partner.microsoft.com/en-us/dashboard/products/"+self.store_id+"/identity"
        }
        self.identity_bytes=json.dumps(self.approved,separators=(",",":")).encode("utf-8")
        self.identity_blob_sha=hashlib.sha1(
            b"blob "+str(len(self.identity_bytes)).encode("ascii")+b"\0"+self.identity_bytes
        ).hexdigest()
        self.identity_response={"encoding":"base64",
            "content":base64.b64encode(self.identity_bytes).decode("ascii"),
            "sha":self.identity_blob_sha}
        self.archive_buffer=io.BytesIO()
        with zipfile.ZipFile(self.archive_buffer,"w") as z:
            z.writestr("handoff.json",self.handoff_bytes)
            z.writestr("package.msix",package)
        self.archive=self.archive_buffer.getvalue()
        self.artifact=dict(ARTIFACT,digest="sha256:"+hashlib.sha256(self.archive).hexdigest())
        self.artifact_meta={
            "id":123,"name":NAME,"expired":False,
            "workflow_run":{"id":555,"head_sha":self.source_sha},
            "digest":"sha256:"+hashlib.sha256(self.archive).hexdigest()
        }
        self.custody_run={"id":555,"head_sha":self.source_sha,
            "status":"completed","conclusion":"success"}
        self.ledger=self.root/"ledger.json"
        self.ledger.write_text(json.dumps({"schema_version":1,
            "processed_artifacts":[],"request_sources":{}}),encoding="utf-8")
        self.out=self.root/"out"

    def run_intake(self,identity_response="DEFAULT",branch_sha=None,archive=None):
        identity_response=self.identity_response if identity_response=="DEFAULT" else identity_response
        branch_sha=self.source_sha if branch_sha is None else branch_sha
        archive=self.archive if archive is None else archive
        def fake_api(route):
            if "/actions/artifacts?" in route:
                items=[self.artifact] if REPO in route else []
                return {"total_count":len(items),"artifacts":items}
            if "/actions/runs/" in route:
                return RUN
            if "/branches/" in route:
                return {"commit":{"sha":branch_sha}}
            if "/contents/" in route:
                if identity_response is None:
                    raise RuntimeError("not found")
                return identity_response
            raise AssertionError("unexpected API route: "+route)
        def fake_command(*args):
            if args[0]=="run":
                target=Path(args[-1])
                for entry in self.fixture.iterdir():
                    shutil.copyfile(entry,target/entry.name)
                return ""
            raise AssertionError("unexpected GitHub command")
        def fake_clients(token):
            self.assertEqual(token,"fixture-token")
            def get_json(url):
                return self.custody_run if "/runs/" in url else self.artifact_meta
            return get_json,lambda url:archive
        with patch.dict("os.environ",{"GH_TOKEN":"fixture-token"}), \
             patch("all_auto.bridge_poll.api",side_effect=fake_api), \
             patch("all_auto.bridge_poll.command",side_effect=fake_command), \
             patch("all_auto.bridge_poll.github_clients",side_effect=fake_clients):
            return intake(self.ledger,self.out)

    def test_source_bound_identity_and_independent_custody_are_staged(self):
        result=self.run_intake()
        self.assertEqual(result["received"],1)
        queue=json.loads((self.out/"queue.json").read_text(encoding="utf-8"))
        self.assertEqual(queue["intake_count"],1)
        item=queue["items"][0]
        self.assertEqual(item["github_artifact_custody"]["status"],"CUSTODY_VERIFIED_ONLY")
        self.assertFalse(item["github_artifact_custody"]["e2e_pass"])
        self.assertEqual(item["factory_run_id"],555)
        self.assertEqual(item["factory_artifact_id"],123)
        folder=self.out/"packages"/"APP"/("sample-app-"+self.handoff["package_sha256"][:12])
        self.assertEqual({p.name for p in folder.iterdir()},
            {"handoff.json","package.msix","approved-identity.json",
             "transport_receipt.json","github-custody.json"})
        self.assertEqual((folder/"approved-identity.json").read_bytes(),self.identity_bytes)
        transport=json.loads((folder/"transport_receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(transport["source_sha"],self.source_sha)
        self.assertEqual(transport["package_version"],"1.0.0.0")
        self.assertFalse(transport["store_submission_allowed"])
        self.assertFalse(transport["certification_allowed"])
        self.assertFalse(transport["publish_allowed"])
        self.assertEqual(json.loads(self.ledger.read_text())["processed_artifacts"],[123])
        self.assertEqual(self.run_intake()["received"],0)

    def test_missing_current_source_identity_stays_unprocessed(self):
        with self.assertRaisesRegex(ValueError,"CURRENT_SOURCE_APPROVED_IDENTITY_UNAVAILABLE"):
            self.run_intake(identity_response=None)
        self.assertEqual(json.loads(self.ledger.read_text())["processed_artifacts"],[])
        self.assertFalse((self.out/"packages").exists())

    def test_historical_or_unapproved_version_stays_hold(self):
        approved=dict(self.approved,package_version_gate="HOLD")
        raw=json.dumps(approved,separators=(",",":")).encode("utf-8")
        response={"encoding":"base64","content":base64.b64encode(raw).decode("ascii"),
                  "sha":hashlib.sha1(b"blob "+str(len(raw)).encode("ascii")+b"\0"+raw).hexdigest()}
        with self.assertRaisesRegex(ValueError,"CURRENT_SOURCE_APPROVED_IDENTITY_OR_VERSION_HOLD"):
            self.run_intake(identity_response=response)
        self.assertEqual(json.loads(self.ledger.read_text())["processed_artifacts"],[])

    def test_source_branch_drift_stays_hold(self):
        with self.assertRaisesRegex(ValueError,"SOURCE_BRANCH_DRIFT"):
            self.run_intake(branch_sha="c"*40)
        self.assertEqual(json.loads(self.ledger.read_text())["processed_artifacts"],[])

    def test_independent_archive_digest_mismatch_stays_hold(self):
        with self.assertRaisesRegex(ValueError,"SOURCE_ARTIFACT_CUSTODY_HOLD:ARTIFACT_ARCHIVE_DIGEST_MISMATCH"):
            self.run_intake(archive=b"tampered")
        self.assertEqual(json.loads(self.ledger.read_text())["processed_artifacts"],[])


if __name__=="__main__":unittest.main()


if __name__=="__main__":unittest.main()
