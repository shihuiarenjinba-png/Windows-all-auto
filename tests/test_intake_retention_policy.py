"""Guard the central verified MSIX backlog retention contract."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "factory-msix-intake.yml"


class IntakeRetentionPolicyTests(unittest.TestCase):
    def test_verified_msix_local_qa_retained_30_days(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        marker = "name: verified-msix-local-qa-"
        self.assertIn(marker, workflow)
        artifact_section = workflow.split(marker, 1)[1].split("      - name:", 1)[0]
        self.assertIn("retention-days: 30", artifact_section)

    def test_no_bulk_local_download_added_to_workflow(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("gh run download --all", workflow)
        self.assertNotIn("download-artifact@v4", workflow)


if __name__ == "__main__":
    unittest.main()
