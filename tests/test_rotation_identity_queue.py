"""Rotation regression tests: pure cloud contracts, never CAS or local GUI."""
import copy
import unittest

from scripts import rotation_identity_queue as q
from scripts import pre_identity_queue
from scripts import local_identity_scheduler as s

SHA = "a" * 40
PROVISIONER_SHA = "b" * 40
GAME = s.OWNER + "/AI-Game-Factory"
PROVISIONER = s.OWNER + "/Repository-Provisioner-game"
BRANCH = "codex/game-signal-sprint-undo-20261027"
PBRANCH = "codex/game-identity-idempotency-20261027"


def fixture():
    rid = "game-signal-sprint-" + SHA
    return {
        "e2e_pass": False, "new_product_allowed": False,
        "active_product": {
            "request_id": rid, "product_type": "GAME", "slug": "signal-sprint",
            "source_sha": SHA, "expected_head_sha": SHA,
            "source_repository": GAME, "source_branch": BRANCH,
            "provisioner_repository": PROVISIONER,
            "provisioner_branch": PBRANCH, "provisioner_head_observed": PROVISIONER_SHA,
            "factory_exe_artifact_kind": "EXE_QA_UNSIGNED_NOT_MSIX",
            "local_execution_result": {"package_kind": "exe",
                                       "package_status": "INSPECTED",
                                       "package_sha256": "c" * 64},
        },
        "other_lanes": {"APP": {"canary_proposal": {
            "slug": "offline-notes-canary", "source_sha": None, "request_id": None}}},
        "user_id_requests": {"items": [{
            "product_name": "Signal Sprint", "request_id": rid,
            "status": "USER_IDENTITY_RECEIVED", "repo": GAME,
            "source_branch": BRANCH, "source_sha": SHA,
            "identity_target": q.TARGET,
        }]},
    }


APP_SHA = "d" * 40
BUILD_SHA = "e" * 40
THREE_D_SHA = "f" * 40
DIGEST = "1" * 64


def rotated(app_count=5, three_d=True):
    ledger = fixture()
    apps = []
    for n in range(app_count):
        slug = "notes-rotation-" + str(n)
        rid = "app-rotation-request-" + str(n)
        app = {
            "product_type": "APP", "display_name": "Notes rotation " + str(n),
            "slug": slug, "request_id": rid,
            "source_repository": q.APP_REPO, "source_branch": "codex/app-" + str(n),
            "source_sha": APP_SHA, "factory_build_branch": "codex/app-build-" + str(n),
            "factory_build_head": BUILD_SHA, "expected_exe_sha256": DIGEST,
            "artifact_id": 12345, "artifact_run_id": 67890,
            "artifact_zip_sha256": "2" * 64,
            "artifact_provenance": "REAL_WINDOWS_EXPORT_VERIFIED",
            "status": "PRE_IDENTITY_READY", "packaging_family": "MSIX",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app",
        }
        apps.append(app)
        ledger["user_id_requests"]["items"].append({
            "product_name": app["display_name"], "request_id": rid,
            "repo": q.APP_REPO, "source_branch": app["source_branch"],
            "source_sha": APP_SHA, "slug": slug, "product_type": "APP",
            "identity_target": q.TARGET, "status": "WAITING_USER_IDENTITY",
        })
    games = []
    if three_d:
        game = {
            "product_type": "GAME_3D", "display_name": "Prism Route 3D",
            "slug": "prism-route-3d", "request_id": "3d-prism-route-3d-" + THREE_D_SHA[:12],
            "source_repository": q.THREE_D_REPO,
            "source_branch": "codex/3d-prism-source", "source_sha": THREE_D_SHA,
            "factory_build_branch": "codex/3d-prism-build",
            "factory_build_head": BUILD_SHA, "expected_exe_sha256": DIGEST,
            "artifact_id": 12345, "artifact_run_id": 67890,
            "artifact_zip_sha256": "2" * 64,
            "artifact_provenance": "REAL_WINDOWS_EXPORT_VERIFIED",
            "packaging_strategy": "GODOT_WINDOWS_EXE_PCK_MAKEAPPX_MSIX",
            "packaging_family": "MSIX", "registration_type": "MSIX_OR_PWA_GAME",
            "partner_center_selection": "MSIX or PWA game", "status": "PRE_IDENTITY_READY",
        }
        games.append(game)
        ledger["user_id_requests"]["items"].append({
            "product_name": game["display_name"], "request_id": game["request_id"],
            "repo": q.THREE_D_REPO, "source_branch": game["source_branch"],
            "source_sha": THREE_D_SHA, "slug": game["slug"], "product_type": "GAME_3D",
            "identity_target": q.TARGET, "status": "WAITING_USER_IDENTITY",
        })
    ledger["rotation_cohorts"] = {"app_jobs": apps, "three_d_jobs": games}
    return ledger


def head(repo, branch):
    if (repo, branch) == (GAME, BRANCH):
        return SHA
    if (repo, branch) == (PROVISIONER, PBRANCH):
        return PROVISIONER_SHA
    if repo == q.APP_REPO:
        return BUILD_SHA if "build" in branch else APP_SHA
    if repo == q.THREE_D_REPO:
        return BUILD_SHA if "build" in branch else THREE_D_SHA
    raise AssertionError("unexpected remote HEAD request")


class RotationQueueTests(unittest.TestCase):
    def test_five_apps_and_one_3d_queue_without_cas(self):
        result = q.project(rotated(), head)
        self.assertEqual(len(result["jobs"]), 7)
        self.assertFalse(result["ready_for_cas"])
        self.assertEqual(result["rotation_metrics"]["pre_identity_pass"], 5)
        self.assertEqual(result["rotation_metrics"]["3d_pre_identity_pass"], 1)
        self.assertEqual(result["rotation_metrics"]["waiting_user_identity"], 5)
        self.assertEqual(result["rotation_metrics"]["3d_waiting_identity"], 1)
        self.assertEqual(result["jobs"][-1]["kind"], "GAME_3D_CANARY")

    def test_received_identity_only_promotes_its_own_app(self):
        data = rotated(2, False)
        data["user_id_requests"]["items"][1]["status"] = "USER_IDENTITY_RECEIVED"
        result = q.project(data, head)
        self.assertEqual(result["rotation_metrics"]["identity_received"], 1)
        self.assertEqual(result["rotation_metrics"]["waiting_user_identity"], 1)
        self.assertNotIn("store_id", str(result))

    def test_cross_product_request_rejected(self):
        data = rotated(2, False)
        data["user_id_requests"]["items"][2]["slug"] = "notes-rotation-0"
        with self.assertRaisesRegex(pre_identity_queue.QueueHold, "CROSS_PRODUCT"):
            q.project(data, head)

    def test_duplicate_request_id_rejected(self):
        data = rotated(2, False)
        data["rotation_cohorts"]["app_jobs"][1]["request_id"] = data["rotation_cohorts"]["app_jobs"][0]["request_id"]
        with self.assertRaises(pre_identity_queue.QueueHold):
            q.project(data, head)

    def test_artifact_mismatch_fails_closed(self):
        data = rotated(1, False)
        data["rotation_cohorts"]["app_jobs"][0]["expected_exe_sha256"] = "not-a-digest"
        with self.assertRaisesRegex(pre_identity_queue.QueueHold, "PROVENANCE"):
            q.project(data, head)

    def test_artifact_zip_digest_required(self):
        data = rotated(1, False)
        data["rotation_cohorts"]["app_jobs"][0]["artifact_zip_sha256"] = None
        with self.assertRaisesRegex(pre_identity_queue.QueueHold, "PROVENANCE"):
            q.project(data, head)

    def test_product_display_name_cannot_cross_identity_request(self):
        data = rotated(1, False)
        data["user_id_requests"]["items"][1]["product_name"] = "Another product"
        with self.assertRaisesRegex(pre_identity_queue.QueueHold, "CROSS_PRODUCT"):
            q.project(data, head)

    def test_head_change_fails_closed(self):
        data = rotated(1, False)
        def moved(repo, branch):
            if repo == q.APP_REPO and branch == "codex/app-0":
                return "0" * 40
            return head(repo, branch)
        with self.assertRaisesRegex(pre_identity_queue.QueueHold, "SOURCE_HEAD_CONFLICT"):
            q.project(data, moved)

    def test_3d_gdk_misclassification_rejected(self):
        data = rotated(0, True)
        data["rotation_cohorts"]["three_d_jobs"][0]["registration_type"] = "GDK_GAME"
        with self.assertRaisesRegex(pre_identity_queue.QueueHold, "THREE_D_REGISTRATION_CONFLICT"):
            q.project(data, head)

    def test_pending_3d_does_not_block_app(self):
        data = rotated(1, True)
        data["rotation_cohorts"]["three_d_jobs"][0]["status"] = "EXPORT_PENDING"
        result = q.project(data, head)
        self.assertEqual(len(result["jobs"]), 2)
        self.assertEqual(result["rotation_metrics"]["3d_pre_identity_pass"], 0)
        self.assertEqual(result["deferred"][-1]["status"], "NOT_YET_REQUIRED")

    def test_app_cohort_max_five(self):
        data = rotated(5, False)
        data["rotation_cohorts"]["app_jobs"].append(copy.deepcopy(data["rotation_cohorts"]["app_jobs"][0]))
        with self.assertRaisesRegex(pre_identity_queue.QueueHold, "CAP_EXCEEDED"):
            q.project(data, head)

    def test_promoted_primary_app_counts_toward_five_cap(self):
        data = rotated(5, False)
        candidate = data["other_lanes"]["APP"]["canary_proposal"]
        candidate.update({
            "status": "PROMOTED", "source_sha": APP_SHA,
            "request_id": "app-offline-promoted-20261028",
            "exe_sha256": DIGEST, "branch": "codex/offline-promoted",
        })
        data["user_id_requests"]["items"].append({
            "product_name": "Offline Notes Canary",
            "request_id": candidate["request_id"],
            "status": "USER_IDENTITY_RECEIVED",
            "repo": q.APP_REPO, "source_branch": candidate["branch"],
            "source_sha": APP_SHA, "identity_target": q.TARGET,
        })
        with self.assertRaisesRegex(pre_identity_queue.QueueHold, "CAP_EXCEEDED"):
            q.project(data, head)

    def test_3d_identity_cannot_be_reused_by_app(self):
        data = rotated(1, True)
        data["user_id_requests"]["items"][-1]["repo"] = q.APP_REPO
        with self.assertRaisesRegex(pre_identity_queue.QueueHold, "CROSS_PRODUCT"):
            q.project(data, head)

    def test_real_prism_route_factory_provenance_correlates(self):
        """The independently verified 2026-10-28 Factory/Provisioner receipt
        must queue only the exact Prism Route 3D source, never perform CAS."""
        data = rotated(0, True)
        item = data["rotation_cohorts"]["three_d_jobs"][0]
        real_sha = "15fdcb52e46e35e6de8e87c55af99719c21e09b9"
        real_branch = "codex/3d-canary-prism-route-20261028"
        real_request = "3d-prism-route-3d-15fdcb52e46e"
        item.update({
            "request_id": real_request, "source_sha": real_sha,
            "source_branch": real_branch, "factory_build_branch": real_branch,
            "factory_build_head": real_sha,
            "expected_exe_sha256": "66b26ad96df7458ea917b632a73ac7c88bb058db24dbd11a457fd50435ab7b13",
            "artifact_id": 12795476435, "artifact_run_id": 40640951915,
            "artifact_zip_sha256": "76b5fae99491b70514e3152483e0192ac70b2909d8f6eeb9802a640ad12409b0",
            "artifact_provenance": "REAL_WINDOWS_EXPORT_VERIFIED",
        })
        request = data["user_id_requests"]["items"][-1]
        request.update({"request_id": real_request, "source_sha": real_sha,
                        "source_branch": real_branch})
        def observed_head(repo, branch):
            if repo == q.THREE_D_REPO:
                self.assertEqual(branch, real_branch)
                return real_sha
            return head(repo, branch)
        result = q.project(data, observed_head)
        job = result["jobs"][-1]
        self.assertEqual(job["request_id"], real_request)
        self.assertEqual(job["artifact_id"], 12795476435)
        self.assertEqual(job["package_sha256"], item["expected_exe_sha256"])
        self.assertEqual(job["registration_type"], "MSIX_OR_PWA_GAME")
        self.assertEqual(job["identity_status"], "WAITING_USER_IDENTITY")
        self.assertEqual(result["rotation_metrics"]["3d_pre_identity_pass"], 1)
        self.assertFalse(result["ready_for_cas"])

        # A later Factory HEAD, wrong Identity request or unverified Artifact
        # must never be silently accepted as a different product.
        with self.assertRaisesRegex(pre_identity_queue.QueueHold, "SOURCE_HEAD_CONFLICT"):
            q.project(data, lambda repo, branch: "0" * 40
                      if repo == q.THREE_D_REPO else head(repo, branch))
        request["source_sha"] = "0" * 40
        with self.assertRaisesRegex(pre_identity_queue.QueueHold, "CROSS_PRODUCT"):
            q.project(data, observed_head)
        request["source_sha"] = real_sha
        item["artifact_provenance"] = "PENDING_INDEPENDENT_REAL_EXPORT_VERIFICATION"
        with self.assertRaisesRegex(pre_identity_queue.QueueHold, "ARTIFACT_NOT_VERIFIED"):
            q.project(data, observed_head)

    def test_empty_rotation_preserves_base_queue(self):
        result = q.project(fixture(), head)
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["rotation_metrics"]["total_jobs"], 0)


if __name__ == "__main__":
    unittest.main()
