"""Browser-first sign-in, session renewal and server-capability fallback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import coinfello_core as core


@pytest.fixture
def live(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp/mcp")
    return mock_mcp


@pytest.fixture
def browser_server(live):
    live.mock_state["browser_sign_in"] = True
    return live


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


# -- browser-first sign-in ----------------------------------------------------

def test_connect_is_browser_first_on_servers_that_support_it(browser_server):
    result = core.connect()  # no email needed
    assert result["status"] == "approval_required"
    assert result["user_code"] == "WDJB-MJHT"
    assert result["approval_url"].endswith("user_code=WDJB-MJHT")
    names = [name for name, _ in browser_server.mock_state["tool_calls"]]
    assert names == ["start_browser_sign_in"]
    assert "privy_send_login_code" not in names


def test_browser_sign_in_completes_with_one_approval(browser_server):
    core.connect()
    assert core.poll_approval()["status"] == "pending"  # stored approval id
    assert not core.signed_in()

    browser_server.mock_state["browser_approved"] = True
    done = core.poll_approval()
    assert done["status"] == "signed_in"
    assert core.signed_in()
    state = core.load_state()
    assert state["pending_approval_id"] == ""
    assert state["pending_user_code"] == ""


def test_pending_browser_sign_in_survives_a_pane_reload(browser_server):
    core.connect()
    status = core.status()
    assert status["connected"] is False
    assert status["pending_user_code"] == "WDJB-MJHT"
    assert status["pending_approval_url"].endswith("WDJB-MJHT")
    assert status["sign_in_mode"] == "browser"


def test_cancel_sign_in_forgets_the_pending_approval(browser_server):
    core.connect()
    core.cancel_sign_in()
    assert core.status()["pending_user_code"] == ""


def test_old_servers_fall_back_to_email_sign_in(live):
    # A server deployed before browser sign-in: the email flow still works.
    assert core.sign_in_mode() == "email"
    with pytest.raises(ValueError):
        core.connect()  # email required there
    result = core.connect("user@example.com")
    assert result["status"] == "code_sent"
    with pytest.raises(RuntimeError):
        core.start_browser_sign_in()


def test_capabilities_are_cached(browser_server):
    core.sign_in_mode()
    core.sign_in_mode()
    core.supports("renew_session")
    assert browser_server.mock_state["list_calls"] == 1


# -- renewal -----------------------------------------------------------------

def _signed_in(expires_in: timedelta, token: str = "tok-old"):
    core.save_state(
        {"session_token": token, "wallet_address": "0xWALLET", "expires_at": _iso(expires_in)}
    )


def test_renews_when_near_expiry_and_uses_the_new_token(browser_server):
    _signed_in(timedelta(days=3))
    core.call("get_balances", {})
    names = [name for name, _ in browser_server.mock_state["tool_calls"]]
    assert names == ["renew_session", "get_balances"]
    assert browser_server.mock_state["auth_headers"][-1] == "Bearer tok-renewed"
    assert core.load_state()["session_token"] == "tok-renewed"
    assert core.load_state()["expires_at"].startswith("2099")


def test_does_not_renew_a_fresh_session(browser_server):
    _signed_in(timedelta(days=29))
    core.call("get_balances", {})
    names = [name for name, _ in browser_server.mock_state["tool_calls"]]
    assert names == ["get_balances"]


def test_no_renewal_on_servers_without_it(live):
    _signed_in(timedelta(days=3))
    core.call("get_balances", {})
    names = [name for name, _ in live.mock_state["tool_calls"]]
    assert "renew_session" not in names
    assert core.load_state()["session_token"] == "tok-old"


def test_failed_renewal_keeps_the_session_and_backs_off(browser_server, monkeypatch):
    _signed_in(timedelta(days=3))
    calls = {"n": 0}
    real = core.CoinFelloMCP.call_tool

    def flaky(self, name, arguments=None, **kw):
        if name == "renew_session":
            calls["n"] += 1
            raise core.MCPError("server hiccup")
        return real(self, name, arguments, **kw)

    monkeypatch.setattr(core.CoinFelloMCP, "call_tool", flaky)
    core.call("get_balances", {})  # renewal fails, read still goes through
    core.call("get_balances", {})  # inside the back-off window: no retry
    assert calls["n"] == 1
    assert core.load_state()["session_token"] == "tok-old"


def test_status_renews_too(browser_server):
    _signed_in(timedelta(days=1))
    core.status()
    assert core.load_state()["session_token"] == "tok-renewed"


# -- app links ---------------------------------------------------------------

def test_app_url_follows_the_mcp_deployment(monkeypatch):
    monkeypatch.setattr(core, "mcp_url", lambda: "https://app.coinfello.com/api/mcp/mcp")
    assert core.app_url("/portfolio") == "https://app.coinfello.com/portfolio"
    monkeypatch.setattr(
        core, "mcp_url", lambda: "https://coinfello-git-x.vercel.app/api/mcp/mcp"
    )
    assert core.app_url("/strategies") == "https://coinfello-git-x.vercel.app/strategies"


def test_status_shows_who_the_session_acts_as(browser_server):
    # sessions carry signed_in_as (email, else phone);
    # whoever approved the browser link is who the plugin acts as.
    core.connect()
    browser_server.mock_state["browser_approved"] = True
    core.poll_approval()
    core.save_state({"signed_in_as": "jacob@example.com"})
    assert core.status()["signed_in_as"] == "jacob@example.com"
