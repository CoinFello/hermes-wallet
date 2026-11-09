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


def test_connect_sends_code(live):
    result = core.connect("user@example.com")
    assert result["ok"] is True
    assert [(name, args) for name, args in live.mock_state["tool_calls"]] == [
        ("privy_send_login_code", {"email": "user@example.com"})
    ]


def test_connect_validates_email(live):
    with pytest.raises(ValueError):
        core.connect("not-an-email")


def test_verify_signs_in_and_stores_token(live):
    core.connect("user@example.com")
    result = core.verify("user@example.com", "111111")
    assert result["status"] == "signed_in"
    assert result["wallet_address"] == "0xWALLET"
    state = core.load_state()
    assert state["session_token"] == "tok-abc123"
    assert state["email"] == "user@example.com"


def test_verify_bad_code_surfaces_server_message(live):
    core.connect("user@example.com")
    with pytest.raises(core.ToolError) as excinfo:
        core.verify("user@example.com", "999999")
    assert "wrong code" in str(excinfo.value)
    assert not core.signed_in()


def test_verify_code_format_validated(live):
    with pytest.raises(ValueError):
        core.verify("user@example.com", "12")


def test_approval_flow(live):
    core.connect("approval@example.com")
    result = core.verify("approval@example.com", "111111")
    assert result["status"] == "approval_required"
    assert result["approval_url"].endswith("/authorize")
    assert not core.signed_in()

    pending = core.poll_approval(result["approval_id"])
    assert pending["status"] == "pending"

    done = core.poll_approval("done-approval")
    assert done["status"] == "signed_in"
    assert core.signed_in()


def test_status_reflects_state(live):
    offline = core.status()
    assert offline["connected"] is False

    core.connect("user@example.com")
    core.verify("user@example.com", "111111")
    online = core.status()
    assert online["connected"] is True
    assert online["wallet_address"] == "0xWALLET"
    assert "session_token" not in online  # never leaks the token


def test_read_requires_session(live):
    with pytest.raises(core.NotSignedIn):
        core.call("get_balances", {})


def test_read_with_session(live):
    core.connect("user@example.com")
    core.verify("user@example.com", "111111")
    result = core.call("get_balances", {})
    assert result["totalValueUsd"] == 2500.0


def test_disconnect_clears_state(live):
    core.connect("user@example.com")
    core.verify("user@example.com", "111111")
    result = core.disconnect()
    assert result["ok"] is True
    assert not core.signed_in()