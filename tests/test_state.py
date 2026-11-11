"""Tests for the credential state store (fallback file path)."""

from __future__ import annotations

import coinfello_state


def test_save_and_load_roundtrip(isolated_state):
    state = coinfello_state.save_state({"signed_in": True, "test_grant": "tok", "email": "a@b.c"})
    assert state["test_grant"] == "tok"
    assert coinfello_state.load_state()["email"] == "a@b.c"
    assert isolated_state.exists()


def test_clear_state(isolated_state):
    coinfello_state.save_state({"signed_in": True, "test_grant": "tok"})
    coinfello_state.clear_state()
    assert not coinfello_state.signed_in()


def test_signed_in(isolated_state):
    assert not coinfello_state.signed_in()
    coinfello_state.save_state({"signed_in": True, "test_grant": "tok"})
    assert coinfello_state.signed_in()


def test_mcp_url_is_fixed():
    # The OAuth bearer only goes to the hosts plugin.yaml declares, so the
    # endpoint is not configurable (and no .env is read).
    assert coinfello_state.mcp_url() == "https://app.coinfello.com/api/mcp"
