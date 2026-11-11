"""Send (prepare -> confirm -> execute) and the swap embed token, from the pane.

These actions move funds, so the contract under test is: nothing executes
without an explicit execute call carrying a prepared intent; a used intent
cannot run twice; a moved price is reported, not retried; the 30-day session
token never leaves the backend; and the agent reaches execution only through
the approval-gated coinfello_execute (see test_agent_trades).
"""

from __future__ import annotations

import pytest

import coinfello_core as core


@pytest.fixture
def server(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp/mcp")
    core.save_state({"signed_in": True, "test_grant": "tok-live", "wallet_address": "0xWALLET"})
    mock_mcp.mock_state["actions"] = True
    return mock_mcp


def _calls(server):
    return [name for name, _ in server.mock_state["tool_calls"]]


def test_prepare_executes_nothing(server):
    prepared = core.prepare_send(8453, "0xUSDC", "25.5", "0x1111111111111111111111111111111111111111")
    assert prepared["intent_id"] == "33333333-3333-3333-3333-333333333333"
    assert prepared["summary"]["chainName"] == "Base"
    assert _calls(server) == ["prepare_send"]
    assert "execute_intent" not in _calls(server)


def test_server_validation_errors_reach_the_user(server):
    with pytest.raises(core.ToolError, match="recipient must be a 0x address"):
        core.prepare_send(8453, "0xUSDC", "1", "bob")


def test_execute_returns_hash_and_explorer_link(server):
    result = core.execute_intent("33333333-3333-3333-3333-333333333333")
    assert result["ok"] is True
    assert result["transaction_hash"] == "0xabc123"
    assert result["explorer_url"] == "https://blockscan.com/tx/0xabc123"


def test_an_intent_cannot_run_twice(server):
    intent = "33333333-3333-3333-3333-333333333333"
    assert core.execute_intent(intent)["ok"] is True
    replay = core.execute_intent(intent)
    assert replay["ok"] is False
    assert "already used" in replay["error"]


def test_a_moved_price_is_reported_not_retried(server):
    server.mock_state["price_moved"] = True
    result = core.execute_intent("44444444-4444-4444-4444-444444444444")
    assert result["ok"] is False
    assert result["price_moved"] is True
    assert result["outcome_unknown"] is False  # refused before any broadcast
    assert result["error"] == "The price moved since this swap was approved."
    assert _calls(server).count("execute_intent") == 1


def test_embed_token_is_short_lived_and_not_the_session_token(server):
    minted = core.embed_token()
    assert minted["token"] == "cfemb_test"
    assert minted["token"] != "tok-live"
    assert "tok-live" not in repr(minted)
    assert minted["embed_url"].endswith("/embed/swap")


def test_buttons_follow_server_capabilities(server, mock_mcp):
    assert core.portfolio()["can_send"] is True
    assert core.portfolio()["can_swap"] is True


def test_older_servers_disable_send_and_swap(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp/mcp")
    core.save_state({"signed_in": True, "test_grant": "tok-live", "wallet_address": "0xWALLET"})
    model = core.portfolio()
    assert model["can_send"] is False and model["can_swap"] is False
    with pytest.raises(RuntimeError, match="needs a CoinFello server update"):
        core.prepare_send(8453, "0xUSDC", "1", "0x1111111111111111111111111111111111111111")
    with pytest.raises(RuntimeError, match="needs a CoinFello server update"):
        core.embed_token()


def test_token_rows_carry_what_the_send_form_needs(server):
    rows = [t for n in core.portfolio()["networks"] for t in n["tokens"]]
    assert all({"address", "chain_id", "balance"} <= set(row) for row in rows)


def test_the_embed_token_and_raw_execute_are_never_agent_tools():
    # plugin.yaml's provides_tools is what `hermes plugins validate` checks
    # against the live register() call, so it is the agent tool surface. The
    # agent may prepare trades and run them only through coinfello_execute,
    # which the pre_tool_call hook escalates to a human (test_agent_trades).
    from pathlib import Path

    manifest = (Path(__file__).resolve().parent.parent / "plugin.yaml").read_text()
    provided = [
        line.strip()[2:]
        for line in manifest.splitlines()
        if line.strip().startswith("- coinfello_")
    ]
    assert provided, "expected provides_tools entries"
    for name in provided:
        for forbidden in ("intent", "embed"):
            assert forbidden not in name, f"{name} exposes {forbidden} to the agent"


def test_broadcast_but_unconfirmed_is_not_reported_as_not_sent(server):
    # coinfello-web: a swap broadcast whose receipt wait failed is
    # outcomeUnknown, with the hash. The pane must show a way to check it,
    # never "not sent" (which invites a second, duplicate transaction).
    server.mock_state["outcome_unknown"] = True
    result = core.execute_intent("55555555-5555-5555-5555-555555555555")
    assert result["ok"] is False
    assert result["outcome_unknown"] is True
    assert result["transaction_hash"] == "0xbroadcast"
    assert result["explorer_url"] == "https://blockscan.com/tx/0xbroadcast"
