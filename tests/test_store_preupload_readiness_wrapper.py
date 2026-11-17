from pathlib import Path
import unittest


class StorePreuploadReadinessWrapperContractTests(unittest.TestCase):
    def test_wrapper_is_local_only_fail_closed_and_candidate_first(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "scripts" / "run_store_preupload_readiness.ps1").read_text(
            encoding="utf-8"
        )
        candidate = text.index("check_local_store_upload_candidate.py")
        preflight = text.index("run_local_exact_package_preflight.ps1")
        self.assertLess(candidate, preflight)
        for required in (
            "HOLD_EXACT_PACKAGE_MISMATCH",
            "READY_FOR_MSIX_UPLOAD_APPROVAL",
            "package_upload_executed",
            "certification_executed",
            "published",
            "SourceCheckoutMode",
        ):
            self.assertIn(required, text)
        for forbidden in (
            "Submit for certification",
            "Publish button",
            "set_input_files",
            "confirm-live-draft",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
