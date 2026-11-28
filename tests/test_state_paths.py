from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from all_auto.state_paths import product_state_dir, state_root


class StatePathTests(unittest.TestCase):
    def test_explicit_state_root_is_shared_and_product_scoped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "state"
            with patch.dict(os.environ, {"WINDOWS_ALL_AUTO_STATE_DIR": str(root)}):
                self.assertEqual(state_root(Path(temporary)), root.resolve())
                self.assertEqual(product_state_dir("data-contract-auditor", Path(temporary)),
                                 root.resolve() / "data-contract-auditor")

    def test_legacy_ledger_is_reused_when_present(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            legacy = home / "Desktop" / "Windows-all-auto-dca-upload" / ".uploader-run"
            legacy.mkdir(parents=True)
            with patch.dict(os.environ, {"WINDOWS_ALL_AUTO_STATE_DIR": ""}), patch("pathlib.Path.home", return_value=home):
                self.assertEqual(state_root(Path(temporary)), legacy.resolve())

    def test_repo_local_state_is_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            with patch.dict(os.environ, {"WINDOWS_ALL_AUTO_STATE_DIR": ""}), patch("pathlib.Path.home", return_value=Path(temporary) / "no-home"):
                self.assertEqual(state_root(repo), repo / ".uploader-run")

    def test_invalid_product_key_is_rejected(self):
        with self.assertRaises(ValueError):
            product_state_dir("../other", Path.cwd())


if __name__ == "__main__":
    unittest.main()
