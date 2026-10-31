import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts.local_handoff_pull import pull, recent_artifacts
from all_auto.handoff_bridge import validate_bundle

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


    def test_queue_rejects_ambiguous_json_before_staging(self):
        # Both outer and nested duplicate keys must be rejected, as must NaN.
        originals=json.dumps(self.q)
        variants=[
            originals.replace('"schema_version": 1',
                              '"schema_version": 1, "schema_version": 1',1),
            originals.replace('"submit_allowed": false',
                              '"submit_allowed": false, "submit_allowed": false',1),
            originals.replace('"intake_count": 1', '"intake_count": NaN',1),
        ]
        for raw in variants:
            def fake(*args):
                result=self.fake_gh(*args)
                if args[0]=="run":
                    (Path(args[-1])/"queue.json").write_text(raw,encoding="utf-8")
                return result
            with self.subTest(raw=raw[:80]):
                with patch("scripts.local_handoff_pull.gh",side_effect=fake):
                    with self.assertRaisesRegex(ValueError,"Duplicate|Non-finite"):
                        pull(self.root/"inbox")
                self.assertEqual(list((self.root/"inbox").iterdir()),[])

    def test_queue_rejects_boolean_schema_and_count(self):
        for field in ("schema_version","intake_count"):
            original=self.q[field]
            self.q[field]=True
            with self.subTest(field=field):
                with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_gh):
                    with self.assertRaisesRegex(ValueError,"Wrong queue schema|Invalid queue count"):
                        pull(self.root/"inbox")
                self.assertEqual(list((self.root/"inbox").iterdir()),[])
            self.q[field]=original

    def test_duplicate_package_and_request_rejected_before_staging(self):
        self.q["intake_count"]=2
        self.q["items"].append(dict(self.q["items"][0]))
        with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_gh):
            with self.assertRaisesRegex(ValueError,"Duplicate local QA package"):
                pull(self.root/"inbox")
        self.assertEqual(list((self.root/"inbox").iterdir()),[])

    def test_invalid_second_item_does_not_stage_first(self):
        second=dict(self.q["items"][0])
        second["slug"]="other-app"
        self.q["items"].append(second)
        self.q["intake_count"]=2
        with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_gh):
            with self.assertRaisesRegex(ValueError,"Missing source package directory"):
                pull(self.root/"inbox")
        self.assertEqual(list((self.root/"inbox").iterdir()),[])

    def fake_two_item_gh(self, *args):
        """Two valid distinct packages in one authenticated artifact."""
        result=self.fake_gh(*args)
        if args[0]=="run":
            root=Path(args[-1])
            folder=root/"packages"/("sample-two-"+self.checksum[:12])
            folder.mkdir()
            for entry in (self.fixture/"factory-qa").iterdir():
                shutil.copyfile(entry,folder/entry.name)
            meta=json.loads((folder/"handoff.json").read_text())
            meta["slug"]="sample-two"
            (folder/"handoff.json").write_text(json.dumps(meta))
            queue=json.loads((root/"queue.json").read_text())
            queue["items"].append({**meta,"store_id":None,"submit_allowed":False})
            queue["intake_count"]=2
            (root/"queue.json").write_text(json.dumps(queue))
        return result

    def test_capacity_count_is_checked_for_entire_artifact_before_stage(self):
        # With room for only one package, neither of two may be admitted.
        with (patch("scripts.local_handoff_pull.gh",side_effect=self.fake_two_item_gh),
              patch("scripts.local_handoff_pull.MAX_QUEUED",1)):
            with self.assertRaisesRegex(ValueError,"inbox full"):
                pull(self.root/"inbox")
        self.assertEqual(list((self.root/"inbox").iterdir()),[])

    def test_capacity_bytes_is_checked_for_entire_artifact_before_stage(self):
        # Each item fits individually, but their sum exceeds the quota.
        package_size=(self.fixture/"factory-qa"/"package.msix").stat().st_size
        with (patch("scripts.local_handoff_pull.gh",side_effect=self.fake_two_item_gh),
              patch("scripts.local_handoff_pull.MAX_QUEUED_BYTES",package_size+1)):
            with self.assertRaisesRegex(ValueError,"exceed 2GiB"):
                pull(self.root/"inbox")
        self.assertEqual(list((self.root/"inbox").iterdir()),[])

    def test_two_item_capacity_preflight_allows_exact_idempotent_replay(self):
        with patch("scripts.local_handoff_pull.gh",side_effect=self.fake_two_item_gh):
            self.assertEqual(pull(self.root/"inbox")["new_packages"],2)
            self.assertEqual(pull(self.root/"inbox")["new_packages"],0)
        self.assertEqual(len(list(self.root.joinpath("inbox").rglob("package.msix"))),2)

    def three_d_fixture(self):
        """A real byte-level 3D QA bundle with distinct source and build HEADs."""
        bundle=self.fixture/"factory-3d-qa"
        bundle.mkdir()
        with zipfile.ZipFile(bundle/"package.msix","w") as z:
            z.writestr("AppxManifest.xml",XML)
            z.writestr("AppxBlockMap.xml",b"<BlockMap/>")
            z.writestr("[Content_Types].xml",b"<Types/>")
            z.writestr("main.exe",b"3d executable, QA only")
        payload=(bundle/"package.msix").read_bytes()
        checksum=hashlib.sha256(payload).hexdigest()
        meta={
            "schema_version":1,
            "source_repository":"shihuiarenjinba-png/3d-game-factory",
            "source_sha":SOURCE_SHA,
            "type":"3d-game","slug":"sample-3d",
            "package":"package.msix","status":"QA_UNSIGNED",
            "package_bytes":len(payload),"package_sha256":checksum,
            "local_package_sha256":checksum,
            "request_id":"3d-sample-3d-"+SOURCE_SHA[:12],
            "product_type":"GAME_3D","source_factory":"3d-game-factory",
            "source_branch":"codex/3d-sample-20261101",
            "expected_head_sha":SOURCE_SHA,
            "factory_build_head":"c"*40,
            "identity":{"name":"Demo.App","publisher":"CN=ABC",
                        "version":"1.0.0.0","store_id":"9N12345678",
                        "package_family_name":"Demo.App_abcdefghijklm",
                        "package_sid":"S-1-15-2-1-2-3-4-5-6-7"},
        }
        (bundle/"handoff.json").write_text(json.dumps(meta),encoding="utf-8")
        verified=validate_bundle(bundle,"c"*40)
        queue={"schema_version":1,"mode":"WINDOWS_LOCAL_QA_ONLY",
               "intake_count":1,"items":[{**verified,"submit_allowed":False}]}
        return bundle,checksum,queue

    def fake_3d_gh(self,bundle,checksum,queue):
        def invoke(*args):
            if args[0]=="api":
                return self.fake_gh(*args)
            if args[0]=="run":
                folder=Path(args[-1])
                dest=folder/"packages"/"GAME_3D"/("sample-3d-"+checksum[:12])
                dest.mkdir(parents=True)
                for entry in bundle.iterdir():
                    shutil.copyfile(entry,dest/entry.name)
                (folder/"queue.json").write_text(json.dumps(queue),encoding="utf-8")
                return ""
            raise RuntimeError("unexpected command")
        return invoke

    def test_3d_pull_uses_build_head_not_preidentity_source(self):
        bundle,checksum,queue=self.three_d_fixture()
        with patch("scripts.local_handoff_pull.gh",
                   side_effect=self.fake_3d_gh(bundle,checksum,queue)):
            result=pull(self.root/"inbox")
            self.assertEqual(result["new_packages"],1)
            self.assertEqual(result["products"][0]["product_type"],"GAME_3D")
            self.assertEqual(result["products"][0]["sha256"],checksum)
            self.assertEqual(pull(self.root/"inbox")["new_packages"],0)
        self.assertTrue((self.root/"inbox"/"GAME_3D"/
                         ("sample-3d-"+checksum[:12])/"package.msix").is_file())

    def test_3d_pull_rejects_wrong_build_head_or_claimed_identity(self):
        bundle,checksum,queue=self.three_d_fixture()
        for field,value in (("factory_build_head",SOURCE_SHA),
                            ("claimed_package_sid","S-1-15-2-9-9-9-9-9-9-9"),
                            ("local_package_sha256","0"*64)):
            altered=json.loads(json.dumps(queue))
            altered["items"][0][field]=value
            with self.subTest(field=field):
                with patch("scripts.local_handoff_pull.gh",
                           side_effect=self.fake_3d_gh(bundle,checksum,altered)):
                    with self.assertRaisesRegex(ValueError,"mismatch|provenance"):
                        pull(self.root/"inbox")
                self.assertFalse((self.root/"inbox"/"GAME_3D").exists())

    def test_3d_handoff_rejects_local_hash_claim_different_from_bytes(self):
        bundle,_,_=self.three_d_fixture()
        path=bundle/"handoff.json"
        data=json.loads(path.read_text(encoding="utf-8"))
        data["local_package_sha256"]="f"*64
        path.write_text(json.dumps(data),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"3D local package provenance"):
            validate_bundle(bundle,"c"*40)

if __name__=="__main__":unittest.main()
