"""Offline, credential-free tests for the local-only Identity return worker."""
import base64
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from scripts import local_identity_return as worker

SOURCE = "c058cbf7fe38e02d929c67d047d717ff74bd522e"
REQUEST = "game-signal-sprint-" + SOURCE
PROVISIONER_SHA = "66fc66b0e2a58dba2a9023f7e7fbbd6e5803d857"
RETURN_SHA = "b" * 40
EXE_SHA = "e8517df8cd31a40e5ce72afdd4e6a4d63626fb99f7ff8a4fa3296ff8deef05f4"
BRANCH = "codex/game-signal-sprint-undo-20261027"
PBRANCH = "codex/game-msix-package-safety-20261027-1510"


def args(tmp, **changes):
    values = dict(source_sha=SOURCE, source_branch=BRANCH, request_id=REQUEST,
                  provisioner_sha=PROVISIONER_SHA, provisioner_branch=PBRANCH,
                  provisioner_root=tmp / "provisioner", local_dir=tmp / "local",
                  official_identity=tmp / "identity-private.json",
                  apply=False, confirm_request_id="")
    values.update(changes)
    return SimpleNamespace(**values)


def ledger():
    job = dict(schema_version="1.0", request_id=REQUEST, product_type="GAME",
               source_factory="AI-Game-Factory", source_repository=worker.FACTORY,
               source_branch=BRANCH, source_sha=SOURCE, slug="signal-sprint",
               display_name="Signal Sprint", target_owner="shihuiarenjinba-png",
               dry_run=False, requested_actions=["BUILD_WINDOWS", "INSPECT_PACKAGE",
                  "LOOKUP_OFFICIAL_IDENTITY", "PROPOSE_GITHUB_RETURN"])
    return {"e2e_pass": False, "new_product_allowed": False,
            "active_product": {
                "lane": "GAME", "product_type": "GAME",
                "source_factory": "AI-Game-Factory",
                "source_repository": worker.FACTORY,
                "source_branch": BRANCH, "source_sha": SOURCE,
                "expected_head_sha": SOURCE, "request_id": REQUEST,
                "slug": "signal-sprint", "factory_return_commit_sha": None,
                "approved_identity_json": None,
                "local_job_live": job,
                "local_execution_result": {"package_sha256": EXE_SHA},
                "provisioner_package_safety": {
                    "repository": worker.PROVISIONER,
                    "branch": PBRANCH, "head_sha": PROVISIONER_SHA}}}


def provisioner_result(applied, package_sha=EXE_SHA):
    return {"request_id": REQUEST, "product_type": "GAME",
            "source_sha": SOURCE, "source_repository": worker.FACTORY,
            "source_branch": BRANCH, "slug": "signal-sprint",
            "status": "HOLD", "package": {"kind": "exe",
            "sha256": package_sha, "signature_status": "NOTSIGNED"},
            "github_return": {"status": "APPLIED" if applied else "NOT_APPLIED",
                              "commit_sha": RETURN_SHA if applied else None},
            "next_stage": "GITHUB_REBUILD_MSIX" if applied else
                          "APPLY_VERIFIED_GITHUB_RETURN"}


class LocalIdentityWorkerTests(unittest.TestCase):
    def test_pinned_identity_contract(self):
        product, safety = worker.validate_ledger(ledger(), args(Path(".")))
        self.assertEqual(product["source_sha"], SOURCE)
        self.assertEqual(safety["head_sha"], PROVISIONER_SHA)

    def test_reject_changed_request_and_source(self):
        for change in ({"source_sha": "a" * 40},
                       {"request_id": "game-signal-sprint-" + "a" * 40},
                       {"source_branch": "codex/other"}):
            with self.subTest(change=change):
                with self.assertRaises(worker.Gate) as ctx:
                    worker.validate_ledger(ledger(), args(Path("."), **change))
                self.assertEqual(ctx.exception.status, "CONFLICT")

    def test_reject_unreviewed_provisioner(self):
        with self.assertRaisesRegex(worker.Gate, "PROVISIONER_PIN_MISMATCH"):
            worker.validate_ledger(ledger(), args(Path("."), provisioner_sha="a" * 40))

    def test_duplicate_json_key_rejected(self):
        with self.assertRaisesRegex(worker.Gate, "DUPLICATE_JSON_KEY"):
            worker.parse_json('{"request_id":"first","request_id":"second"}')

    def test_remote_ledger_decodes_only_pinned_source(self):
        raw = json.dumps(ledger()).encode()
        response = {"encoding": "base64", "content": base64.b64encode(raw).decode()}
        with patch.object(worker, "gh_api", return_value=response) as mock:
            self.assertEqual(worker.read_ledger()["active_product"]["slug"], "signal-sprint")
        self.assertIn(worker.LEDGER_REF.replace("/", "%2F"), mock.call_args.args[0])

    def test_wrong_local_evidence_is_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "identity.json"
            path.write_text(json.dumps({"request_id": REQUEST, "source_sha": "a" * 40,
                                        "product_type": "GAME", "slug": "signal-sprint"}))
            with self.assertRaises(worker.Gate) as ctx:
                worker.validate_evidence(path, args(Path(tmp)))
            self.assertEqual(ctx.exception.status, "CONFLICT")

    def test_missing_evidence_holds_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = args(Path(tmp))
            with (patch.object(worker, "read_ledger", return_value=ledger()),
                  patch.object(worker, "source_head", return_value=SOURCE),
                  patch.object(worker, "check_local_paths",
                               return_value=(Path(tmp), Path(tmp) / "local",
                                             Path(tmp) / "missing.json")),
                  patch.object(worker, "validate_evidence", return_value=False),
                  patch.object(worker.subprocess, "run") as proc):
                result = worker.run(a)
            self.assertEqual(result["status"], "HOLD")
            proc.assert_not_called()

    def test_source_conflict_before_evidence(self):
        with (patch.object(worker, "read_ledger", return_value=ledger()),
              patch.object(worker, "source_head", return_value="a" * 40),
              patch.object(worker, "check_local_paths") as paths):
            with self.assertRaisesRegex(worker.Gate, "FACTORY_SOURCE_HEAD_CHANGED"):
                worker.run(args(Path(".")))
            paths.assert_not_called()

    def test_apply_requires_explicit_request_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = args(Path(tmp), apply=True)
            with (patch.object(worker, "read_ledger", return_value=ledger()),
                  patch.object(worker, "source_head", return_value=SOURCE),
                  patch.object(worker, "check_local_paths",
                               return_value=(Path(tmp), Path(tmp) / "local",
                                             Path(tmp) / "evidence.json")),
                  patch.object(worker, "validate_evidence", return_value=True)):
                with self.assertRaisesRegex(worker.Gate, "EXPLICIT_REQUEST_APPROVAL_REQUIRED"):
                    worker.run(a)

    def test_check_only_never_applies(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = args(Path(tmp))
            with (patch.object(worker, "read_ledger", return_value=ledger()),
                  patch.object(worker, "source_head", return_value=SOURCE),
                  patch.object(worker, "check_local_paths",
                               return_value=(Path(tmp), Path(tmp) / "local",
                                             Path(tmp) / "evidence.json")),
                  patch.object(worker, "validate_evidence", return_value=True),
                  patch.object(worker.subprocess, "run") as proc):
                self.assertEqual(worker.run(a)["status"], "READY_FOR_LOCAL_CAS_APPROVAL")
                proc.assert_not_called()

    def test_changed_exe_preflight_blocks_cas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = args(root, apply=True, confirm_request_id=REQUEST)
            calls = []
            def fake_run(command, **kwargs):
                calls.append(command)
                (root / "local" / "provisioner-result.json").write_text(
                    json.dumps(provisioner_result(False, "a" * 64)))
                return SimpleNamespace(returncode=2)
            with (patch.object(worker, "read_ledger", return_value=ledger()),
                  patch.object(worker, "source_head", return_value=SOURCE),
                  patch.object(worker, "check_local_paths",
                               return_value=(root, root / "local", root / "evidence.json")),
                  patch.object(worker, "validate_evidence", return_value=True),
                  patch.object(worker.subprocess, "run", side_effect=fake_run)):
                with self.assertRaisesRegex(worker.Gate, "LOCAL_EXE_PROVENANCE_CHANGED"):
                    worker.run(a)
            self.assertEqual(len(calls), 1)
            self.assertNotIn("--apply", calls[0])

    def test_cas_receipt_contains_no_identity_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = args(root, apply=True, confirm_request_id=REQUEST)
            calls = []
            def fake_run(command, **kwargs):
                applied = "--apply" in command
                calls.append(applied)
                (root / "local" / "provisioner-result.json").write_text(
                    json.dumps(provisioner_result(applied)))
                return SimpleNamespace(returncode=2)
            with (patch.object(worker, "read_ledger", return_value=ledger()),
                  patch.object(worker, "source_head",
                               side_effect=[SOURCE, SOURCE, SOURCE, RETURN_SHA]),
                  patch.object(worker, "check_local_paths",
                               return_value=(root, root / "local", root / "evidence.json")),
                  patch.object(worker, "validate_evidence", return_value=True),
                  patch.object(worker.subprocess, "run", side_effect=fake_run)):
                receipt = worker.run(a)
            self.assertEqual(calls, [False, True])
            self.assertEqual(receipt["status"], "CAS_RETURNED_MSIX_PENDING")
            self.assertEqual(receipt["factory_return_commit_sha"], RETURN_SHA)
            saved = (root / "local" / "identity-return-receipt.json").read_text()
            self.assertNotIn("partner.microsoft", saved)
            self.assertNotIn("store_id", saved)
            self.assertFalse(receipt["e2e_pass"])


if __name__ == "__main__":
    unittest.main()
