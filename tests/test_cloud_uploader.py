from __future__ import annotations
import hashlib
import tempfile
import sqlite3
import unittest
import zipfile
from pathlib import Path
from uploader.core import JobLedger, UploadError, process_job, validate_config, verify_file
from uploader.receipts import ReceiptJournal, new_execution_receipt

CONFIG = {"schema_version":1,"product_name":"Data Contract Auditor","product_id":"9PDL4ZWSB45P","submission_id":"1152921505702212222","repository":"shihuiarenjinba-png/csv-import-validator","ref":"107e59f2cbcde9c6ca88cf1aaf3d52262004e6e0","path":"pkg.msix","version":"1.0.0.0","destination":"microsoft_partner_center_existing_draft","identity_name":"OkinawaDesktopTools.DataContractAuditor","publisher":"CN=46263F21-A700-41DB-8C9B-114C22FB82FC","architecture":"x64","upload_approved":False}

def make_msix(path, data=b"synthetic-msix"):
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("AppxManifest.xml", '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"><Identity Name="OkinawaDesktopTools.DataContractAuditor" Publisher="CN=46263F21-A700-41DB-8C9B-114C22FB82FC" Version="1.0.0.0" ProcessorArchitecture="x64" /><Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.0.0" MaxVersionTested="10.0.22621.0" /></Dependencies></Package>''')
        package.writestr("payload.bin", data)

def approved_live_config(package, **updates):
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    config = {**CONFIG, "upload_approved": True,
              "upload_scope": "ONE_EXACT_MSIX_TO_EXISTING_DRAFT_PACKAGES_ONLY",
              "expected_sha256": digest,
              "certification_submission_authorized": False, "publish_authorized": False,
              "local_runtime_qa_status": "WINDOWS_REAL_DEVICE_QA_PASS_EXACT_PACKAGE",
              "runtime_qa_receipt": {"status": "WINDOWS_REAL_DEVICE_QA_PASS_EXACT_PACKAGE",
                                     "product_id": CONFIG["product_id"],
                                     "submission_id": CONFIG["submission_id"],
                                     "package_sha256": digest,
                                     "identity": CONFIG["identity_name"],
                                     "version": CONFIG["version"],
                                     "architecture": CONFIG["architecture"]},
              "device_family_settings": {"status": "OWNER_APPROVED",
                  "approved_store_device_families": ["Windows 10/11 Desktop"],
                  "approval": {"product_id": CONFIG["product_id"],
                               "submission_id": CONFIG["submission_id"],
                               "approval_ref": "fixture-device", "approved_by": "test", "approved_at": "2026-11-28"}},
              "execution_policy": {"status": "OWNER_APPROVED", "auto_execute_approved_sections": True,
                  "approved_sections": ["packages"],
                  "approval": {"product_id": CONFIG["product_id"],
                               "submission_id": CONFIG["submission_id"],
                               "approval_ref": "fixture-package", "approved_by": "test", "approved_at": "2026-11-28"}}}
    config.update(updates)
    return config

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
            config=approved_live_config(p); digest=hashlib.sha256(p.read_bytes()).hexdigest(); called=[]
            with JobLedger(root/"ledger.sqlite3") as ledger:
                process_job(config,p,ledger,dry_run=True)
                result=process_job(config,p,ledger,expected_sha256=digest,dry_run=False,
                                   live_adapter=lambda *_:(called.append(True) or {"partner_center_confirmed":True}))
                attempts=ledger.db.execute("SELECT attempts FROM uploads").fetchone()[0]
            self.assertEqual(result["status"],"SUCCEEDED")
            self.assertEqual(called,[True])
            self.assertEqual(attempts,1,"dry-run must not consume a remote upload attempt")
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
                    process_job(approved_live_config(p),p,ledger,expected_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),dry_run=False,live_adapter=lambda *_:{"http_accepted":True})
                self.assertEqual(ledger.db.execute("SELECT status FROM uploads").fetchone()[0],"UNKNOWN")

    def test_interrupted_upload_is_reconciled_before_safe_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            config=approved_live_config(p); digest=hashlib.sha256(p.read_bytes()).hexdigest()
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
            config=approved_live_config(p); digest=hashlib.sha256(p.read_bytes()).hexdigest()
            with JobLedger(root/"ledger.sqlite3") as ledger:
                with self.assertRaises(UploadError):
                    process_job(config,p,ledger,expected_sha256=digest,dry_run=False,
                                live_adapter=lambda *_: (_ for _ in ()).throw(UploadError("UPLOAD_RESULT_UNKNOWN","ambiguous")))
                result=process_job(config,p,ledger,expected_sha256=digest,dry_run=False,
                                   reconcile_adapter=lambda *_:{"partner_center_confirmed":True},
                                   live_adapter=lambda *_:self.fail("must not upload twice"))
            self.assertEqual(result["status"],"RECONCILE_REQUIRED")

    def test_cache_loss_with_exact_durable_receipt_prevents_duplicate_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            job=verify_file(CONFIG,p,expected_sha256=digest)
            journal=ReceiptJournal(root/"durable-receipts")
            receipt=new_execution_receipt(
                product_id=job.product_id,submission_id=job.submission_id,
                package_file_name=job.file_name,sha256=digest,result="SUCCEEDED",
                partner_center_confirmation="UI_VALIDATED_SHA_UNOBSERVABLE",
                details={"partner_center_confirmed":True,"partner_center_sha256":None},
            )
            journal.append(receipt)
            called=[]
            reconciled=[]
            def preflight(current_job, path, *, recovery_required=False):
                self.assertTrue(recovery_required)
                return {"live_adapter": lambda *_:called.append(True),
                        "reconcile_adapter": lambda current, _path, previous: (
                            reconciled.append(previous) or {
                                "partner_center_confirmed": True,
                                "current_partner_center_reconciled": True,
                                "partner_center_validation": "Validated",
                                "product_id": current.product_id,
                                "submission_id": current.submission_id,
                                "package_file_name": current.file_name,
                                "local_package_sha256": current.sha256,
                                "partner_center_sha256": None,
                                "prior_receipt_sha256_match": True,
                                "partner_center_confirmation": "UI_VALIDATED_SHA_UNOBSERVABLE"})}
            # New SQLite file simulates an evicted GitHub Actions cache.
            with JobLedger(root/"new-empty-ledger.sqlite3") as ledger:
                result=process_job(approved_live_config(p),p,ledger,
                    expected_sha256=digest,dry_run=False,receipt_journal=journal,
                    live_preflight_adapter=preflight)
            self.assertEqual(result["status"],"DUPLICATE_CONFIRMED")
            self.assertTrue(result["partner_center_reconfirmed"])
            self.assertEqual(called,[])
            self.assertEqual(len(reconciled),1)

    def test_historical_success_without_current_partner_center_match_never_skips_ahead_or_reuploads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            job=verify_file(CONFIG,p,expected_sha256=digest)
            journal=ReceiptJournal(root/"durable-receipts")
            journal.append(new_execution_receipt(
                product_id=job.product_id,submission_id=job.submission_id,
                package_file_name=job.file_name,sha256=digest,result="SUCCEEDED",
                partner_center_confirmation="UI_VALIDATED_SHA_UNOBSERVABLE"))
            uploads=[]
            with JobLedger(root/"ledger.sqlite3") as ledger:
                result=process_job(approved_live_config(p),p,ledger,expected_sha256=digest,
                    dry_run=False,receipt_journal=journal,
                    live_preflight_adapter=lambda *_args,**_kwargs:{
                        "live_adapter":lambda *_:uploads.append(True),
                        "reconcile_adapter":lambda *_:{"partner_center_confirmed":False,
                            "safe_to_retry":True,"reason":"row absent"}})
            self.assertEqual(result["status"],"RECONCILE_REQUIRED")
            self.assertEqual(uploads,[])

    def test_historical_success_without_live_reconcile_adapter_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            job=verify_file(CONFIG,p,expected_sha256=digest)
            journal=ReceiptJournal(root/"durable-receipts")
            journal.append(new_execution_receipt(
                product_id=job.product_id,submission_id=job.submission_id,
                package_file_name=job.file_name,sha256=digest,result="SUCCEEDED",
                partner_center_confirmation="UI_VALIDATED_SHA_UNOBSERVABLE"))
            with JobLedger(root/"ledger.sqlite3") as ledger:
                result=process_job(approved_live_config(p),p,ledger,expected_sha256=digest,
                    dry_run=False,receipt_journal=journal,
                    live_adapter=lambda *_:self.fail("historical ledger cannot confirm current Store state"))
            self.assertEqual(result["status"],"RECONCILE_REQUIRED")

    def test_sqlite_success_also_requires_current_partner_center_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            config=approved_live_config(p)
            with JobLedger(root/"ledger.sqlite3") as ledger:
                first=process_job(config,p,ledger,expected_sha256=digest,dry_run=False,
                                  live_adapter=lambda *_:{"partner_center_confirmed":True})
                self.assertEqual(first["status"],"SUCCEEDED")
                result=process_job(config,p,ledger,expected_sha256=digest,dry_run=False,
                    reconcile_adapter=lambda job, _path, _receipt:{
                        "partner_center_confirmed":True,
                        "current_partner_center_reconciled":True,
                        "partner_center_validation":"Validated",
                        "product_id":job.product_id,"submission_id":job.submission_id,
                        "package_file_name":job.file_name,"local_package_sha256":job.sha256,
                        "partner_center_sha256":None,"prior_receipt_sha256_match":True,
                        "partner_center_confirmation":"UI_VALIDATED_SHA_UNOBSERVABLE"},
                    live_adapter=lambda *_:self.fail("must not repeat the upload"))
            self.assertEqual(result["status"],"DUPLICATE_CONFIRMED")
            self.assertTrue(result["partner_center_reconfirmed"])

    def test_common_live_gate_holds_on_source_formal_package_sha_conflict(self):
        from uploader.live_gates import package_write_hold_reason
        with tempfile.TemporaryDirectory() as tmp:
            package=Path(tmp)/"pkg.msix"; make_msix(package)
            config=approved_live_config(package, source_package_provenance={
                "status":"MISMATCH",
                "formal_package_sha256":"4b373d2bc54ecbd3efa0a77a94005007777e66d641fa3908f523ac69fcd46984"})
            self.assertEqual(package_write_hold_reason(config,package),
                             "SOURCE_PRODUCT_PROFILE_PACKAGE_SHA_MISMATCH")

    def test_same_filename_different_sha_requires_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); first=root/"pkg.msix"; make_msix(first,b"first")
            digest=hashlib.sha256(first.read_bytes()).hexdigest()
            first_job=verify_file(CONFIG,first,expected_sha256=digest)
            journal=ReceiptJournal(root/"durable-receipts")
            journal.append(new_execution_receipt(
                product_id=first_job.product_id,submission_id=first_job.submission_id,
                package_file_name=first_job.file_name,sha256=digest,result="SUCCEEDED",
                partner_center_confirmation="UI_VALIDATED_SHA_UNOBSERVABLE"))
            changed=root/"changed.msix"; make_msix(changed,b"different")
            # Keep the same Store-visible name while changing package bytes.
            renamed=root/"pkg.msix"; changed.replace(renamed)
            changed_digest=hashlib.sha256(renamed.read_bytes()).hexdigest()
            with JobLedger(root/"ledger.sqlite3") as ledger:
                result=process_job(approved_live_config(renamed, path=renamed.name),renamed,ledger,
                    expected_sha256=changed_digest,dry_run=False,receipt_journal=journal,
                    live_adapter=lambda *_:self.fail("must not upload a different binary under a reused filename"))
            self.assertEqual(result["status"],"RECONCILE_REQUIRED")

    def test_corrupt_durable_receipt_fails_closed_before_live_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            journal=ReceiptJournal(root/"durable-receipts")
            bad=root/"durable-receipts"/CONFIG["product_id"]
            bad.mkdir(parents=True)
            (bad/"bad.json").write_text("{broken",encoding="utf-8")
            called=[]
            with JobLedger(root/"ledger.sqlite3") as ledger:
                with self.assertRaisesRegex(UploadError,"receipt ledger is unreadable"):
                    process_job(approved_live_config(p),p,ledger,dry_run=False,
                        receipt_journal=journal,live_adapter=lambda *_:(called.append(True) or {"partner_center_confirmed":True}))
            self.assertEqual(called,[])


    def test_legacy_preflight_failures_keep_history_but_do_not_consume_remote_write_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "pkg.msix"
            make_msix(package)
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            job = verify_file({**CONFIG, "upload_approved": True}, package, expected_sha256=digest)
            db_path = root / "legacy-ledger.sqlite3"

            # Simulate the pre-migration schema and a legacy pre-upload failure.
            with sqlite3.connect(db_path) as con:
                con.execute("""CREATE TABLE uploads (
                    job_key TEXT PRIMARY KEY, product_id TEXT NOT NULL, submission_id TEXT NOT NULL,
                    package_file_name TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL,
                    error_code TEXT NOT NULL DEFAULT '', receipt_json TEXT NOT NULL DEFAULT '')""")
                con.execute(
                    """INSERT INTO uploads
                       (job_key, product_id, submission_id, package_file_name, sha256,
                        status, attempts, error_code, receipt_json)
                       VALUES (?, ?, ?, ?, ?, 'FAILED', 3, 'PARTNER_CENTER_TAB_AMBIGUOUS', ?)""",
                    (JobLedger.key(job), job.product_id, job.submission_id, job.file_name,
                     job.sha256, '{"legacy":"kept"}'),
                )

            con.close()
            order = []
            def preflight(*_, **__):
                order.append("preflight")
                return {"live_adapter": lambda *_: (
                    order.append("upload") or {"partner_center_confirmed": True}
                )}

            with JobLedger(db_path) as ledger:
                accounting = ledger.db.execute(
                    """SELECT remote_write_attempts, classification, legacy_status,
                              legacy_error_code
                       FROM upload_write_attempts WHERE job_key=?""",
                    (JobLedger.key(job),),
                ).fetchone()
                self.assertEqual(accounting, (
                    0, "LEGACY_PREUPLOAD_FAILURE", "FAILED", "PARTNER_CENTER_TAB_AMBIGUOUS"
                ))
                result = process_job(
                    approved_live_config(package), package, ledger,
                    expected_sha256=digest, dry_run=False,
                    live_preflight_adapter=preflight,
                )
                historical_attempts, status = ledger.db.execute(
                    "SELECT attempts, status FROM uploads WHERE job_key=?",
                    (JobLedger.key(job),),
                ).fetchone()
                remote_attempts = ledger.db.execute(
                    "SELECT remote_write_attempts FROM upload_write_attempts WHERE job_key=?",
                    (JobLedger.key(job),),
                ).fetchone()[0]

            self.assertEqual(result["status"], "SUCCEEDED")
            self.assertEqual(order, ["preflight", "upload"])
            self.assertEqual(historical_attempts, 4, "legacy attempts remain monotonic; they are not reset")
            self.assertEqual(status, "SUCCEEDED")
            self.assertEqual(remote_attempts, 1)


    def test_dry_run_on_legacy_failed_row_does_not_change_history_or_remote_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "pkg.msix"
            make_msix(package)
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            job = verify_file(CONFIG, package, expected_sha256=digest)
            db_path = root / "legacy-ledger.sqlite3"

            con = sqlite3.connect(db_path)
            try:
                con.execute("""CREATE TABLE uploads (
                    job_key TEXT PRIMARY KEY, product_id TEXT NOT NULL, submission_id TEXT NOT NULL,
                    package_file_name TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL,
                    error_code TEXT NOT NULL DEFAULT '', receipt_json TEXT NOT NULL DEFAULT '')""")
                con.execute(
                    """INSERT INTO uploads
                       (job_key, product_id, submission_id, package_file_name, sha256,
                        status, attempts, error_code, receipt_json)
                       VALUES (?, ?, ?, ?, ?, 'FAILED', 3, 'PARTNER_CENTER_TAB_AMBIGUOUS', ?)""",
                    (JobLedger.key(job), job.product_id, job.submission_id, job.file_name,
                     job.sha256, '{"legacy":"kept"}'),
                )
                con.commit()
            finally:
                con.close()

            with JobLedger(db_path) as ledger:
                result = process_job(CONFIG, package, ledger, expected_sha256=digest, dry_run=True)
                historical = ledger.db.execute(
                    "SELECT status, attempts, error_code, receipt_json FROM uploads WHERE job_key=?",
                    (JobLedger.key(job),),
                ).fetchone()
                remote_attempts = ledger.db.execute(
                    "SELECT remote_write_attempts FROM upload_write_attempts WHERE job_key=?",
                    (JobLedger.key(job),),
                ).fetchone()[0]

            self.assertEqual(result["status"], "DRY_RUN")
            self.assertEqual(historical, ("FAILED", 3, "PARTNER_CENTER_TAB_AMBIGUOUS", '{"legacy":"kept"}'))
            self.assertEqual(remote_attempts, 0)

    def test_legacy_ambiguous_write_history_remains_at_retry_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "pkg.msix"
            make_msix(package)
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            job = verify_file({**CONFIG, "upload_approved": True}, package, expected_sha256=digest)
            db_path = root / "legacy-ledger.sqlite3"

            with sqlite3.connect(db_path) as con:
                con.execute("""CREATE TABLE uploads (
                    job_key TEXT PRIMARY KEY, product_id TEXT NOT NULL, submission_id TEXT NOT NULL,
                    package_file_name TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL,
                    error_code TEXT NOT NULL DEFAULT '', receipt_json TEXT NOT NULL DEFAULT '')""")
                con.execute(
                    """INSERT INTO uploads
                       (job_key, product_id, submission_id, package_file_name, sha256,
                        status, attempts, error_code, receipt_json)
                       VALUES (?, ?, ?, ?, ?, 'FAILED', 3, 'UPLOAD_RESULT_UNKNOWN', '{}')""",
                    (JobLedger.key(job), job.product_id, job.submission_id, job.file_name, job.sha256),
                )

            con.close()
            order = []
            def preflight(*_, **__):
                order.append("preflight")
                return {"live_adapter": lambda *_: order.append("upload") or {"partner_center_confirmed": True}}

            with JobLedger(db_path) as ledger:
                result = process_job(
                    approved_live_config(package), package, ledger,
                    expected_sha256=digest, dry_run=False,
                    live_preflight_adapter=preflight,
                )
                remote_attempts = ledger.db.execute(
                    "SELECT remote_write_attempts FROM upload_write_attempts WHERE job_key=?",
                    (JobLedger.key(job),),
                ).fetchone()[0]

            self.assertEqual(result["status"], "RETRY_LIMIT")
            self.assertEqual(order, ["preflight"], "preflight may inspect, but the MSIX is never selected")
            self.assertEqual(remote_attempts, 3)

    def test_live_upload_requires_frozen_hash_and_exact_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            with JobLedger(root/"ledger.sqlite3") as ledger:
                with self.assertRaisesRegex(UploadError,"frozen 64-character"):
                    process_job(approved_live_config(p),p,ledger,dry_run=False,live_adapter=lambda *_:{"partner_center_confirmed":True})
            wrong={**CONFIG,"identity_name":"Wrong.Identity"}
            with self.assertRaisesRegex(UploadError,"manifest does not match"):
                verify_file(wrong,p)

    def test_cdp_preflight_failure_does_not_consume_remote_upload_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            adapter_calls=[]
            with JobLedger(root/"ledger.sqlite3") as ledger:
                with self.assertRaisesRegex(UploadError,"tab selection failed"):
                    process_job(approved_live_config(p),p,ledger,
                        expected_sha256=digest,dry_run=False,
                        live_adapter=lambda *_: adapter_calls.append("upload"),
                        live_preflight_adapter=lambda *_, **__: (_ for _ in ()).throw(
                            UploadError("HOLD_NO_MATCHING_PRODUCT_TAB","tab selection failed")))
                rows=ledger.db.execute("SELECT attempts,status FROM uploads").fetchall()
            self.assertEqual(rows,[])
            self.assertEqual(adapter_calls,[])

    def test_preflight_completes_before_upload_attempt_is_reserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; make_msix(p)
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            order=[]
            def preflight(*_, **__):
                order.append("preflight")
                return {"live_adapter":lambda *_:(order.append("upload") or {"partner_center_confirmed":True})}
            with JobLedger(root/"ledger.sqlite3") as ledger:
                result=process_job(approved_live_config(p),p,ledger,
                    expected_sha256=digest,dry_run=False,live_adapter=lambda *_:None,
                    live_preflight_adapter=preflight)
                attempts=ledger.db.execute("SELECT attempts FROM uploads").fetchone()[0]
            self.assertEqual(order,["preflight","upload"])
            self.assertEqual(attempts,1)
            self.assertEqual(result["status"],"SUCCEEDED")

if __name__=="__main__": unittest.main()
