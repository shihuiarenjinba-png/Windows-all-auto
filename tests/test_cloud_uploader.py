from __future__ import annotations
import hashlib
import tempfile
import unittest
from pathlib import Path
from uploader.core import JobLedger, UploadError, process_job, validate_config, verify_file

CONFIG = {"schema_version":1,"product_name":"Data Contract Auditor","product_id":"9PDL4ZWSB45P","submission_id":"1152921505702212222","repository":"shihuiarenjinba-png/csv-import-validator","ref":"107e59f2cbcde9c6ca88cf1aaf3d52262004e6e0","path":"pkg.msix","version":"1.0.0.0","destination":"microsoft_partner_center_existing_draft"}

class CloudUploaderTests(unittest.TestCase):
    def test_hash_and_target_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"pkg.msix"; p.write_bytes(b"synthetic-msix")
            job=verify_file(CONFIG,p,expected_sha256=hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertEqual((job.product_id,job.submission_id),(CONFIG["product_id"],CONFIG["submission_id"]))
    def test_bad_hash_and_destination_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"pkg.msix"; p.write_bytes(b"x")
            with self.assertRaisesRegex(UploadError,"SHA-256"): verify_file(CONFIG,p,expected_sha256="0"*64)
            with self.assertRaisesRegex(UploadError,"destination"): validate_config({**CONFIG,"destination":"new_submission"})
    def test_dry_run_duplicate_is_reconciled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; p.write_bytes(b"x")
            with JobLedger(root/"ledger.sqlite3") as ledger:
                a=process_job(CONFIG,p,ledger); b=process_job(CONFIG,p,ledger)
            self.assertEqual(a["status"],"DRY_RUN"); self.assertEqual(b["status"],"DRY_RUN_ALREADY_DONE")
    def test_live_msix_fails_closed_without_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; p.write_bytes(b"x")
            with JobLedger(root/"ledger.sqlite3") as ledger:
                with self.assertRaisesRegex(UploadError,"not enabled"): process_job(CONFIG,p,ledger,dry_run=False)
    def test_unconfirmed_result_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); p=root/"pkg.msix"; p.write_bytes(b"x")
            with JobLedger(root/"ledger.sqlite3") as ledger:
                with self.assertRaisesRegex(UploadError,"did not confirm"):
                    process_job(CONFIG,p,ledger,dry_run=False,live_adapter=lambda *_:{"http_accepted":True})
                self.assertEqual(ledger.db.execute("SELECT status FROM uploads").fetchone()[0],"UNKNOWN")

if __name__=="__main__": unittest.main()
