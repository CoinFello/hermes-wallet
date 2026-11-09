"""Sign-out must be instant for the user and still revoke server-side."""

from __future__ import annotations

import time

import pytest

import coinfello_core as core


@pytest.fixture
def signed_in(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp/mcp")
    core.save_state({"session_token": "tok-live", "wallet_address": "0xWALLET"})
    return mock_mcp


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_pane_sign_out_returns_before_a_slow_server_answers(signed_in):
    signed_in.mock_state["sign_out_delay"] = 2.0
    started = time.monotonic()
    result = core.disconnect(wait=False)
    elapsed = time.monotonic() - started

    assert result == {"ok": True, "signed_out": True}
    assert elapsed < 0.5, f"sign-out blocked for {elapsed:.2f}s"
    assert not core.signed_in()  # the local session is gone immediately
    # ...and the server-side revocation still happens, with the right token.
    assert _wait_for(lambda: signed_in.mock_state["signed_out_tokens"] == ["Bearer tok-live"])


def test_agent_sign_out_waits_and_reports(signed_in):
    result = core.disconnect(wait=True)
    assert result == {"ok": True, "signed_out": True}
    assert signed_in.mock_state["signed_out_tokens"] == ["Bearer tok-live"]
    assert not core.signed_in()


def test_unreachable_server_is_retried_then_reported(signed_in, monkeypatch):
    monkeypatch.setattr(core, "mcp_url", lambda: "http://127.0.0.1:1/api/mcp/mcp")
    monkeypatch.setattr(core.time, "sleep", lambda _s: None)  # no real back-off in tests
    result = core.disconnect(wait=True)
    assert result["signed_out"] is True
    assert "server sign-out failed" in result["warning"]
    assert not core.signed_in()  # local sign-out never depends on the network


def test_sign_out_without_a_session_is_a_no_op(isolated_state):
    assert core.disconnect(wait=False) == {"ok": True, "signed_out": True}
