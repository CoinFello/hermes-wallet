"""Session access: read-only vs trading, and how the
plugin explains signing in.

The failure this guards against: the agent told the human "open the link,
enter the code", the page asked for a CoinFello login first, and the login
looked like a mistake. The plugin now owns the wording (user_message, in the
page's order), knows when a session is read-only, and says how to upgrade.
"""

from __future__ import annotations

import time

import pytest

import coinfello_core as core


@pytest.fixture
def server(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp")
    mock_mcp.mock_state.update(browser_sign_in=True, actions=True, access_mode=True)
    return mock_mcp


@pytest.fixture
def read_only(server):
    # A session from an older server, or an email-code sign-in: read-only.
    core.save_state({"signed_in": True, "test_grant": "tok-old", "wallet_address": "0xWALLET",
                     "signed_in_as": "jacob@example.com"})
    return server


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# -- read-only state ---------------------------------------------------------------

def test_status_reports_read_only_and_how_to_upgrade(read_only):
    status = core.status()
    assert status["access"] == "read_only"
    assert status["can_trade"] is False
    assert "coinfello_set_daily_limit" in status["next"]
    assert core.load_state()["access"] == "read_only"  # cached for trading_call


def test_read_only_disables_send_and_swap(read_only):
    core.status()
    model = core.portfolio()
    assert model["can_trade"] is False
    assert model["can_send"] is False and model["can_swap"] is False


def test_trades_are_refused_locally_once_read_only_is_known(read_only):
    core.status()
    with pytest.raises(core.NeedsTradingAccess) as excinfo:
        core.prepare_send(8453, "0xUSDC", "1", "0x1111111111111111111111111111111111111111")
    assert "coinfello_set_daily_limit" in str(excinfo.value)
    assert "Nothing was sent" in str(excinfo.value)
    assert read_only.mock_state["refused_read_only"] == []  # never reached the server


def test_server_read_only_refusal_becomes_the_same_clear_error(read_only):
    # access not known locally yet: the server's refusal is translated.
    with pytest.raises(core.NeedsTradingAccess):
        core.embed_token()
    assert read_only.mock_state["refused_read_only"] == ["create_embed_token"]
    assert core.load_state()["access"] == "read_only"


# -- the upgrade ---------------------------------------------------------------------

def test_signed_in_message_names_the_account(read_only):
    message = core._signed_in_message(
        {"signed_in_as": "jacob@example.com", "access": "read_only"}
    )
    assert "jacob@example.com" in message
    assert "read-only" in message
    assert "sign out" in message


def test_older_server_sessions_are_not_marked_read_only(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp")
    mock_mcp.mock_state["actions"] = True
    core.save_state({"signed_in": True, "test_grant": "tok-old", "wallet_address": "0xWALLET"})
    status = core.status()
    assert status["access"] == "unknown" and status["can_trade"] is True
    assert core.portfolio()["can_send"] is True
