"""Offline guards for canonical E2E ledger single-writer atomic commit."""
import base64
import copy
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts import post_identity_ledger_writer as writer

HEAD = "a" * 40
BLOB = "b" * 40
COMMIT = "c" * 40
SLUG = "focus-session-desk"


def ledger():
    return {
        "schema_version": 1, "e2e_pass": False, "e2e_status": "HOLD",
        "new_product_allowed": False, "rotation_cohorts": {"app_jobs": []},
        "user_id_requests": {"items": []},
        "registration_router": {"entries": []},
        "post_identity_pipeline": {"products": []},
        "policy": {"store_submission": False},
    }


def bound_ledger():
    value = ledger()
    value["rotation_cohorts"]["app_jobs"] = [
        {"slug": SLUG, "request_id": "request-focus", "display_name": "Focus Session Desk",
         "source_sha": HEAD, "source_repository": "shihuiarenjinba-png/AI-App-Factory",
         "identity_return_target": "products/focus-session-desk/store/approved-identity.json"},
        {"slug": "other-product", "request_id": "request-other", "display_name": "Other Product"},
    ]
    value["user_id_requests"]["items"] = [
        {"request_id": "request-focus", "status": "WAITING_USER_IDENTITY",
         "source_sha": HEAD, "repo": "shihuiarenjinba-png/AI-App-Factory"},
        {"request_id": "request-other", "status": "WAITING_USER_IDENTITY"},
    ]
    value["registration_router"]["entries"] = [
        {"product": "Focus Session Desk", "identity_status": "WAITING",
         "registration_type": "MSIX_OR_PWA_APP"},
        {"product": "Other Product", "identity_status": "WAITING"},
    ]
    value["post_identity_pipeline"]["products"] = [
        {"request_id": "request-focus", "state": "WAITING_IDENTITY_CAPTURE_AND_CAS",
         "source_branch": "codex/focus"},
        {"request_id": "request-other", "state": "WAITING_IDENTITY_CAPTURE_AND_CAS"},
    ]
    return value


class CanonicalLedgerWriterTests(unittest.TestCase):
    @patch.object(writer, "_gh_json")
    def test_head_exact_ref_and_commit(self, gh):
        gh.return_value = {
            "ref": f"refs/heads/{writer.BRANCH}",
            "object": {"type": "commit", "sha": HEAD},
        }
        self.assertEqual(writer.fetch_canonical_head(), HEAD)
        gh.return_value["ref"] = "refs/heads/main"
        with self.assertRaisesRegex(writer.LedgerWriteHold, "HEAD_INVALID"):
            writer.fetch_canonical_head()

    @patch.object(writer, "_gh_json")
    def test_pinned_ledger_content_and_blob(self, gh):
        raw = json.dumps(ledger()).encode()
        gh.return_value = {
            "type": "file", "path": writer.PATH, "encoding": "base64",
            "sha": BLOB, "size": len(raw),
            "content": base64.b64encode(raw).decode(),
        }
        gh.return_value["sha"] = writer._git_blob_sha(raw.decode())
        loaded, blob = writer.fetch_canonical_ledger(HEAD)
        self.assertEqual(loaded, ledger())
        self.assertEqual(blob, writer._git_blob_sha(raw.decode()))
        self.assertIn("?ref=" + HEAD, gh.call_args.args[0])

    @patch.object(writer, "_gh_json")
    def test_reject_mismatched_git_blob_for_valid_json(self, gh):
        raw = json.dumps(ledger()).encode()
        gh.return_value = {
            "type": "file", "path": writer.PATH, "encoding": "base64",
            "sha": BLOB, "size": len(raw),
            "content": base64.b64encode(raw).decode(),
        }
        with self.assertRaisesRegex(writer.LedgerWriteHold,
                                    "^HOLD_CANONICAL_BLOB_CONTENT_MISMATCH$"):
            writer.fetch_canonical_ledger(HEAD)

    @patch.object(writer, "_gh_json")
    def test_reject_duplicate_json_key(self, gh):
        raw = b'{"schema_version":1,"schema_version":1}'
        gh.return_value = {
            "type": "file", "path": writer.PATH, "encoding": "base64",
            "sha": BLOB, "size": len(raw),
            "content": base64.b64encode(raw).decode(),
        }
        with self.assertRaisesRegex(writer.LedgerWriteHold, "DUPLICATE"):
            writer.fetch_canonical_ledger(HEAD)

    @patch.object(writer, "_gh_json")
    def test_reject_bad_content_and_nan(self, gh):
        raw = b'{"schema_version":1,"value":NaN}'
        gh.return_value = {
            "type": "file", "path": writer.PATH, "encoding": "base64",
            "sha": BLOB, "size": len(raw),
            "content": base64.b64encode(raw).decode(),
        }
        with self.assertRaisesRegex(writer.LedgerWriteHold, "JSON_INVALID"):
            writer.fetch_canonical_ledger(HEAD)
        gh.return_value["size"] = len(raw) + 1
        with self.assertRaisesRegex(writer.LedgerWriteHold, "CONTENT_INVALID"):
            writer.fetch_canonical_ledger(HEAD)

    def test_reject_boolean_schema_and_overflowed_json_float(self):
        # bool is an int subclass in Python; true must never be schema 1.
        with self.assertRaisesRegex(writer.LedgerWriteHold,
                                    "^HOLD_CANONICAL_SCHEMA_INVALID$"):
            writer._json_load('{"schema_version":true}')
        # JSON 1e999 is syntactically legal but float() becomes infinity.
        with self.assertRaisesRegex(writer.LedgerWriteHold,
                                    "^HOLD_CANONICAL_JSON_INVALID$"):
            writer._json_load('{"schema_version":1,"metric":1e999}')
        self.assertEqual(
            writer._json_load('{"schema_version":1,"metric":0.75}')["metric"],
            0.75,
        )

    @patch.object(writer, "propose_authenticated_post_identity")
    @patch.object(writer, "fetch_canonical_ledger")
    @patch.object(writer, "fetch_canonical_head")
    def test_prepare_only_allowed_fields(self, head, fetch, propose):
        head.return_value = HEAD
        before = bound_ledger()
        fetch.return_value = (before, BLOB)
        after = copy.deepcopy(before)
        after["rotation_cohorts"]["app_jobs"][0]["status"] = "POST_IDENTITY_READY"
        propose.return_value = (after, "POST_IDENTITY_READY")
        prepared = writer.prepare(SLUG)
        self.assertEqual(prepared.expected_head, HEAD)
        self.assertEqual(prepared.expected_blob, BLOB)
        self.assertEqual(prepared.transition, "POST_IDENTITY_READY")
        self.assertIn('"updated_at_utc"', prepared.content)
        self.assertEqual(head.call_count, 2)
        after["policy"]["store_submission"] = True
        with self.assertRaisesRegex(writer.LedgerWriteHold, "UNRELATED_MUTATION"):
            writer.prepare(SLUG)

    @patch.object(writer, "propose_authenticated_post_identity")
    @patch.object(writer, "fetch_canonical_ledger")
    @patch.object(writer, "fetch_canonical_head", return_value=HEAD)
    def test_prepare_rejects_in_place_adapter_mutation(self, head, fetch, propose):
        # A future adapter might mutate the input and return that same dict.
        # Comparing before/after aliases must never hide a policy mutation.
        fetch.return_value = (ledger(), BLOB)

        def change_policy(source, slug):
            source["policy"]["store_submission"] = True
            return source, "POST_IDENTITY_READY"

        propose.side_effect = change_policy
        with self.assertRaisesRegex(writer.LedgerWriteHold,
                                    "^HOLD_CANONICAL_UNRELATED_MUTATION$"):
            writer.prepare(SLUG)

        fetch.return_value = (ledger(), BLOB)

        def escalate_product_gate(source, slug):
            source["new_product_allowed"] = True
            return source, "POST_IDENTITY_READY"

        propose.side_effect = escalate_product_gate
        with self.assertRaisesRegex(writer.LedgerWriteHold,
                                    "^HOLD_CANONICAL_GATE_ESCALATION$"):
            writer.prepare(SLUG)

    @patch.object(writer, "propose_authenticated_post_identity")
    @patch.object(writer, "fetch_canonical_ledger")
    @patch.object(writer, "fetch_canonical_head", return_value=HEAD)
    def test_prepare_rejects_target_provenance_rebinding(
            self, head, fetch, propose):
        cases = (
            ("rotation_cohorts", "app_jobs", "source_sha", COMMIT),
            ("user_id_requests", "items", "source_sha", COMMIT),
            ("registration_router", "entries", "registration_type", "GDK_GAME"),
            ("post_identity_pipeline", "products", "source_branch", "codex/other"),
        )
        for section, collection, field, replacement in cases:
            with self.subTest(section=section):
                before = bound_ledger()
                fetch.return_value = (before, BLOB)
                after = copy.deepcopy(before)
                after[section][collection][0][field] = replacement
                propose.return_value = (after, "POST_IDENTITY_READY")
                with self.assertRaisesRegex(
                        writer.LedgerWriteHold,
                        "^HOLD_CANONICAL_CROSS_PRODUCT_MUTATION$"):
                    writer.prepare(SLUG)

        # Removing or injecting an immutable binding is also a conflict.
        for mutation in ("delete", "inject"):
            with self.subTest(mutation=mutation):
                before = bound_ledger()
                fetch.return_value = (before, BLOB)
                after = copy.deepcopy(before)
                if mutation == "delete":
                    del after["rotation_cohorts"]["app_jobs"][0]["source_sha"]
                else:
                    after["registration_router"]["entries"][0]["source_sha"] = HEAD
                propose.return_value = (after, "POST_IDENTITY_READY")
                with self.assertRaisesRegex(
                        writer.LedgerWriteHold,
                        "^HOLD_CANONICAL_CROSS_PRODUCT_MUTATION$"):
                    writer.prepare(SLUG)

    @patch.object(writer, "propose_authenticated_post_identity")
    @patch.object(writer, "fetch_canonical_ledger")
    @patch.object(writer, "fetch_canonical_head", return_value=HEAD)
    def test_prepare_rejects_collateral_edits_inside_allowlisted_sections(
            self, head, fetch, propose):
        cases = (
            ("rotation_cohorts", "app_jobs", "status"),
            ("user_id_requests", "items", "status"),
            ("registration_router", "entries", "identity_status"),
            ("post_identity_pipeline", "products", "state"),
        )
        for section, collection, field in cases:
            with self.subTest(section=section):
                fetch.return_value = (bound_ledger(), BLOB)

                def collateral(source, slug):
                    source[section][collection][1][field] = "CORRUPTED"
                    return source, "POST_IDENTITY_READY"

                propose.side_effect = collateral
                with self.assertRaisesRegex(
                    writer.LedgerWriteHold,
                    "^HOLD_CANONICAL_CROSS_PRODUCT_MUTATION$",
                ):
                    writer.prepare(SLUG)

        fetch.return_value = (bound_ledger(), BLOB)

        def reorder(source, slug):
            source["rotation_cohorts"]["app_jobs"].reverse()
            return source, "POST_IDENTITY_READY"

        propose.side_effect = reorder
        with self.assertRaisesRegex(
            writer.LedgerWriteHold,
            "^HOLD_CANONICAL_CROSS_PRODUCT_MUTATION$",
        ):
            writer.prepare(SLUG)

        fetch.return_value = (bound_ledger(), BLOB)

        def mutate_metrics(source, slug):
            source["rotation_cohorts"]["total_jobs"] = 999
            return source, "POST_IDENTITY_READY"

        propose.side_effect = mutate_metrics
        with self.assertRaisesRegex(
            writer.LedgerWriteHold,
            "^HOLD_CANONICAL_CROSS_PRODUCT_MUTATION$",
        ):
            writer.prepare(SLUG)

    @patch.object(writer, "propose_authenticated_post_identity")
    @patch.object(writer, "fetch_canonical_ledger")
    @patch.object(writer, "fetch_canonical_head")
    def test_prepare_rejects_escalation_and_drift(self, head, fetch, propose):
        head.return_value = HEAD
        fetch.return_value = (bound_ledger(), BLOB)
        after = bound_ledger()
        after["e2e_pass"] = True
        propose.return_value = (after, "POST_IDENTITY_READY")
        with self.assertRaisesRegex(writer.LedgerWriteHold, "GATE_ESCALATION"):
            writer.prepare(SLUG)
        after["e2e_pass"] = False
        head.side_effect = [HEAD, COMMIT]
        with self.assertRaisesRegex(writer.LedgerWriteHold, "HEAD_DRIFT"):
            writer.prepare(SLUG)

    @patch.object(writer, "fetch_canonical_ledger")
    @patch.object(writer.subprocess, "run")
    @patch.object(writer, "fetch_canonical_head", return_value=HEAD)
    def test_atomic_expected_head_commit(self, head, run, readback):
        content = json.dumps(ledger()) + "\n"
        proposal = writer.PreparedLedger(HEAD, BLOB, SLUG,
                                         "EXISTING_VERIFIED", content)
        readback.return_value = (ledger(), writer._git_blob_sha(content))
        run.return_value = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({
                "data": {"createCommitOnBranch": {"commit": {"oid": COMMIT}}}
            }), stderr="",
        )
        result = writer.apply(proposal, reviewed_head=HEAD, reviewed_blob=BLOB,
                     reviewed_proposal_sha256=writer._proposal_sha256(proposal.content))
        self.assertEqual(result, COMMIT)
        self.assertEqual(run.call_args.args[0], ["gh", "api", "graphql", "--input", "-"])
        payload = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(payload["variables"]["input"]["expectedHeadOid"], HEAD)
        self.assertEqual(payload["variables"]["input"]["branch"]["branchName"],
                         writer.BRANCH)
        self.assertEqual(base64.b64decode(
            payload["variables"]["input"]["fileChanges"]["additions"][0]["contents"]
        ), content.encode())
        readback.assert_called_once_with(COMMIT)

    @patch.object(writer.subprocess, "run")
    @patch.object(writer, "fetch_canonical_head", return_value=HEAD)
    def test_apply_requires_review_of_substantive_proposal(self, head, run):
        # HEAD/blob alone pin the old ledger, not the authenticated proposal.
        # Audit timestamps vary between read-only review and explicit apply.
        original = json.dumps(ledger()) + "\n"
        proposal = writer.PreparedLedger(HEAD, BLOB, SLUG,
                                         "POST_IDENTITY_READY", original)
        digest = writer._proposal_sha256(original)
        self.assertEqual(len(digest), 64)
        with self.assertRaisesRegex(
                writer.LedgerWriteHold,
                "^HOLD_CANONICAL_PROPOSAL_REVIEW_MISMATCH$"):
            writer.apply(proposal, reviewed_head=HEAD, reviewed_blob=BLOB,
                         reviewed_proposal_sha256="0" * 64)
        with_timestamp = copy.deepcopy(ledger())
        with_timestamp["updated_at_utc"] = "2026-10-31T06:30:00Z"
        next_timestamp = copy.deepcopy(with_timestamp)
        next_timestamp["updated_at_utc"] = "2026-10-31T06:40:00Z"
        self.assertEqual(writer._proposal_sha256(json.dumps(with_timestamp)),
                         writer._proposal_sha256(json.dumps(next_timestamp)))
        changed = copy.deepcopy(with_timestamp)
        changed["rotation_cohorts"]["app_jobs"].append({"slug": "wrong-product"})
        mutated = writer.PreparedLedger(HEAD, BLOB, SLUG,
                                        "POST_IDENTITY_READY", json.dumps(changed))
        with self.assertRaisesRegex(
                writer.LedgerWriteHold,
                "^HOLD_CANONICAL_PROPOSAL_REVIEW_MISMATCH$"):
            writer.apply(mutated, reviewed_head=HEAD, reviewed_blob=BLOB,
                         reviewed_proposal_sha256=digest)
        run.assert_not_called()

    @patch.object(writer, "fetch_canonical_ledger")
    @patch.object(writer.subprocess, "run")
    @patch.object(writer, "fetch_canonical_head", return_value=HEAD)
    def test_postwrite_readback_rejects_mismatch(self, head, run, readback):
        content = json.dumps(ledger()) + "\n"
        proposal = writer.PreparedLedger(HEAD, BLOB, SLUG,
                                         "POST_IDENTITY_READY", content)
        run.return_value = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({
                "data": {"createCommitOnBranch": {"commit": {"oid": COMMIT}}}
            }), stderr="",
        )
        readback.return_value = (ledger(), "d" * 40)
        with self.assertRaisesRegex(writer.LedgerWriteHold,
                                    "HOLD_CANONICAL_POSTWRITE_CONTENT_MISMATCH"):
            writer.apply(proposal, reviewed_head=HEAD, reviewed_blob=BLOB,
                     reviewed_proposal_sha256=writer._proposal_sha256(proposal.content))
        wrong = ledger()
        wrong["e2e_pass"] = True
        readback.return_value = (wrong, writer._git_blob_sha(content))
        with self.assertRaisesRegex(writer.LedgerWriteHold,
                                    "HOLD_CANONICAL_POSTWRITE_CONTENT_MISMATCH"):
            writer.apply(proposal, reviewed_head=HEAD, reviewed_blob=BLOB,
                     reviewed_proposal_sha256=writer._proposal_sha256(proposal.content))

    @patch.object(writer, "fetch_canonical_ledger")
    @patch.object(writer.subprocess, "run")
    @patch.object(writer, "fetch_canonical_head", return_value=HEAD)
    def test_postwrite_unavailable_fails_closed(self, head, run, readback):
        proposal = writer.PreparedLedger(HEAD, BLOB, SLUG,
                                         "POST_IDENTITY_READY", "{}")
        run.return_value = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({
                "data": {"createCommitOnBranch": {"commit": {"oid": COMMIT}}}
            }), stderr="",
        )
        readback.side_effect = writer.LedgerWriteHold("internal secret")
        with self.assertRaisesRegex(writer.LedgerWriteHold,
                                    "^HOLD_CANONICAL_POSTWRITE_READ_UNAVAILABLE$"):
            writer.apply(proposal, reviewed_head=HEAD, reviewed_blob=BLOB,
                     reviewed_proposal_sha256=writer._proposal_sha256(proposal.content))

    @patch.object(writer.subprocess, "run")
    @patch.object(writer, "fetch_canonical_head", return_value=HEAD)
    def test_no_write_on_review_mismatch_or_head_drift(self, head, run):
        proposal = writer.PreparedLedger(HEAD, BLOB, SLUG,
                                         "POST_IDENTITY_READY", "{}")
        with self.assertRaisesRegex(writer.LedgerWriteHold, "REVIEW_PIN_MISMATCH"):
            writer.apply(proposal, reviewed_head=COMMIT, reviewed_blob=BLOB,
                         reviewed_proposal_sha256=writer._proposal_sha256(proposal.content))
        run.assert_not_called()
        head.return_value = COMMIT
        with self.assertRaisesRegex(writer.LedgerWriteHold, "HEAD_DRIFT"):
            writer.apply(proposal, reviewed_head=HEAD, reviewed_blob=BLOB,
                     reviewed_proposal_sha256=writer._proposal_sha256(proposal.content))
        run.assert_not_called()

    @patch.object(writer.subprocess, "run")
    @patch.object(writer, "fetch_canonical_head", return_value=HEAD)
    def test_graphql_rejection_is_fail_closed_secret_safe(self, head, run):
        proposal = writer.PreparedLedger(HEAD, BLOB, SLUG,
                                         "POST_IDENTITY_READY", "{}")
        run.return_value = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({
                "errors": [{"message": "token=private-credential"}]
            }), stderr="secret",
        )
        with self.assertRaisesRegex(writer.LedgerWriteHold,
                                    "^HOLD_CANONICAL_ATOMIC_WRITE_REJECTED$"):
            writer.apply(proposal, reviewed_head=HEAD, reviewed_blob=BLOB,
                     reviewed_proposal_sha256=writer._proposal_sha256(proposal.content))

    @patch.object(writer, "prepare")
    @patch.object(writer, "apply")
    def test_default_cli_does_not_apply(self, apply, prepare):
        prepare.return_value = writer.PreparedLedger(
            HEAD, BLOB, SLUG, "EXISTING_VERIFIED", "{}")
        self.assertEqual(writer.main(["--slug", SLUG]), 0)
        apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
