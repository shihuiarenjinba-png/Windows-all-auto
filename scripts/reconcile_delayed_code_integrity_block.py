from __future__ import annotations

from pathlib import Path
import runpy


if __name__ == "__main__":
    target = Path(__file__).with_name("reconcile_delayed_code_integrity_launch.py")
    if not target.is_file():
        raise SystemExit("reconcile_delayed_code_integrity_launch.py is missing")
    runpy.run_path(str(target), run_name="__main__")
