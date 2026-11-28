from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "folder_engine_paid_trial_handoff_v2.json"


class GroupBLocalQaTemplateTests(unittest.TestCase):
    def test_folder_template_is_seeded_from_registry_and_keeps_github_primary(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "receipt.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "create_local_final_qa_receipt_template.py"),
                    "--handoff",
                    str(FIXTURE),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(receipt["github_ci_is_primary"])
            self.assertFalse(receipt["local_full_test_suite_required"])
            self.assertEqual(receipt["test_source"], "github_exact_head_ci")
            self.assertIn("Store-signed JP/EN GUI", receipt["product_specific_checks"])
            self.assertIn("real OS DPI 100/125/150", receipt["product_specific_checks"])

    def test_template_refuses_to_overwrite_existing_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "receipt.json"
            output.write_text('{"existing": true}\n', encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "create_local_final_qa_receipt_template.py"),
                    "--handoff",
                    str(FIXTURE),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to overwrite", result.stderr + result.stdout)

    def test_template_script_does_not_authorize_store_write(self):
        text = (
            ROOT / "scripts" / "create_local_final_qa_receipt_template.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "submit certification",
            "publish_approved = True",
            "package_uploaded = True",
            "confirm-live-draft",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
