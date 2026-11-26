import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from all_auto.lane_queue import relative_package_path
from scripts.local_handoff_pull import pull, recent_artifacts
from scripts.github_artifact_custody import safe_package_folder, verify_queue_artifact_custody

SOURCE_SHA="b"*40
RUN_HEAD_SHA="c"*40
XML=b'<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="Demo.App" Publisher="CN=ABC" Version="1.0.0.0"/></Package>'

class LocalPullTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.fixture=self.root/"fixture"
        self.fixture.mkdir()
        bundle=self.fixture/"factory-qa"
        bundle.mkdir()
        with zipfile.ZipFile(bundle/"package.msix","w") as z:
            z.writestr("AppxManifest.xml",XML)
            z.writestr("AppxBlockMap.xml",b"<BlockMap/>")
            z.writestr("[Content_Types].xml",b"<Types/>")
            z.writestr("main.exe",b"not actually installed")
        data=(bundle/"package.msix").read_bytes()
        self.checksum=hashlib.sha256(data).hexdigest()
        meta={"schema_version":1,
            "source_repository":"https://github.com/shihuiarenjinba-png/AI-App-Factory",
            "source_sha":SOURCE_SHA,"type":"app","slug":"sample-app",
            "package":"package.msix","status":"QA_UNSIGNED","package_bytes":len(data),
            "package_sha256":self.checksum,
            "identity":{"name":"Demo.App","publisher":"CN=ABC","version":"1.0.0.0"}}
        (bundle/"handoff.json").write_text(json.dumps(meta))
        self.q={"schema_version":1,"mode":"WINDOWS_LOCAL_QA_ONLY","intake_count":1,
           "items":[{**meta,"store_id":None,"submit_allowed":False,
                     "security_confirmed":False,"price_approved":False}],
           "store_submissions":0}
        self.run_id=888
        self.artifact_id=111
        self.artifact_name="verified-msix-local-qa-888"
        self.run_head_sha=RUN_HEAD_SHA
        self.build_artifact()

    def build_artifact(self):
        self.artifact_dir=self.root/"artifact"
        if self.artifact_dir.exists():
            shutil.rmtree(self.artifact_dir)
        (self.artifact_dir/"packages").mkdir(parents=True)
        folder=relative_package_path(self.q["items"][0])
        destination=self.artifact_dir/"packages"/folder
        destination.mkdir()
        for entry in (self.fixture/"factory-qa").iterdir():
            shutil.copyfile(entry,destination/entry.name)
        (self.artifact_dir/"queue.json").write_text(json.dumps(self.q),encoding="utf-8")
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
            z.write(self.artifact_dir/"queue.json","queue.json")
            for path in sorted((self.artifact_dir/"packages").rglob("*")):
                if path.is_file():
                    z.write(path,path.relative_to(self.artifact_dir).as_posix())
        self.archive_bytes=archive.getvalue()
        self.run_response={
            "name":"Factory MSIX intake and local QA handoff",
            "path":".github/workflows/factory-msix-intake.yml",
            "status":"completed","conclusion":"success",
            "event":"schedule","head_sha":self.run_head_sha,
            "head_branch":"codex/windows-all-auto-integration-20261026",
            "head_repository":{"full_name":"shihuiarenjinba-png/Windows-all-auto"},
        }
        self.artifact_response={
            "id":self.artifact_id,"name":self.artifact_name,"expired":False,
            "digest":"sha256:"+hashlib.sha256(self.archive_bytes).hexdigest(),
            "workflow_run":{"id":self.run_id,"head_sha":self.run_head_sha},
        }

    def fake_gh(self,*args):
        if args[0]=="api" and "actions/artifacts" in args[-1]:
            self.build_artifact()
            return json.dumps({"total_count":1,"artifacts":[{
                "id":self.artifact_id,"name":self.artifact_name,"expired":False,
                "workflow_run":{"id":self.run_id}}]})
        if args[0]=="api" and "/actions/runs/" in args[-1]:
            self.build_artifact()
            return json.dumps(self.run_response)
        if args[0]=="run":
            self.build_artifact()
            shutil.copytree(self.artifact_dir,Path(args[-1]),dirs_exist_ok=True)
            return ""
        raise RuntimeError("unexpected command")

    def fake_clients(self,token):
        self.build_artifact()
        def fetch_json(url):
            if url.endswith("/runs/"+str(self.run_id)):
                return self.run_response
            if url.endswith("/artifacts/"+str(self.artifact_id)):
                return self.artifact_response
            raise AssertionError("unexpected GitHub API URL")
        def fetch_bytes(url):
            if url.endswith("/artifacts/"+str(self.artifact_id)+"/zip"):
                return self.archive_bytes
            raise AssertionError("unexpected GitHub artifact URL")
        return fetch_json,fetch_bytes

    def pull_fake(self,target,gh_side_effect=None,clients_side_effect=None):
        with patch("scripts.local_handoff_pull.gh",side_effect=gh_side_effect or self.fake_gh), \
             patch("scripts.local_handoff_pull.github_clients",side_effect=clients_side_effect or self.fake_clients), \
             patch.dict("os.environ",{"GH_TOKEN":"test-token"}):
            return pull(target)

    def test_local_qa_artifact_pagination_does_not_drop_older_packages(self):
        # More than 30 artifacts and more than one GitHub API page must
        # remain visible to the local QA puller.
        calls=[]
        def paged_gh(*args):
            calls.append(args)
            if args[:3]==("api","-X","GET") and "actions/artifacts?" in args[-1]:
                page=int(args[-1].rsplit("page=",1)[-1])
                ids=range(1,101) if page==1 else range(101,102)
                return json.dumps({"total_count":101,"artifacts":[
                    {"id":n,"name":"verified-msix-local-qa-"+str(n),
                     "expired":False,"workflow_run":{"id":n}} for n in ids]})
            if args[:3]==("api","-X","GET") and "/actions/runs/" in args[-1]:
                return json.dumps({"name":"Factory MSIX intake and local QA handoff",
                                   "status":"completed","conclusion":"success",
                                   "head_sha":RUN_HEAD_SHA})
            raise AssertionError("unexpected GitHub call")
        with patch("scripts.local_handoff_pull.gh",side_effect=paged_gh):
            found=recent_artifacts()
        self.assertEqual(len(found),101)
        self.assertEqual(found[0]["run_id"],1)
        self.assertEqual(found[0]["artifact_name"],"verified-msix-local-qa-1")
        self.assertEqual(found[-1]["run_id"],101)
        self.assertEqual(found[-1]["run_head_sha"],RUN_HEAD_SHA)
        pages=[a[-1] for a in calls if "actions/artifacts?" in a[-1]]
        self.assertEqual(len(pages),2)

    def test_local_qa_artifact_pagination_holds_on_truncated_listing(self):
        def truncated_gh(*args):
            if "actions/artifacts?" in args[-1]:
                return json.dumps({"total_count":120,"artifacts":[
                    {"id":n,"name":"verified-msix-local-qa-"+str(n),
                     "expired":False,"workflow_run":{"id":n}} for n in range(5)]})
            raise AssertionError("should HOLD before checking individual runs")
        with patch("scripts.local_handoff_pull.gh",side_effect=truncated_gh):
            with self.assertRaisesRegex(ValueError,"listing incomplete"):
                recent_artifacts()

    def test_local_download_verifies_package_and_persists_custody_receipt(self):
        result=self.pull_fake(self.root/"inbox")
        self.assertEqual(result["new_packages"],1)
        self.assertEqual(result["submitted_to_store"],0)
        self.assertEqual(len(result["custody_receipts"]),1)
        receipt=result["custody_receipts"][0]
        self.assertEqual(receipt["status"],"CUSTODY_VERIFIED_ONLY")
        self.assertFalse(receipt["e2e_pass"])
        self.assertEqual(receipt["local_pull_status"],"VERIFIED")
        self.assertEqual(receipt["packages"][0]["local_pull_status"],"VERIFIED")
        saved=json.loads((self.root/"inbox"/".artifact-custody"/"111.json").read_text())
        self.assertEqual(saved,receipt)
        self.assertEqual(len([p for p in (self.root/"inbox").iterdir()
                              if p.name!=".artifact-custody"]),1)

    def test_duplicate_download_does_not_multiply_storage_or_receipts(self):
        target=self.root/"inbox"
        self.pull_fake(target)
        self.pull_fake(target)
        self.assertEqual(len([p for p in target.iterdir() if p.name!=".artifact-custody"]),1)
        self.assertEqual(len(list((target/".artifact-custody").iterdir())),1)

    def test_artifact_archive_digest_mismatch_holds_before_staging(self):
        def bad_clients(token):
            fetch_json,fetch_bytes=self.fake_clients(token)
            def altered_json(url):
                value=fetch_json(url)
                if url.endswith("/artifacts/"+str(self.artifact_id)):
                    value=dict(value)
                    value["digest"]="sha256:"+"0"*64
                return value
            return altered_json,fetch_bytes
        target=self.root/"inbox"
        with self.assertRaisesRegex(ValueError,"ARTIFACT_ARCHIVE_DIGEST_MISMATCH"):
            self.pull_fake(target,clients_side_effect=bad_clients)
        self.assertEqual(list(target.iterdir()),[])

    def test_duplicate_archive_path_rejected_before_staging(self):
        def duplicate_clients(token):
            self.build_artifact()
            source_archive = io.BytesIO(self.archive_bytes)
            duplicate_archive = io.BytesIO()
            with zipfile.ZipFile(source_archive) as source, \
                 zipfile.ZipFile(duplicate_archive, "w", zipfile.ZIP_DEFLATED) as target:
                for info in source.infolist():
                    target.writestr(info.filename, source.read(info.filename))
                # A matching GitHub digest must not make duplicate archive paths acceptable.
                target.writestr("queue.json", (self.artifact_dir / "queue.json").read_bytes())
            duplicate_bytes = duplicate_archive.getvalue()
            artifact = dict(self.artifact_response)
            artifact["digest"] = "sha256:" + hashlib.sha256(duplicate_bytes).hexdigest()

            def fetch_json(url):
                if url.endswith("/runs/" + str(self.run_id)):
                    return self.run_response
                if url.endswith("/artifacts/" + str(self.artifact_id)):
                    return artifact
                raise AssertionError("unexpected GitHub API URL")

            def fetch_bytes(url):
                if url.endswith("/artifacts/" + str(self.artifact_id) + "/zip"):
                    return duplicate_bytes
                raise AssertionError("unexpected GitHub artifact URL")

            return fetch_json, fetch_bytes

        target = self.root / "inbox"
        with self.assertRaisesRegex(ValueError, "ARTIFACT_DUPLICATE_PATH"):
            self.pull_fake(target, clients_side_effect=duplicate_clients)
        self.assertEqual(list(target.iterdir()), [])

    def test_local_extracted_bytes_must_match_archived_bytes(self):
        def tampered_gh(*args):
            result=self.fake_gh(*args)
            if args[0]=="run":
                folder=Path(args[-1])
                package=folder/"packages"/relative_package_path(self.q["items"][0])/"package.msix"
                with package.open("ab") as stream:
                    stream.write(b"tampered-after-download")
            return result
        target=self.root/"inbox"
        with self.assertRaisesRegex(ValueError,"LOCAL_ARTIFACT_BYTES_DIFFER"):
            self.pull_fake(target,gh_side_effect=tampered_gh)
        self.assertEqual(list(target.iterdir()),[])

    def test_illegal_store_approval_rejected(self):
        self.q["items"][0]["submit_allowed"]=True
        with self.assertRaisesRegex(ValueError,"QUEUE_STORE_AUTHORITY_INVALID"):
            self.pull_fake(self.root/"inbox")

    def test_corrupt_queue_count_rejected(self):
        self.q["intake_count"]=2
        with self.assertRaisesRegex(ValueError,"QUEUE_PERMISSION_OR_COUNT_INVALID"):
            self.pull_fake(self.root/"inbox")

    def test_queue_cannot_underreport_package_size(self):
        # A forged small size must not bypass the 2 GiB quota.
        self.q["items"][0]["package_bytes"]=1
        with self.assertRaisesRegex(ValueError,"QUEUE_PACKAGE_METADATA_MISMATCH"):
            self.pull_fake(self.root/"inbox")
        self.assertEqual(list((self.root/"inbox").iterdir()),[])

    def test_queue_cannot_replace_verified_identity(self):
        self.q["items"][0]["identity"]["publisher"]="CN=UNVERIFIED"
        with self.assertRaisesRegex(ValueError,"Queue metadata mismatch: identity"):
            self.pull_fake(self.root/"inbox")
        self.assertEqual(list((self.root/"inbox").iterdir()),[])

    def test_custody_layer_allows_bounded_approved_identity_member_without_claiming_e2e(self):
        # This layer proves only archive/local byte custody. The later strict
        # handoff validator still requires the complete paired Identity receipts.
        (self.fixture / "factory-qa" / "approved-identity.json").write_text(
            '{"reviewed": true}', encoding="utf-8"
        )
        self.build_artifact()
        fetch_json, fetch_bytes = self.fake_clients("test-token")
        result = verify_queue_artifact_custody(
            {"repository": "shihuiarenjinba-png/Windows-all-auto",
             "run_id": self.run_id, "artifact_id": self.artifact_id,
             "artifact_name": self.artifact_name, "run_head_sha": self.run_head_sha},
            self.artifact_dir, fetch_json, fetch_bytes
        )
        self.assertEqual(result["status"], "CUSTODY_VERIFIED_ONLY")
        self.assertIs(result["e2e_pass"], False)

    def test_safe_package_folder_rejects_path_traversal(self):
        item = {"slug": "../escape", "package_sha256": self.checksum}
        with self.assertRaisesRegex(ValueError, "PACKAGE_PATH_INVALID"):
            safe_package_folder(item)

    def test_queue_cannot_claim_store_id_or_approval(self):
        self.q["items"][0]["store_id"]="UNVERIFIED-STORE-ID"
        with self.assertRaisesRegex(ValueError,"QUEUE_STORE_AUTHORITY_INVALID"):
            self.pull_fake(self.root/"inbox")
        self.q["items"][0]["store_id"]=None
        self.q["items"][0]["security_confirmed"]=True
        with self.assertRaisesRegex(ValueError,"must not assert Store approvals"):
            self.pull_fake(self.root/"inbox")


if __name__=="__main__":unittest.main()
