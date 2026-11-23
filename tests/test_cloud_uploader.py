from __future__ import annotations
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from uploader.core import JobLedger, UploadError, process_job, validate_config, verify_file

CONFIG = {"schema_version":1,"product_name":"Data Contract Auditor","product_id":"9PDL4ZWSB45P","submission_id":"1152921505702212222","repository":"shihuiarenjinba-png/csv-import-validator","ref":"107e59f2cbcde9c6ca88cf1aaf3d52262004e6e0","path":"pkg.msix","version":"1.0.0.0","destination":"microsoft_partner_center_existing_draft","identity_name":"OkinawaDesktopTools.DataContractAuditor","publisher":"CN=46263F21-A700-41DB-8C9B-114C22FB82FC","architecture":"x64","upload_approved":False}

def make_msix(path, data=b"synthetic-msix"):
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("AppxManifest.xml", '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="OkinawaDesktopTools.DataContractAuditor" Publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC" Version="1.0.0.0" ProcessorArchitecture="x64" /></Package>''')
        package.writestr("payload.bin", data)

class CloudUploaderTests(unittest.TestCase):
    def test_hash_and_target_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"pkg.msix"; make_msix(p)
            job=verify_file(CONFIG,p,expected_sha256=hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertEqual((job.product_id,job.submission_id),(CONFIG["product_id"],CONFIG["submission_id"]))
    def test_bad_hash_and_destination_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"pkg.msix"; make_msix(p)
            with self.assertRaisesRegex(UploadError,"SHA-256"): verify_file(CONFIG,p,expected_sha256="0"*64)
            with self.assertRaisesRegex(UploadError,"destination"): validate_config({**CONFIG,"destination":"new_submission"})
    def test_dry_run_duplicate_is_reconciled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            with JobLedger(root/"ledger.sqlite3") as ledger:
                a=process_job(CONFIG,p,ledger); b=process_job(CONFIG,p,ledger)
            self.assertEqual(a["status"],"DRY_RUN"); self.assertEqual(b["status"],"DRY_RUN_ALREADY_DONE")
    def test_dry_run_does_not_block_later_approved_live_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            config={**CONFIG,"upload_approved":True}; digest=hashlib.sha256(p.read_bytes()).hexdigest(); called=[]
            with JobLedger(root/"ledger.sqlite3") as ledger:
                process_job(config,p,ledger,dry_run=True)
                result=process_job(config,p,ledger,expected_sha256=digest,dry_run=False,
                                   live_adapter=lambda *_:(called.append(True) or {"partner_center_confirmed":True}))
            self.assertEqual(result["status"],"SUCCEEDED")
            self.assertEqual(called,[True])
    def test_live_msix_fails_closed_without_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            with JobLedger(root/"ledger.sqlite3") as ledger:
                with self.assertRaisesRegex(UploadError,"not approved"): process_job(CONFIG,p,ledger,dry_run=False)
    def test_unconfirmed_result_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            with JobLedger(root/"ledger.sqlite3") as ledger:
                with self.assertRaisesRegex(UploadError,"did not confirm"):
                    process_job({**CONFIG,"upload_approved":True},p,ledger,expected_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),dry_run=False,live_adapter=lambda *_:{"http_accepted":True})
                self.assertEqual(ledger.db.execute("SELECT status FROM uploads").fetchone()[0],"UNKNOWN")

    def test_interrupted_upload_is_reconciled_before_safe_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            config={**CONFIG,"upload_approved":True}; digest=hashlib.sha256(p.read_bytes()).hexdigest()
            with JobLedger(root/"ledger.sqlite3") as ledger:
                with self.assertRaisesRegex(UploadError,"ambiguous"):
                    process_job(config,p,ledger,expected_sha256=digest,dry_run=False,
                                live_adapter=lambda *_: (_ for _ in ()).throw(UploadError("UPLOAD_RESULT_UNKNOWN","ambiguous")))
                result=process_job(config,p,ledger,expected_sha256=digest,dry_run=False,
                                   reconcile_adapter=lambda *_:{"safe_to_retry":True},
                                   live_adapter=lambda *_:{"partner_center_confirmed":True})
                self.assertEqual(ledger.db.execute("SELECT attempts FROM uploads").fetchone()[0],2)
            self.assertEqual(result["status"],"SUCCEEDED")

    def test_interrupted_upload_recognizes_confirmed_partner_center_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            config={**CONFIG,"upload_approved":True}; digest=hashlib.sha256(p.read_bytes()).hexdigest()
            with JobLedger(root/"ledger.sqlite3") as ledger:
                with self.assertRaises(UploadError):
                    process_job(config,p,ledger,expected_sha256=digest,dry_run=False,
                                live_adapter=lambda *_: (_ for _ in ()).throw(UploadError("UPLOAD_RESULT_UNKNOWN","ambiguous")))
                result=process_job(config,p,ledger,expected_sha256=digest,dry_run=False,
                                   reconcile_adapter=lambda *_:{"partner_center_confirmed":True},
                                   live_adapter=lambda *_:self.fail("must not upload twice"))
            self.assertEqual(result["status"],"SUCCEEDED_RECONCILED")

    def test_live_upload_requires_frozen_hash_and_exact_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            with JobLedger(root/"ledger.sqlite3") as ledger:
                with self.assertRaisesRegex(UploadError,"frozen 64-character"):
                    process_job({**CONFIG,"upload_approved":True},p,ledger,dry_run=False,live_adapter=lambda *_:{"partner_center_confirmed":True})
            wrong={**CONFIG,"identity_name":"Wrong.Identity"}
            with self.assertRaisesRegex(UploadError,"manifest does not match"):
                verify_file(wrong,p)

if __name__=="__main__": unittest.main()
