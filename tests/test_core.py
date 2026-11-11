"""Tests for the service layer against the mock MCP server."""

from __future__ import annotations

import pytest

import coinfello_core as core


@pytest.fixture
def live(mock_mcp, isolated_state, monkeypatch):
    """Core pointed at the mock server with isolated state."""
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/mcp")
    return mock_mcp


def test_status_reflects_state(live):
    offline = core.status()
    assert offline["connected"] is False

    core.save_state({"test_grant": "tok-abc123"})  # `hermes auth add` ran
    online = core.status()
    assert online["connected"] is True
    assert online["wallet_address"] == "0xWALLET"
    assert "session_token" not in online  # never leaks the token


def test_read_requires_session(live):
    with pytest.raises(core.NotSignedIn):
        core.call("get_balances", {})


def test_read_with_session(live):
    core.save_state({"test_grant": "tok-abc123"})
    result = core.call("get_balances", {})
    assert core.signed_in()
    assert result["totalValueUsd"] == 2500.0


def test_disconnect_clears_state(live):
    core.save_state({"signed_in": True, "test_grant": "tok-abc123"})
    result = core.disconnect()
    assert result["ok"] is True
    assert not core.signed_in()

def test_connect_without_a_grant_gives_the_hermes_command(live):
    result = core.connect()
    assert result["status"] == "sign_in_required"
    assert result["command"] == "hermes auth add coinfello:coinfello"
    assert "hermes auth add coinfello:coinfello" in result["user_message"]
    assert "COINFELLO_OAUTH_CLIENT_ID=coinfello-hermes" in result["user_message"]


def test_connect_with_a_grant_reports_the_sign_in(live):
    core.save_state({"test_grant": "tok-abc123"})
    result = core.connect()
    assert result["status"] == "signed_in"
    assert result["wallet_address"] == "0xWALLET"


def test_a_lost_grant_flips_the_cached_flag(live):
    core.save_state({"signed_in": True})  # cached, but Hermes holds no grant
    with pytest.raises(core.NotSignedIn) as excinfo:
        core.call("get_balances", {})
    assert "hermes auth add coinfello:coinfello" in str(excinfo.value)
    assert not core.signed_in()


def test_state_never_holds_a_token(live):
    core.save_state({"test_grant": "tok-abc123"})
    core.status()
    stored = {k: v for k, v in core.load_state().items() if k != "test_grant"}
    assert "tok-abc123" not in str(stored)
