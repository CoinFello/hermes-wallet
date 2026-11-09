"""The desktop half's card bridge, from pytest.

Runs tests/card_bridge.test.mjs under node (skipped when node is missing), and
checks that desktop/plugin.js and coinfello_cards.py allow the same tools per
card: the allowlist is enforced in both places, so the two copies must agree.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import coinfello_cards as cards

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

DUMP = """
const fs = require('fs')
const source = fs.readFileSync(process.argv[1], 'utf8')
const body = source.slice(source.indexOf('/* card-bridge:start */'), source.indexOf('/* card-bridge:end */'))
const tables = new Function(body + '\\nreturn { tools: CARD_TOOLS, always: CARD_ALWAYS_RELAYED, retryable: CARD_RETRYABLE_TOOLS, never: CARD_NEVER_RELAYED }')()
console.log(JSON.stringify(tables))
"""


def test_the_bridge_suite_passes():
    run = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "card_bridge.test.mjs")],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "# fail 0" in run.stdout or "fail 0" in run.stdout


def test_pane_and_backend_allow_the_same_tools():
    run = subprocess.run(
        [NODE, "-e", DUMP, str(ROOT / "desktop" / "plugin.js")],
        capture_output=True, text=True, timeout=60, check=True,
    )
    pane = json.loads(run.stdout)
    backend = {
        card.uri: {"tool": card.tool, "relay": sorted(card.relay), "confirm": sorted(card.confirm)}
        for card in cards.CARDS.values()
    }
    assert {uri: {"tool": t["tool"], "relay": sorted(t["relay"]), "confirm": sorted(t["confirm"])}
            for uri, t in pane["tools"].items()} == backend
    assert sorted(pane["always"]) == sorted(cards.ALWAYS_RELAYED)
    assert sorted(pane["retryable"]) == sorted(cards.RETRYABLE_TOOLS)
    assert sorted(pane["never"]) == sorted(cards.NEVER_RELAYED)
