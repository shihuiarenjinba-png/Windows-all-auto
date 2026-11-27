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
from scripts.github_artifact_custody import verify_queue_artifact_custody
from scripts.local_handoff_pull import pull, recent_artifacts

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
            paths=[(self.artifact_dir/"queue.json","queue.json")]
            paths.extend(
                (path,path.relative_to(self.artifact_dir).as_posix())
                for path in sorted((self.artifact_dir/"packages").rglob("*"))
                if path.is_file()
            )
            for path,archive_name in paths:
                # Artifact IDs are immutable; test archive bytes must also be
                # deterministic across Windows replays (avoid wall-clock ZIP timestamps).
                info=zipfile.ZipInfo(archive_name,date_time=(2020,1,1,0,0,0))
                info.compress_type=zipfile.ZIP_DEFLATED
                info.create_system=3
                info.external_attr=0o100644 << 16
                z.writestr(info,path.read_bytes())
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
        with self.assertRaisesRegex(ValueError,"authorize Store submission"):
            self.pull_fake(self.root/"inbox")

    def test_corrupt_queue_count_rejected(self):
        self.q["intake_count"]=2
        with self.assertRaisesRegex(ValueError,"Invalid queue count"):
            self.pull_fake(self.root/"inbox")

    def test_queue_cannot_underreport_package_size(self):
        # A forged small size must not bypass the 2 GiB quota.
        self.q["items"][0]["package_bytes"]=1
        with self.assertRaisesRegex(ValueError,"Queue metadata mismatch: package_bytes"):
            self.pull_fake(self.root/"inbox")
        self.assertEqual(list((self.root/"inbox").iterdir()),[])

    def test_queue_cannot_replace_verified_identity(self):
        self.q["items"][0]["identity"]["publisher"]="CN=UNVERIFIED"
        with self.assertRaisesRegex(ValueError,"Queue metadata mismatch: identity"):
            self.pull_fake(self.root/"inbox")
        self.assertEqual(list((self.root/"inbox").iterdir()),[])

    def test_queue_cannot_claim_store_id_or_approval(self):
        self.q["items"][0]["store_id"]="UNVERIFIED-STORE-ID"
        with self.assertRaisesRegex(ValueError,"must not assign a Store ID"):
            self.pull_fake(self.root/"inbox")
        self.q["items"][0]["store_id"]=None
        self.q["items"][0]["security_confirmed"]=True
        with self.assertRaisesRegex(ValueError,"must not assert Store approvals"):
            self.pull_fake(self.root/"inbox")



    def test_identity_return_queue_bundle_accepts_paired_approved_identity_receipts(self):
        bundle = self.fixture / "factory-qa"
        (bundle / "transport_receipt.json").write_text('{"schema_version":1}', encoding="utf-8")
        (bundle / "github-custody.json").write_text('{"status":"CUSTODY_VERIFIED_ONLY"}', encoding="utf-8")
        (bundle / "approved-identity.json").write_text('{"reviewed":true}', encoding="utf-8")
        self.build_artifact()
        fetch_json, fetch_bytes = self.fake_clients("test-token")
        result = verify_queue_artifact_custody({
            "repository": "shihuiarenjinba-png/Windows-all-auto",
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "artifact_name": self.artifact_name,
            "run_head_sha": self.run_head_sha,
        }, self.artifact_dir, fetch_json, fetch_bytes)
        self.assertEqual(result["status"], "CUSTODY_VERIFIED_ONLY")
        self.assertFalse(result["e2e_pass"])
        self.assertEqual(result["packages"][0]["package_sha256"], self.checksum)
        self.assertEqual(result["packages"][0]["local_sha256"], self.checksum)

    def test_identity_return_queue_bundle_rejects_partial_receipt_trio(self):
        bundle = self.fixture / "factory-qa"
        (bundle / "approved-identity.json").write_text('{"reviewed":true}', encoding="utf-8")
        self.build_artifact()
        fetch_json, fetch_bytes = self.fake_clients("test-token")
        result = verify_queue_artifact_custody({
            "repository": "shihuiarenjinba-png/Windows-all-auto",
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "artifact_name": self.artifact_name,
            "run_head_sha": self.run_head_sha,
        }, self.artifact_dir, fetch_json, fetch_bytes)
        self.assertEqual(result["status"], "HOLD")
        self.assertEqual(result["reason"], "LOCAL_PACKAGE_BUNDLE_INVALID")

    def test_identity_return_queue_bundle_holds_oversized_approved_identity(self):
        bundle = self.fixture / "factory-qa"
        (bundle / "transport_receipt.json").write_text('{"schema_version":1}', encoding="utf-8")
        (bundle / "github-custody.json").write_text('{"status":"CUSTODY_VERIFIED_ONLY"}', encoding="utf-8")
        (bundle / "approved-identity.json").write_text("x" * (32 * 1024 + 1), encoding="utf-8")
        self.build_artifact()
        fetch_json, fetch_bytes = self.fake_clients("test-token")
        result = verify_queue_artifact_custody({
            "repository": "shihuiarenjinba-png/Windows-all-auto",
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "artifact_name": self.artifact_name,
            "run_head_sha": self.run_head_sha,
        }, self.artifact_dir, fetch_json, fetch_bytes)
        self.assertEqual(result["status"], "HOLD")
        self.assertEqual(result["reason"], "APPROVED_IDENTITY_OVERSIZED")



class CustodyPullCheckerIntegrationTests(unittest.TestCase):
    """Disposable QA fixture only; never a real product or Windows E2E claim."""

    def setUp(self):
        import hashlib
        import io

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source_sha = "a" * 40
        self.run_id = 88123
        self.artifact_id = 77123
        self.artifact_name = "verified-msix-local-qa-qa-fixture-only-77123"
        self.identity = {
            "name": "QA.Fixture.Only",
            "publisher": "CN=QA_FIXTURE_ONLY_NOT_PRODUCT",
            "version": "1.0.0.0",
        }

        manifest = (
            b'<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
            b'<Identity Name="QA.Fixture.Only" Publisher="CN=QA_FIXTURE_ONLY_NOT_PRODUCT" '
            b'Version="1.0.0.0"/></Package>'
        )
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in (
                ("AppxManifest.xml", manifest),
                ("AppxBlockMap.xml", b'<BlockMap xmlns="http://schemas.microsoft.com/appx/2010/blockmap"/>'),
                ("[Content_Types].xml", b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'),
                ("main.exe", b"QA_FIXTURE_ONLY_NOT_PRODUCT executable bytes"),
            ):
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        package_bytes = package.getvalue()
        self.package_sha256 = hashlib.sha256(package_bytes).hexdigest()

        self.handoff = {
            "schema_version": 1,
            "source_repository": "https://github.com/shihuiarenjinba-png/AI-Game-Factory",
            "source_sha": self.source_sha,
            "type": "game",
            "slug": "qa-fixture-only",
            "package": "package.msix",
            "status": "QA_UNSIGNED",
            "package_bytes": len(package_bytes),
            "package_sha256": self.package_sha256,
            "identity": self.identity,
            "request_id": "qa-fixture-only-" + self.source_sha[:12],
            "product_type": "GAME",
            "source_factory": "AI-Game-Factory",
            "source_branch": "codex/qa-fixture-only",
            "expected_head_sha": self.source_sha,
            "store_id": "9PQA00000000",
            "signature_status": "UNSIGNED",
            "qa_fixture_marker": "QA_FIXTURE_ONLY_NOT_PRODUCT",
        }
        self.queue_item = {
            **self.handoff,
            "store_id": None,
            "claimed_store_id": self.handoff["store_id"],
            "contract_status": "IMMUTABLE_QA_ONLY",
            "submit_allowed": False,
            "security_confirmed": False,
            "price_approved": False,
        }
        self.queue = {
            "schema_version": 1,
            "mode": "WINDOWS_LOCAL_QA_ONLY",
            "intake_count": 1,
            "items": [self.queue_item],
            "store_submissions": 0,
            "qa_fixture_marker": "QA_FIXTURE_ONLY_NOT_PRODUCT",
        }
        self.artifact_dir = self.root / "artifact"
        self._build_artifact()

    def _build_artifact(self, partial_receipt=False):
        import hashlib
        import io
        import shutil

        if self.artifact_dir.exists():
            shutil.rmtree(self.artifact_dir)
        package_dir = self.artifact_dir / "packages" / relative_package_path(self.queue_item)
        package_dir.mkdir(parents=True)
        package = io.BytesIO()
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            manifest = (
                b'<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
                b'<Identity Name="QA.Fixture.Only" Publisher="CN=QA_FIXTURE_ONLY_NOT_PRODUCT" '
                b'Version="1.0.0.0"/></Package>'
            )
            for name, data in (
                ("AppxManifest.xml", manifest),
                ("AppxBlockMap.xml", b'<BlockMap xmlns="http://schemas.microsoft.com/appx/2010/blockmap"/>'),
                ("[Content_Types].xml", b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'),
                ("main.exe", b"QA_FIXTURE_ONLY_NOT_PRODUCT executable bytes"),
            ):
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        package_bytes = package.getvalue()
        self.package_sha256 = hashlib.sha256(package_bytes).hexdigest()
        self.handoff["package_bytes"] = len(package_bytes)
        self.handoff["package_sha256"] = self.package_sha256
        self.queue_item["package_bytes"] = len(package_bytes)
        self.queue_item["package_sha256"] = self.package_sha256
        (package_dir / "handoff.json").write_text(
            json.dumps(self.handoff, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        (package_dir / "package.msix").write_bytes(package_bytes)
        if partial_receipt:
            (package_dir / "transport_receipt.json").write_text(
                '{"qa_fixture_marker":"QA_FIXTURE_ONLY_NOT_PRODUCT"}', encoding="utf-8"
            )

        queue_bytes = json.dumps(
            self.queue, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        (self.artifact_dir / "queue.json").write_bytes(queue_bytes)
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, "w", zipfile.ZIP_DEFLATED) as archive:
            paths = [(self.artifact_dir / "queue.json", "queue.json")]
            paths.extend(
                (path, path.relative_to(self.artifact_dir).as_posix())
                for path in sorted((self.artifact_dir / "packages").rglob("*"))
                if path.is_file()
            )
            for path, archive_name in paths:
                info = zipfile.ZipInfo(archive_name, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        self.archive_bytes = archive_bytes.getvalue()
        archive_sha = hashlib.sha256(self.archive_bytes).hexdigest()
        self.run_response = {
            "name": "Factory MSIX intake and local QA handoff",
            "path": ".github/workflows/factory-msix-intake.yml",
            "status": "completed",
            "conclusion": "success",
            "event": "schedule",
            "head_sha": self.source_sha,
            "head_branch": "codex/qa-fixture-only",
            "head_repository": {"full_name": "shihuiarenjinba-png/Windows-all-auto"},
        }
        self.artifact_response = {
            "id": self.artifact_id,
            "name": self.artifact_name,
            "expired": False,
            "digest": "sha256:" + archive_sha,
            "workflow_run": {"id": self.run_id, "head_sha": self.source_sha},
        }

    def _pull(self, target, run_head_sha=None, bad_digest=False, partial_receipt=False):
        import os
        import shutil
        from unittest.mock import patch

        self._build_artifact(partial_receipt=partial_receipt)
        if bad_digest:
            self.artifact_response["digest"] = "sha256:" + ("0" * 64)
        artifact = {
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "artifact_name": self.artifact_name,
            "run_head_sha": run_head_sha or self.source_sha,
        }

        def fake_gh(*args):
            if args[:2] != ("run", "download"):
                raise AssertionError("QA fixture must not call an external GitHub CLI command")
            shutil.copytree(self.artifact_dir, Path(args[-1]), dirs_exist_ok=True)
            return ""

        def fake_clients(token):
            if token != "qa-fixture-token":
                raise AssertionError("unexpected fixture token")

            def fetch_json(url):
                if url.endswith("/runs/" + str(self.run_id)):
                    return self.run_response
                if url.endswith("/artifacts/" + str(self.artifact_id)):
                    return self.artifact_response
                raise AssertionError("unexpected GitHub API URL")

            def fetch_bytes(url):
                if url.endswith("/artifacts/" + str(self.artifact_id) + "/zip"):
                    return self.archive_bytes
                raise AssertionError("unexpected GitHub artifact URL")

            return fetch_json, fetch_bytes

        with patch("scripts.local_handoff_pull.recent_artifacts", return_value=[artifact]), \
             patch("scripts.local_handoff_pull.gh", side_effect=fake_gh), \
             patch("scripts.local_handoff_pull.github_clients", side_effect=fake_clients), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "qa-fixture-token"}, clear=True):
            return pull(target)

    def test_qa_fixture_only_flows_custody_pull_checker_and_idempotent_replay(self):
        import json
        from scripts.local_checker_queue import check_local_queue

        inbox = self.root / "inbox"
        first = self._pull(inbox)
        receipt_path = inbox / ".artifact-custody" / (str(self.artifact_id) + ".json")
        receipt_before = receipt_path.read_bytes()
        second = self._pull(inbox)
        receipt_after = receipt_path.read_bytes()

        self.assertEqual(first["new_packages"], 1)
        self.assertEqual(second["new_packages"], 0)
        self.assertEqual(first["submitted_to_store"], 0)
        self.assertEqual(second["submitted_to_store"], 0)
        self.assertEqual(receipt_before, receipt_after)
        self.assertEqual(len(list((inbox / "GAME").glob("*/package.msix"))), 1)
        custody = json.loads(receipt_after.decode("utf-8"))
        self.assertEqual(custody["status"], "CUSTODY_VERIFIED_ONLY")
        self.assertFalse(custody["e2e_pass"])
        self.assertIn("qa-fixture-only", custody["artifact_name"])
        self.assertEqual(custody["packages"][0]["package_sha256"], self.package_sha256)
        self.assertEqual(custody["packages"][0]["local_sha256"], self.package_sha256)
        self.assertEqual(custody["packages"][0]["local_pull_status"], "VERIFIED")

        checker = self.root / "checker"
        checker.mkdir()
        (checker / "run.py").write_text(
            "import hashlib, json, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv\n"
            "package = Path(args[args.index('--msix') + 1])\n"
            "report = Path(args[args.index('--report') + 1])\n"
            "report.write_text(json.dumps({'verdict':'NEEDS_REVIEW',"
            "'fixture_marker':'QA_FIXTURE_ONLY_NOT_PRODUCT',"
            "'package_sha256':hashlib.sha256(package.read_bytes()).hexdigest()}),"
            "encoding='utf-8')\n"
            "sys.exit(1)\n",
            encoding="utf-8",
        )
        result = check_local_queue(inbox, checker, self.root / "reports")
        self.assertEqual(result["status"], "HOLD")
        self.assertEqual(result["checked"], 1)
        self.assertFalse(result["e2e_pass"])
        self.assertEqual(result["submitted_to_store"], 0)
        checked = result["results"][0]
        self.assertEqual(checked["checker_verdict"], "NEEDS_REVIEW")
        self.assertEqual(checked["request_id"], self.handoff["request_id"])
        self.assertEqual(checked["source_sha"], self.source_sha)
        self.assertEqual(checked["package_sha256"], self.package_sha256)
        self.assertEqual(checked["local_artifact_ids"], [self.artifact_id])
        self.assertEqual(checked["local_artifact_custody"], "VERIFIED")
        self.assertEqual(checked["local_gui_qa"], "NOT_RUN")
        self.assertFalse(checked["e2e_pass"])
        self.assertFalse(checked["submitted_to_store"])
        report = json.loads((self.root / "reports" / checked["checker_report"]).read_text(encoding="utf-8"))
        self.assertEqual(report["checker"]["fixture_marker"], "QA_FIXTURE_ONLY_NOT_PRODUCT")
        self.assertEqual(report["checker"]["package_sha256"], self.package_sha256)
        self.assertEqual(report["receipt"]["status"], "HOLD")

    def test_wrong_run_head_fails_closed_before_local_staging(self):
        inbox = self.root / "wrong-head-inbox"
        with self.assertRaisesRegex(ValueError, "RUN_HEAD_OR_STATUS_MISMATCH"):
            self._pull(inbox, run_head_sha="b" * 40)
        self.assertFalse((inbox / "GAME").exists())
        self.assertFalse((inbox / ".artifact-custody").exists())

    def test_archive_digest_mismatch_fails_closed_before_local_staging(self):
        inbox = self.root / "wrong-digest-inbox"
        with self.assertRaisesRegex(ValueError, "ARTIFACT_ARCHIVE_DIGEST_MISMATCH"):
            self._pull(inbox, bad_digest=True)
        self.assertFalse((inbox / "GAME").exists())
        self.assertFalse((inbox / ".artifact-custody").exists())

    def test_partial_identity_receipt_trio_fails_closed_before_local_staging(self):
        inbox = self.root / "partial-receipt-inbox"
        with self.assertRaisesRegex(ValueError, "LOCAL_PACKAGE_BUNDLE_INVALID"):
            self._pull(inbox, partial_receipt=True)
        self.assertFalse((inbox / "GAME").exists())
        self.assertFalse((inbox / ".artifact-custody").exists())


if __name__=="__main__":unittest.main()
