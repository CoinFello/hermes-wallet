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
    core.save_state({"session_token": "tok-old", "wallet_address": "0xWALLET",
                     "signed_in_as": "jacob@example.com"})
    return server


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# -- the steps, in the page's order ---------------------------------------------

def test_steps_follow_the_page_sign_in_before_code(server):
    steps = core.sign_in_steps("WDJB-MJHT", "https://app.coinfello.com/authorize")
    order = [
        next(i for i, s in enumerate(steps) if "Open https://app.coinfello.com/authorize" in s),
        next(i for i, s in enumerate(steps) if "Sign in to your CoinFello account" in s),
        next(i for i, s in enumerate(steps) if "WDJB-MJHT" in s),
        next(i for i, s in enumerate(steps) if "Read only, or trade" in s),
        next(i for i, s in enumerate(steps) if s.startswith("Approve")),
    ]
    assert order == sorted(order) == list(range(5))
    # The code appears in exactly one step, and the login step says so.
    assert sum("WDJB-MJHT" in s for s in steps) == 1
    assert "not where the code goes" in steps[1]


def test_older_servers_get_no_access_step(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp")
    mock_mcp.mock_state["browser_sign_in"] = True  # browser sign-in, no access levels
    steps = core.sign_in_steps("WDJB-MJHT", "https://x/authorize")
    assert not any("daily" in s for s in steps)
    assert len(steps) == 4


def test_connect_hands_the_agent_a_message_to_relay_verbatim(server):
    result = core.connect()
    assert result["upgrade"] is False
    message = result["user_message"]
    assert message.index("Sign in to your CoinFello account") < message.index(result["user_code"])
    assert "exactly as written" in result["next"]
    assert "in-app preview" in result["next"]


# -- read-only state ---------------------------------------------------------------

def test_status_reports_read_only_and_how_to_upgrade(read_only):
    status = core.status()
    assert status["access"] == "read_only"
    assert status["can_trade"] is False
    assert "coinfello_connect" in status["next"]
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
    assert "coinfello_connect" in str(excinfo.value)
    assert "Nothing was sent" in str(excinfo.value)
    assert read_only.mock_state["refused_read_only"] == []  # never reached the server


def test_server_read_only_refusal_becomes_the_same_clear_error(read_only):
    # access not known locally yet: the server's refusal is translated.
    with pytest.raises(core.NeedsTradingAccess):
        core.embed_token()
    assert read_only.mock_state["refused_read_only"] == ["create_embed_token"]
    assert core.load_state()["access"] == "read_only"


# -- the upgrade ---------------------------------------------------------------------

def test_upgrade_flow_keeps_reads_working_and_swaps_the_session(read_only):
    started = core.connect()
    assert started["upgrade"] is True
    assert "read-only" in started["user_message"]
    assert "Pick a daily limit" in started["user_message"]

    # Still signed in (read-only) while the upgrade is pending, and the pane
    # gets the steps to show.
    status = core.status()
    assert status["connected"] is True
    assert status["pending_upgrade"] is True
    assert status["sign_in_steps"][2].endswith(started["user_code"])

    read_only.mock_state["browser_approved"] = True
    done = core.poll_approval()
    assert done["access"] == "trade" and done["daily_limit_usd"] == 250
    assert done["can_trade"] is True
    assert "$250 a day" in done["user_message"]
    assert core.load_state()["session_token"] == "tok-trade"
    # The replaced read-only session is signed out server-side.
    assert _wait_for(lambda: "Bearer tok-old" in read_only.mock_state["signed_out_tokens"])

    status = core.status()
    assert status["access"] == "trade"
    assert status["remaining_today_usd"] == 209.5
    assert "pending_approval_id" not in status


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
    core.save_state({"session_token": "tok-old", "wallet_address": "0xWALLET"})
    status = core.status()
    assert status["access"] == "unknown" and status["can_trade"] is True
    assert core.portfolio()["can_send"] is True
