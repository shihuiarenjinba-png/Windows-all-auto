import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from all_auto.handoff_bridge import validate_bundle, stage_bundle

SHA="a"*40
BUILD_HEAD="b"*40
XML=b'<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="OkinawaDesktopTools.TestApp" Publisher="CN=ABC" Version="1.0.1.0"/></Package>'

class HandoffBridgeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.source=self.root/"source"
        self.source.mkdir()
        with zipfile.ZipFile(self.source/"package.msix","w") as z:
            z.writestr("AppxManifest.xml",XML)
            z.writestr("AppxBlockMap.xml",b"<BlockMap/>")
            z.writestr("[Content_Types].xml",b"<Types/>")
            z.writestr("app.exe",b"test executable payload")
        blob=(self.source/"package.msix").read_bytes()
        self.info={
          "schema_version":1,"source_repository":"https://github.com/shihuiarenjinba-png/AI-App-Factory",
          "source_sha":SHA,"type":"app","slug":"demo-app",
          "package":"package.msix","status":"QA_UNSIGNED",
          "package_sha256":hashlib.sha256(blob).hexdigest(),"package_bytes":len(blob),
          "identity":{"name":"OkinawaDesktopTools.TestApp","publisher":"CN=ABC","version":"1.0.1.0"}
        }
        self.write_info()

    def write_info(self):
        (self.source/"handoff.json").write_text(json.dumps(self.info),encoding="utf-8")

    def use_3d(self):
        self.info.update({
          "source_repository":"shihuiarenjinba-png/3d-game-factory",
          "type":"3d-game","request_id":"3d-demo-0001","product_type":"GAME_3D",
          "source_factory":"3d-game-factory","source_branch":"codex/3d-product-demo",
          "expected_head_sha":SHA,"factory_build_head":BUILD_HEAD,
          "local_package_sha256":"e"*64,
        })
        self.info["identity"].update({
          "store_id":"9PTEST3D0001",
          "package_family_name":"OkinawaDesktopTools.TestApp_abcdefghijklm",
          "package_sid":"S-1-15-2-1-2-3-4-5-6-7",
        })
        self.write_info()

    def test_genuine_bytes_preserved(self):
        dest=self.root/"queue"
        result=stage_bundle(self.source,dest,SHA)
        self.assertEqual(result["source_sha"],SHA)
        self.assertFalse(result["submit_allowed"])
        items=list(dest.iterdir())
        self.assertEqual(len(items),1)
        self.assertEqual((items[0]/"package.msix").read_bytes(),(self.source/"package.msix").read_bytes())

    def test_idempotent_stage(self):
        dest=self.root/"queue"
        stage_bundle(self.source,dest,SHA)
        stage_bundle(self.source,dest,SHA)
        self.assertEqual(len(list(dest.iterdir())),1)

    @unittest.skipIf(__import__("os").name == "nt", "Windows symlink creation requires privilege")
    def test_symlinked_existing_queue_rejected_even_on_idempotent_replay(self):
        # Previously the fast path returned before checking target.is_symlink().
        actual=self.root/"actual-queue"
        stage_bundle(self.source,actual,SHA)
        link=self.root/"queue-link"
        link.symlink_to(actual,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,"unsafe destination"):
            stage_bundle(self.source,link,SHA)
        self.assertEqual(len(list(actual.iterdir())),1)

    @unittest.skipIf(__import__("os").name == "nt", "Windows symlink creation requires privilege")
    def test_symlinked_empty_queue_rejected_before_copy(self):
        actual=self.root/"actual-queue"
        actual.mkdir()
        link=self.root/"queue-link"
        link.symlink_to(actual,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,"unsafe destination"):
            stage_bundle(self.source,link,SHA)
        self.assertEqual(list(actual.iterdir()),[])

    def test_identical_msix_from_another_factory_is_not_reused(self):
        dest=self.root/"queue"
        stage_bundle(self.source,dest,SHA)
        original=(next(dest.iterdir())/"handoff.json").read_text(encoding="utf-8")
        # Both Factory lanes can independently produce identical MSIX bytes.
        self.info["source_repository"]="https://github.com/shihuiarenjinba-png/AI-Game-Factory"
        self.info["type"]="game"
        self.write_info()
        with self.assertRaisesRegex(ValueError,"provenance"):
            stage_bundle(self.source,dest,SHA)
        self.assertEqual((next(dest.iterdir())/"handoff.json").read_text(encoding="utf-8"),original)

    def test_identical_msix_from_another_commit_is_not_reused(self):
        dest=self.root/"queue"
        stage_bundle(self.source,dest)
        self.info["source_sha"]="b"*40
        self.write_info()
        with self.assertRaisesRegex(ValueError,"provenance"):
            stage_bundle(self.source,dest)
        self.assertEqual(len(list(dest.iterdir())),1)

    def test_changed_source_sha_rejected(self):
        with self.assertRaisesRegex(ValueError,"provenance"):
            validate_bundle(self.source,"b"*40)

    def test_tampered_package_rejected(self):
        with (self.source/"package.msix").open("ab") as f:f.write(b"mutated")
        with self.assertRaisesRegex(ValueError,"hash mismatch"):
            validate_bundle(self.source,SHA)

    def test_3d_factory_requires_distinct_3d_game_type(self):
        self.use_3d()
        result=validate_bundle(self.source,BUILD_HEAD)
        self.assertEqual(result["type"],"3d-game")
        self.assertEqual(result["local_action"],"WINDOWS_INSTALL_UI_QA_ONLY")
        self.assertFalse(result["submit_allowed"])
        for wrong in ("game","app"):
            with self.subTest(wrong=wrong):
                self.info["type"]=wrong
                self.write_info()
                with self.assertRaisesRegex(ValueError,"factory / product type"):
                    validate_bundle(self.source,BUILD_HEAD)

    def test_normal_game_factory_cannot_claim_3d_type(self):
        self.info["source_repository"]="https://github.com/shihuiarenjinba-png/AI-Game-Factory"
        self.info["type"]="game"
        self.write_info()
        self.assertEqual(validate_bundle(self.source,SHA)["type"],"game")
        self.info["type"]="3d-game"
        self.write_info()
        with self.assertRaisesRegex(ValueError,"factory / product type"):
            validate_bundle(self.source,SHA)

    def test_3d_bundle_stages_with_separate_type(self):
        self.use_3d()
        result=stage_bundle(self.source,self.root/"queue",BUILD_HEAD)
        self.assertEqual(result["type"],"3d-game")
        self.assertEqual(result["request_id"],"3d-demo-0001")
        self.assertEqual(result["product_type"],"GAME_3D")
        self.assertEqual(result["factory_build_head"],BUILD_HEAD)
        self.assertEqual(result["local_package_sha256"],"e"*64)
        self.assertFalse(result["submit_allowed"])
        self.assertEqual(len(list((self.root/"queue").iterdir())),1)

    def test_3d_actions_head_and_request_are_strict(self):
        self.use_3d()
        with self.assertRaisesRegex(ValueError,"Actions head SHA"):
            validate_bundle(self.source,"c"*40)
        self.info.pop("request_id")
        self.write_info()
        with self.assertRaisesRegex(ValueError,"request_id"):
            validate_bundle(self.source,BUILD_HEAD)

    def test_wrong_product_type_rejected(self):
        self.info["type"]="game"
        self.write_info()
        with self.assertRaisesRegex(ValueError,"factory / product type"):
            validate_bundle(self.source,SHA)

    def test_wrong_embedded_publisher_rejected(self):
        self.info["identity"]["publisher"]="CN=wrong"
        self.write_info()
        with self.assertRaisesRegex(ValueError,"embedded identity"):
            validate_bundle(self.source,SHA)

    def test_extra_file_rejected(self):
        (self.source/"secret.txt").write_text("not allowed")
        with self.assertRaisesRegex(ValueError,"only handoff"):
            validate_bundle(self.source,SHA)

    def test_duplicate_payload_names_are_rejected_even_with_matching_hash(self):
        # Metadata parts can be unique while executable members are ambiguous.
        # A checksum only proves the duplicate-member ZIP was transferred intact.
        for first, second in (("app.exe", "app.exe"), ("app.exe", "APP.EXE")):
            with self.subTest(first=first, second=second):
                with zipfile.ZipFile(self.source/"package.msix", "w") as archive:
                    archive.writestr("AppxManifest.xml", XML)
                    archive.writestr("AppxBlockMap.xml", b"<BlockMap/>")
                    archive.writestr("[Content_Types].xml", b"<Types/>")
                    archive.writestr(first, b"original payload")
                    archive.writestr(second, b"conflicting payload")
                blob=(self.source/"package.msix").read_bytes()
                self.info["package_sha256"]=hashlib.sha256(blob).hexdigest()
                self.info["package_bytes"]=len(blob)
                self.write_info()
                with self.assertRaisesRegex(ValueError, "duplicate MSIX ZIP member"):
                    validate_bundle(self.source, SHA)

    def test_manifest_only_zip_with_matching_hash_is_rejected(self):
        # A valid hash proves byte consistency, not that a ZIP is an MSIX.
        with zipfile.ZipFile(self.source/"package.msix","w") as z:
            z.writestr("AppxManifest.xml",XML)
            z.writestr("app.exe",b"payload")
        blob=(self.source/"package.msix").read_bytes()
        self.info["package_sha256"]=hashlib.sha256(blob).hexdigest()
        self.info["package_bytes"]=len(blob)
        self.write_info()
        with self.assertRaisesRegex(ValueError,"required MSIX metadata"):
            validate_bundle(self.source,SHA)

    def test_wrong_blockmap_root_is_rejected(self):
        with zipfile.ZipFile(self.source/"package.msix","w") as z:
            z.writestr("AppxManifest.xml",XML)
            z.writestr("AppxBlockMap.xml",b"<NotABlockMap/>")
            z.writestr("[Content_Types].xml",b"<Types/>")
            z.writestr("app.exe",b"payload")
        blob=(self.source/"package.msix").read_bytes()
        self.info["package_sha256"]=hashlib.sha256(blob).hexdigest()
        self.info["package_bytes"]=len(blob)
        self.write_info()
        with self.assertRaisesRegex(ValueError,"invalid MSIX metadata root"):
            validate_bundle(self.source,SHA)

    def test_bad_zip_rejected(self):
        (self.source/"package.msix").write_bytes(b"not-a-package")
        with self.assertRaisesRegex(ValueError,"readable MSIX"):
            validate_bundle(self.source,SHA)

    def test_no_store_approval_or_guess(self):
        result=validate_bundle(self.source,SHA)
        self.assertIsNone(result["store_id"])
        self.assertFalse(result["security_confirmed"])
        self.assertFalse(result["price_approved"])

    def test_traversal_zip_entry_rejected(self):
        with zipfile.ZipFile(self.source/"package.msix","a") as z:z.writestr("../evil.txt",b"bad")
        with self.assertRaisesRegex(ValueError,"unsafe MSIX ZIP entry"):
            validate_bundle(self.source,SHA)


    def set_identity_return_bundle(self):
        original="b"*40
        self.info.update({
            "source_sha":original,"expected_head_sha":original,
            "factory_head_sha":SHA,"request_id":"app-request-1234",
            "product_type":"APP","source_factory":"AI-App-Factory",
            "source_branch":"codex/factory-autoloop-20261026",
            "display_name":"Sample App","store_id":"9PTESTING",
            "prebuilt_exe_sha256":hashlib.sha256(b"test executable payload").hexdigest(),
        })
        xml=(b'<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
             b'<Identity Name="OkinawaDesktopTools.TestApp" Publisher="CN=ABC" Version="1.0.1.0"/>'
             b'<Applications><Application Executable="app.exe"/></Applications></Package>')
        with zipfile.ZipFile(self.source/"package.msix","w") as z:
            z.writestr("AppxManifest.xml",xml)
            z.writestr("AppxBlockMap.xml",b"<BlockMap/>")
            z.writestr("[Content_Types].xml",b"<Types/>")
            z.writestr("app.exe",b"test executable payload")
        blob=(self.source/"package.msix").read_bytes()
        self.info["package_sha256"]=hashlib.sha256(blob).hexdigest()
        self.info["package_bytes"]=len(blob)
        self.write_info()

    def test_identity_return_preserves_original_source_sha_through_local_qa(self):
        self.set_identity_return_bundle()
        result=stage_bundle(self.source,self.root/"queue",SHA)
        self.assertEqual(result["source_sha"],"b"*40)
        self.assertEqual(result["factory_head_sha"],SHA)
        self.assertEqual(result["request_id"],"app-request-1234")
        self.assertEqual(result["claimed_store_id"],"9PTESTING")
        self.assertIsNone(result["store_id"])
        self.assertFalse(result["submit_allowed"])

    def test_identity_return_requires_actual_prebuilt_exe_payload(self):
        self.set_identity_return_bundle()
        self.info["prebuilt_exe_sha256"]="c"*64
        self.write_info()
        with self.assertRaisesRegex(ValueError,"EXE payload SHA"):
            validate_bundle(self.source,SHA)

    def test_identity_return_rejects_wrong_expected_head(self):
        self.set_identity_return_bundle()
        self.info["expected_head_sha"]="a"*40
        self.write_info()
        with self.assertRaisesRegex(ValueError,"immutable contract"):
            validate_bundle(self.source,SHA)

    def test_identity_return_rejects_wrong_actions_head(self):
        self.set_identity_return_bundle()
        with self.assertRaisesRegex(ValueError,"Actions head SHA"):
            validate_bundle(self.source,"c"*40)


    def write_approved_identity(self, approved_identity, transport):
        raw=json.dumps(approved_identity,separators=(",",":")).encode("utf-8")
        (self.source/"approved-identity.json").write_bytes(raw)
        transport["approved_identity_file_sha"]=hashlib.sha1(
            b"blob "+str(len(raw)).encode("ascii")+b"\0"+raw
        ).hexdigest()

    def transport_receipts(self, version_gate="PASS"):
        # Synthetic values exercise the exact intake contract; they are not product approval.
        self.set_identity_return_bundle()
        source=self.info["source_sha"]
        self.info["factory_head_sha"]=source
        self.info["expected_head_sha"]=source
        self.write_info()
        digest=self.info["package_sha256"]
        verifier="supervisor-fixture"
        evidence="https://partner.microsoft.com/dashboard/products/"+self.info["store_id"]+"/identity"
        approved_identity={
            "schema_version":"1.0","reviewed":True,"source":"partner_center",
            "request_id":self.info["request_id"],"product_type":"APP",
            "source_factory":"AI-App-Factory",
            "source_repository":self.info["source_repository"].removeprefix("https://github.com/"),
            "source_branch":self.info["source_branch"],
            "source_sha":source,"expected_head_sha":source,
            "store_id":self.info["store_id"],
            "name":self.info["identity"]["name"],
            "publisher":self.info["identity"]["publisher"],
            "version":self.info["identity"]["version"],
            "package_version_gate":version_gate,"operator_verified":True,
            "verified_by":verifier,"evidence_url":evidence,
        }
        transport={
            "schema_version":1,"status":"SOURCE_BOUND_VERSION_APPROVED",
            "source_sha":source,"expected_head_sha":source,"factory_head_sha":source,
            "source_repository":self.info["source_repository"],
            "product_type":"APP","source_factory":"AI-App-Factory",
            "package_sha256":digest,"package_bytes":self.info["package_bytes"],
            "identity":self.info["identity"],"approval_source":"partner_center",
            "package_version_gate":version_gate,"package_version":self.info["identity"]["version"],
            "operator_verified":True,
            "store_submission_allowed":False,"certification_allowed":False,"publish_allowed":False,
            "verified_by":verifier,"evidence_url":evidence,
            "request_id":self.info["request_id"],"source_branch":self.info["source_branch"],
            "store_id":self.info["store_id"],"display_name":self.info["display_name"],
            "prebuilt_exe_sha256":self.info["prebuilt_exe_sha256"],
        }
        self.write_approved_identity(approved_identity,transport)
        custody={
            "status":"CUSTODY_VERIFIED_ONLY","e2e_pass":False,
            "source_sha":source,"msix_sha256":digest,
            "run_id":123456,"artifact_id":654321,
            "repository":"shihuiarenjinba-png/AI-App-Factory",
            "archive_sha256":"d"*64,
        }
        return transport,custody

    def write_transport_receipts(self, transport, custody):
        (self.source/"transport_receipt.json").write_text(json.dumps(transport),encoding="utf-8")
        (self.source/"github-custody.json").write_text(json.dumps(custody),encoding="utf-8")

    def test_app_transport_rejects_unpaired_partner_center_and_custody_receipts(self):
        self.set_identity_return_bundle()
        (self.source/"transport_receipt.json").write_text(
            json.dumps({"schema_version":1}),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"central identity and custody receipts must be paired"):
            validate_bundle(self.source,"a"*40)

    def test_app_transport_rejects_version_gate_hold_at_production_boundary(self):
        transport,custody=self.transport_receipts(version_gate="HOLD")
        self.write_transport_receipts(transport,custody)
        with self.assertRaisesRegex(ValueError,"source-bound Partner Center transport receipt mismatch"):
            validate_bundle(self.source,self.info["source_sha"])

    def test_app_transport_rejects_missing_approved_identity_file(self):
        transport,custody=self.transport_receipts()
        (self.source/"approved-identity.json").unlink()
        self.write_transport_receipts(transport,custody)
        with self.assertRaisesRegex(ValueError,"approved-identity.json"):
            validate_bundle(self.source,self.info["source_sha"])

    def test_app_transport_rejects_approved_identity_blob_sha_mismatch(self):
        transport,custody=self.transport_receipts()
        transport["approved_identity_file_sha"]="c"*40
        self.write_transport_receipts(transport,custody)
        with self.assertRaisesRegex(ValueError,"approved Identity file SHA mismatch"):
            validate_bundle(self.source,self.info["source_sha"])

    def test_app_transport_rejects_stale_approved_identity_source(self):
        transport,custody=self.transport_receipts()
        approved=json.loads((self.source/"approved-identity.json").read_text(encoding="utf-8"))
        approved["source_sha"]="c"*40
        approved["expected_head_sha"]="c"*40
        self.write_approved_identity(approved,transport)
        self.write_transport_receipts(transport,custody)
        with self.assertRaisesRegex(ValueError,"approved Identity file does not bind current source"):
            validate_bundle(self.source,self.info["source_sha"])

    def test_app_transport_rejects_approved_identity_version_mismatch(self):
        transport,custody=self.transport_receipts()
        approved=json.loads((self.source/"approved-identity.json").read_text(encoding="utf-8"))
        approved["version"]="2.0.0.0"
        self.write_approved_identity(approved,transport)
        self.write_transport_receipts(transport,custody)
        with self.assertRaisesRegex(ValueError,"approved Identity file does not bind current source"):
            validate_bundle(self.source,self.info["source_sha"])

    def test_app_transport_rejects_unverified_operator(self):
        transport,custody=self.transport_receipts()
        transport["operator_verified"]=False
        approved=json.loads((self.source/"approved-identity.json").read_text(encoding="utf-8"))
        approved["operator_verified"]=False
        self.write_approved_identity(approved,transport)
        self.write_transport_receipts(transport,custody)
        with self.assertRaisesRegex(ValueError,"source-bound Partner Center transport receipt mismatch"):
            validate_bundle(self.source,self.info["source_sha"])

    def test_app_transport_rejects_evidence_for_another_store_id(self):
        transport,custody=self.transport_receipts()
        wrong="https://partner.microsoft.com/dashboard/products/9POTHERID/identity"
        transport["evidence_url"]=wrong
        approved=json.loads((self.source/"approved-identity.json").read_text(encoding="utf-8"))
        approved["evidence_url"]=wrong
        self.write_approved_identity(approved,transport)
        self.write_transport_receipts(transport,custody)
        with self.assertRaisesRegex(ValueError,"does not identify this Store product"):
            validate_bundle(self.source,self.info["source_sha"])

    def test_app_transport_accepts_source_bound_identity_and_custody_but_never_store_authorizes(self):
        transport,custody=self.transport_receipts(version_gate="PASS")
        self.write_transport_receipts(transport,custody)
        result=stage_bundle(self.source,self.root/"queue",self.info["source_sha"])
        self.assertEqual(result["source_sha"],self.info["source_sha"])
        self.assertEqual(result["transport_receipt"]["package_version_gate"],"PASS")
        self.assertEqual(result["approved_identity_file_sha"],transport["approved_identity_file_sha"])
        self.assertEqual(result["github_artifact_custody"]["status"],"CUSTODY_VERIFIED_ONLY")
        self.assertIs(result["github_artifact_custody"]["e2e_pass"],False)
        self.assertEqual(len(list((self.root/"queue").rglob("approved-identity.json"))),1)
        self.assertIsNone(result["store_id"])
        self.assertFalse(result["submit_allowed"])

if __name__== "__main__":
    unittest.main()
