from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from all_auto.github_artifact_intake import (
    ArtifactIntakeHold, fetch_actions_artifact, safe_extract_zip,
    sha256_file, validate_artifact_metadata,
)


SOURCE = "c" * 40
RUN_ID = 123456
ARTIFACT_ID = 789
ARTIFACT_NAME = "Demo_1.0.0.0_x64_STORE_CANDIDATE_UNSIGNED"
PACKAGE_NAME = "Demo_1.0.0.0_x64_STORE_CANDIDATE_UNSIGNED.msix"


def write_msix(path: Path, exe_bytes: bytes = b"demo exe") -> str:
    manifest = """<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
  <Identity Name="OkinawaDesktopTools.Demo" Publisher="CN=TEST" Version="1.0.0.0" ProcessorArchitecture="x64"/>
  <Properties><DisplayName>Demo</DisplayName><PublisherDisplayName>Demo</PublisherDisplayName><Logo>Assets/StoreLogo.png</Logo></Properties>
  <Resources><Resource Language="en-us"/></Resources>
  <Applications>
    <Application Id="App" Executable="Demo.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10" DisplayName="Demo" Description="Demo" Square150x150Logo="Assets/Square150x150Logo.png" Square44x44Logo="Assets/Square44x44Logo.png" BackgroundColor="transparent"/>
    </Application>
  </Applications>
</Package>"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("AppxManifest.xml", manifest)
        archive.writestr("Demo.exe", exe_bytes)
        archive.writestr("Assets/StoreLogo.png", b"x")
        archive.writestr("Assets/Square150x150Logo.png", b"x")
        archive.writestr("Assets/Square44x44Logo.png", b"x")
    return sha256(exe_bytes).hexdigest()


class GithubArtifactIntakeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.msix = self.root / PACKAGE_NAME
        self.exe_sha = write_msix(self.msix)
        self.package_sha = sha256_file(self.msix)
        self.archive = self.root / "artifact.zip"
        with zipfile.ZipFile(self.archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(self.msix, arcname=PACKAGE_NAME)
        self.archive_sha = sha256_file(self.archive)
        self.metadata = {
            "id": ARTIFACT_ID,
            "name": ARTIFACT_NAME,
            "expired": False,
            "digest": "sha256:" + self.archive_sha,
            "archive_download_url": (
                "https://api.github.com/repos/owner/repo/actions/artifacts/789/zip"
            ),
            "workflow_run": {
                "id": RUN_ID,
                "head_sha": SOURCE,
            },
        }

    def test_metadata_must_match_exact_run_and_source(self):
        url = validate_artifact_metadata(
            self.metadata, repository="owner/repo", artifact_id=ARTIFACT_ID,
            expected_name=ARTIFACT_NAME, expected_run_id=RUN_ID,
            expected_head_sha=SOURCE, expected_archive_sha256=self.archive_sha,
        )
        self.assertTrue(url.startswith("https://api.github.com/"))
        changed = json.loads(json.dumps(self.metadata))
        changed["workflow_run"]["head_sha"] = "d" * 40
        with self.assertRaisesRegex(ArtifactIntakeHold, "source SHA"):
            validate_artifact_metadata(
                changed, repository="owner/repo", artifact_id=ARTIFACT_ID,
                expected_name=ARTIFACT_NAME, expected_run_id=RUN_ID,
                expected_head_sha=SOURCE, expected_archive_sha256=self.archive_sha,
            )

    def test_expired_artifact_holds(self):
        changed = dict(self.metadata)
        changed["expired"] = True
        with self.assertRaisesRegex(ArtifactIntakeHold, "expired"):
            validate_artifact_metadata(
                changed, repository="owner/repo", artifact_id=ARTIFACT_ID,
                expected_name=ARTIFACT_NAME, expected_run_id=RUN_ID,
                expected_head_sha=SOURCE, expected_archive_sha256=self.archive_sha,
            )

    def test_archive_traversal_holds(self):
        archive = self.root / "bad.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("../escape.txt", "bad")
        with self.assertRaisesRegex(ArtifactIntakeHold, "unsafe archive member"):
            safe_extract_zip(archive, self.root / "out")

    def test_full_intake_verifies_archive_package_and_exe(self):
        destination = self.root / "intake-root"

        def fake_download(url, token, output):
            shutil.copyfile(self.archive, output)

        with patch(
            "all_auto.github_artifact_intake._github_token",
            return_value="test-token",
        ), patch(
            "all_auto.github_artifact_intake._get_json",
            return_value=self.metadata,
        ), patch(
            "all_auto.github_artifact_intake._download",
            side_effect=fake_download,
        ):
            result = fetch_actions_artifact(
                repository="owner/repo",
                artifact_id=ARTIFACT_ID,
                expected_name=ARTIFACT_NAME,
                expected_run_id=RUN_ID,
                expected_head_sha=SOURCE,
                expected_archive_sha256=self.archive_sha,
                expected_package_name=PACKAGE_NAME,
                expected_package_sha256=self.package_sha,
                expected_executable_sha256=self.exe_sha,
                destination=destination,
            )
        self.assertEqual(result.metadata["source_sha"], SOURCE)
        self.assertEqual(result.metadata["package_sha256"], self.package_sha)
        self.assertEqual(result.metadata["executable_sha256"], self.exe_sha)
        self.assertEqual(result.metadata["identity"]["version"], "1.0.0.0")
        self.assertFalse(result.metadata["store_purchase_required"])
        self.assertTrue(result.executable_path.is_file())

    def test_package_sha_mismatch_holds(self):
        destination = self.root / "bad-package"

        def fake_download(url, token, output):
            shutil.copyfile(self.archive, output)

        with patch(
            "all_auto.github_artifact_intake._github_token",
            return_value="test-token",
        ), patch(
            "all_auto.github_artifact_intake._get_json",
            return_value=self.metadata,
        ), patch(
            "all_auto.github_artifact_intake._download",
            side_effect=fake_download,
        ):
            with self.assertRaisesRegex(ArtifactIntakeHold, "MSIX SHA"):
                fetch_actions_artifact(
                    repository="owner/repo",
                    artifact_id=ARTIFACT_ID,
                    expected_name=ARTIFACT_NAME,
                    expected_run_id=RUN_ID,
                    expected_head_sha=SOURCE,
                    expected_archive_sha256=self.archive_sha,
                    expected_package_name=PACKAGE_NAME,
                    expected_package_sha256="0" * 64,
                    expected_executable_sha256=self.exe_sha,
                    destination=destination,
                )

    def test_executable_sha_mismatch_holds(self):
        destination = self.root / "bad-exe"

        def fake_download(url, token, output):
            shutil.copyfile(self.archive, output)

        with patch(
            "all_auto.github_artifact_intake._github_token",
            return_value="test-token",
        ), patch(
            "all_auto.github_artifact_intake._get_json",
            return_value=self.metadata,
        ), patch(
            "all_auto.github_artifact_intake._download",
            side_effect=fake_download,
        ):
            with self.assertRaisesRegex(ArtifactIntakeHold, "executable SHA"):
                fetch_actions_artifact(
                    repository="owner/repo",
                    artifact_id=ARTIFACT_ID,
                    expected_name=ARTIFACT_NAME,
                    expected_run_id=RUN_ID,
                    expected_head_sha=SOURCE,
                    expected_archive_sha256=self.archive_sha,
                    expected_package_name=PACKAGE_NAME,
                    expected_package_sha256=self.package_sha,
                    expected_executable_sha256="0" * 64,
                    destination=destination,
                )


if __name__ == "__main__":
    unittest.main()
