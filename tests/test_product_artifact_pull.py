from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from all_auto.product_artifact_pull import (
    ProductArtifactPullError,
    stage_verified_store_artifact,
    validate_extracted_store_artifact,
    write_immutable_receipt,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "folder_engine_paid_trial_handoff_v2.json"


def build_artifact(root: Path, *, run_id: int = 123) -> dict:
    handoff = json.loads(FIXTURE.read_text(encoding="utf-8"))
    handoff["product"]["id"] = "demo"
    handoff["product"]["name"] = "Demo Product"
    handoff["product"]["repository"] = "https://github.com/acme/demo"
    handoff["product"]["source_sha"] = "a" * 40

    msix_name = "Demo_1.0.0.0_x64.msix"
    msix = root / msix_name
    msix.write_bytes(b"exact-msix-bytes")
    package_sha = sha256(msix.read_bytes()).hexdigest()
    exe_sha = "b" * 64

    handoff["package"]["artifact_run_id"] = run_id
    handoff["package"]["file_name"] = msix_name
    handoff["package"]["package_sha256"] = package_sha
    handoff["package"]["exe_sha256"] = exe_sha
    handoff["security"]["package_sha256"] = package_sha

    (root / "store-product-handoff.json").write_text(
        json.dumps(handoff, indent=2), encoding="utf-8"
    )
    validation = {
        "source_commit": "a" * 40,
        "store_id": handoff["identity"]["store_id"],
        "identity_name": handoff["identity"]["name"],
        "identity_publisher": handoff["identity"]["publisher"],
        "msix_version": handoff["identity"]["version"],
        "msix_sha256": package_sha,
        "source_exe_sha256": exe_sha,
        "unpacked_exe_sha256": exe_sha,
        "manifest_identity_verified": True,
        "makeappx_pack_unpack": "PASS",
        "signed": False,
        "store_submission_approved": False,
        "sale_approved": False,
    }
    (root / "msix_validation.json").write_text(
        json.dumps(validation, indent=2), encoding="utf-8"
    )
    (root / "msix.sha256.txt").write_text(
        f"{package_sha}  {msix_name}\n", encoding="utf-8"
    )
    return handoff


class ProductArtifactPullTests(unittest.TestCase):
    def test_exact_artifact_validates_and_stages_without_store_action(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "download"
            root.mkdir()
            handoff = build_artifact(root)
            verified = validate_extracted_store_artifact(
                root,
                repository_full_name="acme/demo",
                run_id=123,
                artifact_name="Demo-Store-MSIX-UNSIGNED-DRAFT",
            )
            self.assertEqual(
                verified["status"], "LOCAL_STORE_PRODUCT_ARTIFACT_VERIFIED"
            )
            self.assertEqual(verified["source_sha"], "a" * 40)
            self.assertFalse(verified["submitted_to_store"])
            self.assertFalse(verified["package_rebuilt"])
            self.assertFalse(verified["security_bypass_used"])

            target = Path(td) / "inbox"
            staged = stage_verified_store_artifact(
                verified,
                target_root=target,
            )
            package = Path(staged["local_package_path"])
            self.assertTrue(package.is_file())
            self.assertEqual(
                sha256(package.read_bytes()).hexdigest(),
                handoff["package"]["package_sha256"],
            )

    def test_rejects_run_id_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_artifact(root, run_id=123)
            with self.assertRaisesRegex(ProductArtifactPullError, "artifact_run_id"):
                validate_extracted_store_artifact(
                    root,
                    repository_full_name="acme/demo",
                    run_id=124,
                    artifact_name="Demo-Store-MSIX-UNSIGNED-DRAFT",
                )

    def test_rejects_tampered_msix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_artifact(root)
            next(root.glob("*.msix")).write_bytes(b"tampered")
            with self.assertRaisesRegex(ProductArtifactPullError, "MSIX SHA256"):
                validate_extracted_store_artifact(
                    root,
                    repository_full_name="acme/demo",
                    run_id=123,
                    artifact_name="Demo-Store-MSIX-UNSIGNED-DRAFT",
                )

    def test_rejects_repository_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            build_artifact(root)
            with self.assertRaisesRegex(ProductArtifactPullError, "repository mismatch"):
                validate_extracted_store_artifact(
                    root,
                    repository_full_name="acme/other",
                    run_id=123,
                    artifact_name="Demo-Store-MSIX-UNSIGNED-DRAFT",
                )

    def test_receipt_is_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "receipt.json"
            receipt = {"status": "LOCAL_STORE_PRODUCT_ARTIFACT_VERIFIED"}
            write_immutable_receipt(path, receipt)
            with self.assertRaisesRegex(ProductArtifactPullError, "refusing to overwrite"):
                write_immutable_receipt(path, receipt)

    def test_stage_refuses_existing_destination(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "download"
            root.mkdir()
            build_artifact(root)
            verified = validate_extracted_store_artifact(
                root,
                repository_full_name="acme/demo",
                run_id=123,
                artifact_name="Demo-Store-MSIX-UNSIGNED-DRAFT",
            )
            target = Path(td) / "inbox"
            stage_verified_store_artifact(verified, target_root=target)
            with self.assertRaisesRegex(ProductArtifactPullError, "refusing to overwrite"):
                stage_verified_store_artifact(verified, target_root=target)


if __name__ == "__main__":
    unittest.main()
