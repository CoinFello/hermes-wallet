"""Sign in again as the SAME account, not whatever wallet the browser offers.

Reported: after signing out in the pane, the browser sign-in prompted for a
MetaMask wallet (a different CoinFello account). The plugin now remembers a
non-secret hint of its account, sends it to servers that accept it, names
the account in the steps, and warns to cancel wallet prompts.
"""

from __future__ import annotations

import pytest

import coinfello_core as core


@pytest.fixture
def server(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp")
    mock_mcp.mock_state.update(browser_sign_in=True, access_mode=True)
    core.save_state({"session_token": "tok-old", "wallet_address": "0x2222000000000000000000000000000000002222",
                     "signed_in_as": "jane@example.com"})
    return mock_mcp


def _start_args(server):
    return [args for name, args in server.mock_state["tool_calls"] if name == "start_browser_sign_in"][-1]


def test_sign_out_keeps_only_a_non_secret_account_hint(server):
    core.save_state({"access": "trade", "daily_limit_usd": 250, "pending_limit_change_id": "x"})
    core.disconnect(wait=True)
    state = core.load_state()
    assert state["session_token"] == ""
    assert state["access"] is None and state["daily_limit_usd"] is None
    assert state["pending_limit_change_id"] == ""
    assert state["last_signed_in_as"] == "jane@example.com"
    assert state["last_wallet_address"].startswith("0x2222")
    assert core.status()["account_hint"] == "j…@example.com"


def test_hint_is_sent_to_servers_that_accept_it(server):
    server.mock_state["account_hint"] = True
    core.disconnect(wait=True)
    core.connect()
    args = _start_args(server)
    assert args["expected_wallet"].startswith("0x2222")
    assert args["expected_email"] == "jane@example.com"


def test_hint_is_not_sent_to_servers_that_did_not_advertise_it(server):
    core.disconnect(wait=True)
    core.connect()
    assert _start_args(server) == {}


def test_steps_name_the_account_and_warn_about_wallet_prompts(server):
    core.disconnect(wait=True)
    step = core.sign_in_steps("C0DE", "https://x/authorize")[1]
    assert "j…@example.com" in step
    assert "jane" not in step  # masked on screen
    assert "MetaMask" in step and "cancel it" in step


def test_use_a_different_account_drops_the_hint(server):
    server.mock_state["account_hint"] = True
    core.disconnect(wait=True)
    core.forget_account_hint()
    assert core.status()["account_hint"] == ""
    core.connect()
    assert _start_args(server) == {}
    assert "your CoinFello account" in core.sign_in_steps("C0DE", "https://x/authorize")[1]


@pytest.mark.parametrize(("raw", "masked"), [
    ("jane@example.com", "j…@example.com"),
    ("+17875550100", "+17875550100"),  # a phone sign-in has no email to mask
    ("", ""),
])
def test_mask_email(raw, masked):
    assert core.mask_email(raw) == masked
