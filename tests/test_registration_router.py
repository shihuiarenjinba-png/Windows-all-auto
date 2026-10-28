"""Registration routing contract tests; no network, local Windows or CAS."""
import unittest

from scripts import registration_router as router


class RegistrationRouterTests(unittest.TestCase):
    def test_signal_sprint_is_gdk_even_when_exe_is_intermediate(self):
        self.assertEqual(router.resolve("GAME", "signal-sprint"),
                         ("GDK_GAME", "GDK game"))

    def test_offline_notes_is_msix_even_when_exe_is_intermediate(self):
        self.assertEqual(router.resolve("APP", "offline-notes-canary"),
                         ("MSIX_OR_PWA_APP", "MSIX or PWA app"))

    def test_four_selections(self):
        for product_type, slug, strategy, expected in (
            ("APP", "another-app", "MSIX", "MSIX_OR_PWA_APP"),
            ("APP", "another-app", "EXE_OR_MSI", "EXE_OR_MSI_APP"),
            ("GAME", "another-game", "GDK", "GDK_GAME"),
            ("GAME", "another-game", "MSIX", "MSIX_OR_PWA_GAME"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(router.resolve(product_type, slug, strategy)[0], expected)

    def test_unknown_3d_strategy_fails_closed(self):
        with self.assertRaisesRegex(router.RegistrationHold,
                                    "HOLD_REGISTRATION_TYPE_UNRESOLVED"):
            router.resolve("GAME_3D", "unpromoted-3d")

    def test_exe_artifact_is_not_final_strategy(self):
        with self.assertRaisesRegex(router.RegistrationHold,
                                    "HOLD_REGISTRATION_TYPE_UNRESOLVED"):
            router.resolve("APP", "another-app", "EXE")

    def test_pinned_strategy_cannot_be_overridden(self):
        with self.assertRaisesRegex(router.RegistrationHold,
                                    "REGISTRATION_STRATEGY_CONFLICT"):
            router.resolve("GAME", "signal-sprint", "EXE_OR_MSI")

    def test_declared_type_conflict_fails_closed(self):
        with self.assertRaisesRegex(router.RegistrationHold,
                                    "REGISTRATION_TYPE_CONFLICT"):
            router.resolve("APP", "offline-notes-canary",
                           declared="EXE_OR_MSI_APP")

    def test_selection_must_match_machine_type(self):
        with self.assertRaisesRegex(router.RegistrationHold,
                                    "REGISTRATION_SELECTION_CONFLICT"):
            router.validate_handoff_job({
                "kind": "GAME_SIGNAL_SPRINT", "registration_type": "GDK_GAME",
                "partner_center_selection": "MSIX or PWA game"})

    def test_game_cannot_route_to_non_gdk(self):
        with self.assertRaisesRegex(router.RegistrationHold,
                                    "REGISTRATION_TYPE_CONFLICT"):
            router.validate_handoff_job({
                "kind": "GAME_SIGNAL_SPRINT",
                "registration_type": "MSIX_OR_PWA_GAME",
                "partner_center_selection": "MSIX or PWA game"})

    def test_legacy_job_without_registration_metadata_is_readable(self):
        router.validate_handoff_job({"kind": "GAME_SIGNAL_SPRINT"})

    def test_new_job_has_valid_registration_metadata(self):
        router.validate_handoff_job({
            "kind": "APP_CANARY",
            "registration_type": "MSIX_OR_PWA_APP",
            "partner_center_selection": "MSIX or PWA app"})

    def test_intermediate_exe_is_recorded_without_changing_msix_app_route(self):
        result = router.registration_contract(
            "APP", "new-app", "MSIX", "EXE_PRE_PACKAGE",
            ["factory:msix", "provisioner:manifest-verified"], "NOT_RECEIVED")
        self.assertEqual(result["registration_type"], "MSIX_OR_PWA_APP")
        self.assertEqual(result["build_artifact_kind"], "EXE_PRE_PACKAGE")
        self.assertEqual(result["registration_event"], "USER_ID_REQUEST")
        self.assertTrue(result["user_registration_required"])
        self.assertIn("MSIX_OR_PWA_APP", result["next_action"])

    def test_received_identity_is_not_requested_again(self):
        result = router.registration_contract(
            "GAME", "signal-sprint", "GDK", "EXE_QA_UNSIGNED_NOT_MSIX",
            ["factory:gdk", "provisioner:gdk"], "RECEIVED", "GDK_GAME")
        self.assertFalse(result["user_registration_required"])
        self.assertEqual(result["registration_event"],
                         "PARTNER_CENTER_REGISTRATION_REQUEST")
        self.assertEqual(result["next_action"],
                         "NO_PARTNER_CENTER_ACTION_IDENTITY_ALREADY_RECEIVED")

    def test_gdk_requires_xbox_fields_but_msix_app_does_not(self):
        gdk = router.registration_contract(
            "GAME", "signal-sprint", "GDK", "EXE",
            ["factory:gdk"], "NOT_RECEIVED")
        app = router.registration_contract(
            "APP", "offline-notes-canary", "MSIX", "EXE",
            ["factory:msix"], "NOT_RECEIVED")
        self.assertEqual(gdk["required_identity_fields"][-3:],
                         ["xbox_title_id", "xbox_scid", "msa_app_id"])
        self.assertFalse(any("xbox" in item for item in app["required_identity_fields"]))

    def test_gdk_handoff_missing_xbox_requirements_is_rejected(self):
        route = router.registration_contract(
            "GAME", "signal-sprint", "GDK", "EXE",
            ["factory:gdk"], "NOT_RECEIVED")
        job = {"kind": "GAME_SIGNAL_SPRINT", "slug": "signal-sprint", **route}
        job["required_identity_fields"] = router.BASE_IDENTITY_FIELDS
        with self.assertRaisesRegex(router.RegistrationHold,
                                    "REGISTRATION_HANDOFF_CONFLICT"):
            router.validate_handoff_job(job)


if __name__ == "__main__":
    unittest.main()
