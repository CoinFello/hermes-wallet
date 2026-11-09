"""Tests for the credential state store (fallback file path)."""

from __future__ import annotations

import coinfello_state


def test_save_and_load_roundtrip(isolated_state):
    state = coinfello_state.save_state({"session_token": "tok", "email": "a@b.c"})
    assert state["session_token"] == "tok"
    assert coinfello_state.load_state()["email"] == "a@b.c"
    assert isolated_state.exists()


def test_clear_state(isolated_state):
    coinfello_state.save_state({"session_token": "tok"})
    coinfello_state.clear_state()
    assert not coinfello_state.signed_in()


def test_signed_in(isolated_state):
    assert not coinfello_state.signed_in()
    coinfello_state.save_state({"session_token": "tok"})
    assert coinfello_state.signed_in()


def test_mcp_url_env_override(monkeypatch):
    monkeypatch.setenv("COINFELLO_MCP_URL", "https://preview.example.com/api/mcp/mcp/")
    assert coinfello_state.mcp_url() == "https://preview.example.com/api/mcp/mcp"
    monkeypatch.delenv("COINFELLO_MCP_URL")
    assert coinfello_state.mcp_url() == coinfello_state.DEFAULT_MCP_URL