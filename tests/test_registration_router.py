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


if __name__ == "__main__":
    unittest.main()
