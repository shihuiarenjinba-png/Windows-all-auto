from __future__ import annotations

import unittest

from all_auto.group_c_rollout_guard import ProductBinding, binding_state, next_stage_after_teacher


def binding(**overrides):
    values = dict(
        product_id="fixture-product",
        repository_full_name="owner/repo",
        source_branch="codex/store-product",
        source_sha="a" * 40,
        current_remote_sha="a" * 40,
        store_id="9P1234567890",
        draft_id="1152921505702212222",
        submission_route="msix_pwa_app",
    )
    values.update(overrides)
    return ProductBinding(**values)


class GroupCRolloutGuardTests(unittest.TestCase):
    def test_complete_binding_is_accepted(self):
        self.assertEqual(binding_state(binding()), "REGISTRY_BOUND")

    def test_missing_source_store_or_draft_never_becomes_ready(self):
        for kwargs in (
            {"source_sha": None},
            {"source_branch": None},
            {"store_id": None},
            {"draft_id": None},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(binding_state(binding(**kwargs)), "HOLD_REGISTRY_BINDING_REQUIRED")

    def test_stale_registry_source_sha_requires_rebind(self):
        self.assertEqual(
            binding_state(binding(current_remote_sha="b" * 40)),
            "HOLD_SOURCE_HEAD_REBIND_REQUIRED",
        )

    def test_previous_teacher_blocks_next_product(self):
        self.assertEqual(
            next_stage_after_teacher(
                binding(),
                teacher_previous_complete=False,
                windows_real_device_qa_pass=True,
                formal_store_version_approved=True,
                final_artwork_approved=True,
                manifest_languages_approved=True,
                formal_msix_frozen=True,
            ),
            "WAITING_FOR_PREVIOUS_PRODUCT",
        )

    def test_bound_product_starts_at_real_device_qa(self):
        self.assertEqual(
            next_stage_after_teacher(
                binding(),
                teacher_previous_complete=True,
                windows_real_device_qa_pass=False,
                formal_store_version_approved=False,
                final_artwork_approved=False,
                manifest_languages_approved=False,
                formal_msix_frozen=False,
            ),
            "READY_FOR_WINDOWS_REAL_DEVICE_QA",
        )

    def test_formal_values_are_required_before_formal_msix(self):
        self.assertEqual(
            next_stage_after_teacher(
                binding(),
                teacher_previous_complete=True,
                windows_real_device_qa_pass=True,
                formal_store_version_approved=True,
                final_artwork_approved=False,
                manifest_languages_approved=True,
                formal_msix_frozen=False,
            ),
            "HOLD_FORMAL_STORE_VALUES_REQUIRED",
        )

    def test_upload_readiness_requires_frozen_formal_msix(self):
        common = dict(
            teacher_previous_complete=True,
            windows_real_device_qa_pass=True,
            formal_store_version_approved=True,
            final_artwork_approved=True,
            manifest_languages_approved=True,
        )
        self.assertEqual(
            next_stage_after_teacher(binding(), formal_msix_frozen=False, **common),
            "READY_FOR_FORMAL_STORE_MSIX",
        )
        self.assertEqual(
            next_stage_after_teacher(binding(), formal_msix_frozen=True, **common),
            "READY_FOR_PARTNER_CENTER_PACKAGE_UPLOAD",
        )


if __name__ == "__main__":
    unittest.main()
