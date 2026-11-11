"""The desktop pane must not reference an undefined name.

Nothing else here renders desktop/plugin.js, so a name that moved out of
scope (0.3.1's `appOrigin`) passed every test and validation and only failed
when Hermes drew the pane: "appOrigin is not defined", a blank pane.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("npx") is None, reason="needs Node.js (npx)")
def test_pane_has_no_undefined_names():
    result = subprocess.run(
        [
            "npx", "--yes", "eslint@9.17.0", "--no-config-lookup",
            "-c", str(ROOT / "tests" / "eslint.undef.mjs"),
            str(ROOT / "desktop" / "plugin.js"),
        ],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
