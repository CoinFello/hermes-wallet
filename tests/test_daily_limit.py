"""Adjustable daily limit: lower in place, raise only with the human's approval.

The agent holds the same session token as the plugin backend, so whatever
the backend can do alone, the agent can do. The rule under test: the plugin
can LOWER the limit (or go read-only) directly, but a raise only ever yields
an approval link for the human; the session and its token are kept.
"""

from __future__ import annotations

import pytest

import coinfello_core as core


@pytest.fixture
def server(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp")
    mock_mcp.mock_state.update(
        browser_sign_in=True, actions=True, access_mode=True, limit_mode=True
    )
    return mock_mcp


@pytest.fixture
def trading(server):
    core.save_state({"session_token": "tok-trade", "wallet_address": "0xWALLET"})
    core.status()  # learns access=trade, $250
    return server


@pytest.fixture
def read_only(server):
    core.save_state({"session_token": "tok-old", "wallet_address": "0xWALLET"})
    core.status()
    return server


def _calls(server):
    return [name for name, _ in server.mock_state["tool_calls"]]


def test_lowering_applies_at_once_with_the_same_token(trading):
    result = core.change_daily_limit(100)
    assert result["status"] == "changed"
    assert result["daily_limit_usd"] == 100
    assert "No new sign-in" in result["user_message"]
    assert "start_limit_change" not in _calls(trading)
    assert core.load_state()["session_token"] == "tok-trade"
    assert core.status()["daily_limit_usd"] == 100


def test_read_only_is_always_allowed(trading):
    result = core.change_daily_limit(None)
    assert result["access"] == "read_only" and result["can_trade"] is False


def test_a_raise_only_returns_an_approval_link(trading):
    result = core.change_daily_limit(5000)
    assert result["status"] == "approval_required"
    assert result["approval_url"].endswith("/authorize/limit?change=chg-1")
    assert "set_daily_limit" not in _calls(trading)  # never attempted
    assert "no new sign-in" in result["user_message"]
    # Nothing changed yet.
    assert core.status()["daily_limit_usd"] == 250


def test_custom_amounts_any_size_are_passed_through(trading):
    core.change_daily_limit("$12,345.67")
    change = trading.mock_state["limit_changes"]["chg-1"]
    assert change["limit"] == 12345.67


def test_raise_completes_after_the_human_approves(trading):
    core.change_daily_limit(5000)
    assert core.poll_limit_change()["status"] == "pending"
    assert core.status()["pending_limit_requested"] == 5000

    trading.mock_state["limit_changes"]["chg-1"]["status"] = "approved"
    done = core.poll_limit_change()
    assert done["status"] == "approved" and done["daily_limit_usd"] == 5000
    assert "$5,000" in done["user_message"]
    assert "pending_limit_change_url" not in core.status()
    assert core.load_state()["session_token"] == "tok-trade"


def test_read_only_becomes_trading_without_a_new_sign_in(read_only):
    assert core.status()["access"] == "read_only"
    result = core.change_daily_limit(250)
    assert result["status"] == "approval_required"
    read_only.mock_state["limit_changes"]["chg-1"]["status"] = "approved"
    core.poll_limit_change()
    status = core.status()
    assert status["access"] == "trade" and status["can_trade"] is True
    assert core.load_state()["session_token"] == "tok-old"
    assert "start_browser_sign_in" not in _calls(read_only)


def test_a_stale_cached_limit_falls_back_to_approval(trading):
    # Cache says $10,000 but the server says $250: the "lower" to $1,000 is a
    # raise, the server refuses it, and the plugin asks for approval instead.
    core.save_state({"daily_limit_usd": 10000})
    result = core.change_daily_limit(1000)
    assert result["status"] == "approval_required"


def test_denied_or_expired_changes_leave_the_limit_alone(trading):
    core.change_daily_limit(5000)
    trading.mock_state["limit_changes"]["chg-1"]["status"] = "denied"
    assert core.poll_limit_change()["status"] == "denied"
    assert core.status()["daily_limit_usd"] == 250


@pytest.mark.parametrize("bad", [0, -5, "abc"])
def test_invalid_limits_are_refused_before_any_call(trading, bad):
    with pytest.raises(ValueError):
        core.change_daily_limit(bad)


def test_read_only_error_points_at_the_limit_tool(read_only):
    assert "coinfello_set_daily_limit" in core.status()["next"]
    assert "coinfello_set_daily_limit" in core.NeedsTradingAccess.MESSAGE


def test_sign_in_steps_mention_custom_and_adjusting_later(server):
    step = next(s for s in core.sign_in_steps("C0DE", "https://x/authorize") if "Read only" in s)
    assert "custom amount" in step
    assert "without signing in again" in step


def test_servers_without_adjustable_limits_say_so(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp")
    mock_mcp.mock_state.update(browser_sign_in=True, access_mode=True)
    core.save_state({"session_token": "tok-trade", "wallet_address": "0xWALLET"})
    assert core.status()["can_adjust_limit"] is False
    with pytest.raises(RuntimeError, match="sign in again"):
        core.change_daily_limit(100)
    step = next(s for s in core.sign_in_steps("C0DE", "https://x/authorize") if "Read only" in s)
    assert "custom" not in step and "without signing in again" not in step
