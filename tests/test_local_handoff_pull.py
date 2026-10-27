import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts.local_handoff_pull import pull, recent_artifacts

SOURCE_SHA="b"*40
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
           "items":[{**meta,"store_id":None,"submit_allowed":False}]}

    def fake_gh(self,*args):
        if args[0]=="api" and "actions/artifacts" in args[-1]:
            return json.dumps({"artifacts":[{"id":111,"name":"verified-msix-local-qa-888",
                    "expired":False,"workflow_run":{"id":888}}]})
        if args[0]=="api" and "/actions/runs/" in args[-1]:
            return json.dumps({"name":"Factory MSIX intake and local QA handoff","conclusion":"success"})
        if args[0]=="run":
            folder=Path(args[-1])
            (folder/"packages"/("sample-app-"+self.checksum[:12])).mkdir(parents=True)
            dest=folder/"packages"/("sample-app-"+self.checksum[:12])
            for entry in (self.fixture/"factory-qa").iterdir():
                shutil.copyfile(entry,dest/entry.name)
            (folder/"queue.json").write_text(json.dumps(self.q))
            return ""
        raise RuntimeError("unexpected command")

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
                                   "conclusion":"success"})
            raise AssertionError("unexpected GitHub call")
        with patch("scripts.local_handoff_pull.gh",side_effect=paged_gh):
            found=recent_artifacts()
        self.assertEqual(len(found),101)
        self.assertEqual(found[0],(1,"verified-msix-local-qa-1"))
        self.assertEqual(found[-1],(101,"verified-msix-local-qa-101"))
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

    def test_local_download_verifies_package(self):
        with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_gh):
            result=pull(self.root/"inbox")
            self.assertEqual(result["new_packages"],1)
            self.assertEqual(result["submitted_to_store"],0)
            self.assertEqual(len(list((self.root/"inbox").iterdir())),1)

    def test_duplicate_download_does_not_multiply_storage(self):
        with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_gh):
            pull(self.root/"inbox")
            pull(self.root/"inbox")
            self.assertEqual(len(list((self.root/"inbox").iterdir())),1)

    def test_full_local_inbox_preserves_remote_backlog_without_failure(self):
        inbox=self.root/"inbox"
        inbox.mkdir()
        for n in range(20):
            existing=inbox/("existing-"+str(n))
            existing.mkdir()
            (existing/"package.msix").write_bytes(b"x")
        with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_gh):
            result=pull(inbox)
        self.assertEqual(result["status"],"HOLD_LOCAL_CAPACITY")
        self.assertEqual(result["reason"],"LOCAL_QA_INBOX_FULL")
        self.assertTrue(result["remote_backlog_preserved"])
        self.assertEqual(result["new_packages"],0)
        self.assertEqual(sum(1 for p in inbox.rglob("package.msix")),20)

    def test_illegal_store_approval_rejected(self):
        self.q["items"][0]["submit_allowed"]=True
        with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_gh):
            with self.assertRaisesRegex(ValueError,"authorize Store submission"):
                pull(self.root/"inbox")

    def test_corrupt_queue_count_rejected(self):
        self.q["intake_count"]=2
        with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_gh):
            with self.assertRaisesRegex(ValueError,"Invalid queue count"):
                pull(self.root/"inbox")

    def test_queue_cannot_underreport_package_size(self):
        # A forged small size must not bypass the 2 GiB quota.
        self.q["items"][0]["package_bytes"]=1
        with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_gh):
            with self.assertRaisesRegex(ValueError,"Queue metadata mismatch: package_bytes"):
                pull(self.root/"inbox")
        self.assertEqual(list((self.root/"inbox").iterdir()),[])

    def test_queue_cannot_replace_verified_identity(self):
        self.q["items"][0]["identity"]["publisher"]="CN=UNVERIFIED"
        with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_gh):
            with self.assertRaisesRegex(ValueError,"Queue metadata mismatch: identity"):
                pull(self.root/"inbox")
        self.assertEqual(list((self.root/"inbox").iterdir()),[])

    def test_queue_cannot_claim_store_id_or_approval(self):
        self.q["items"][0]["store_id"]="UNVERIFIED-STORE-ID"
        with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_gh):
            with self.assertRaisesRegex(ValueError,"must not assign a Store ID"):
                pull(self.root/"inbox")
        self.q["items"][0]["store_id"]=None
        self.q["items"][0]["security_confirmed"]=True
        with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_gh):
            with self.assertRaisesRegex(ValueError,"must not assert Store approvals"):
                pull(self.root/"inbox")

if __name__=="__main__":unittest.main()
