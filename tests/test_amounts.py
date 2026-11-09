"""Amounts the server will take, and its schema refusals in plain words.

Production's schema wants a leading digit (``^\\d+(\\.\\d+)?$``), so ".001"
came back as a raw ``MCP error -32602`` JSON dump in the pane. The contract:
  - every amount the pane or the agent sends is normalized first (".001" ->
    "0.001"), and anything that is not an amount is refused before a request,
    with a plain message;
  - the pane's copy of the rules (desktop/plugin.js normalizeAmount) agrees
    with coinfello_core.normalize_amount on one table (amount_cases.json);
  - a -32602 input-validation error reads as "<field>: <server message>",
    never JSON, wherever the server's answer surfaces; the full text is logged.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

import pytest

import coinfello_core as core
import coinfello_trades as trades
from coinfello_mcp import CoinFelloMCP, MCPError, ToolError, result_text, validation_message
from conftest import amount_refusal

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
CASES = json.loads((ROOT / "tests" / "amount_cases.json").read_text())
RECIPIENT = "0x1111111111111111111111111111111111111111"
READABLE = 'amount: A decimal number, e.g. "1.5"'


@pytest.fixture
def server(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp/mcp")
    core.save_state({"session_token": "tok-live", "wallet_address": "0xWALLET"})
    mock_mcp.mock_state["actions"] = True
    with trades._intents_lock:
        trades._intents.clear()
    return mock_mcp


def _sent(server, tool):
    return [args for name, args in server.mock_state["tool_calls"] if name == tool]


# -- the normalizer -------------------------------------------------------------

@pytest.mark.parametrize(("raw", "expected"), CASES["valid"])
def test_normalizes_plain_amounts(raw, expected):
    assert core.normalize_amount(raw) == expected


@pytest.mark.parametrize(("raw", "message"), CASES["invalid"])
def test_refuses_anything_else_in_plain_words(raw, message):
    with pytest.raises(ValueError) as caught:
        core.normalize_amount(raw)
    assert str(caught.value) == message


def test_a_missing_amount_is_refused():
    with pytest.raises(ValueError, match="Enter an amount like 0.001"):
        core.normalize_amount(None)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_pane_normalizer_agrees():
    run = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "amount.test.mjs")],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "fail 0" in run.stdout


# -- every caller normalizes before the server sees it ------------------------------

def test_pane_send_takes_a_leading_dot(server):
    prepared = core.prepare_send(8453, "0xUSDC", ".001", RECIPIENT)
    assert prepared["ok"] is True
    assert _sent(server, "prepare_send")[-1]["amount"] == "0.001"


def test_pane_send_refuses_a_non_amount_without_a_request(server):
    with pytest.raises(ValueError, match="^Enter an amount like 0.001$"):
        core.prepare_send(8453, "0xUSDC", "abc", RECIPIENT)
    assert _sent(server, "prepare_send") == []


def test_agent_send_and_swap_normalize(server):
    trades.prepare_send({"chain_id": 8453, "token": "0xUSDC", "amount": " .5 ", "recipient": RECIPIENT})
    trades.prepare_swap({"from_chain_id": 1, "from_token": "ETH", "to_chain_id": 137,
                         "to_token": "POL", "amount": "1."})
    assert _sent(server, "prepare_send")[-1]["amount"] == "0.5"
    assert _sent(server, "prepare_swap")[-1]["amount"] == "1"


def test_agent_swap_refuses_zero_without_a_request(server):
    with pytest.raises(ValueError, match="greater than 0"):
        trades.prepare_swap({"from_chain_id": 1, "from_token": "ETH", "to_token": "POL", "amount": "0.0"})
    assert _sent(server, "prepare_swap") == []


# -- -32602 in plain words ----------------------------------------------------------

def test_reads_productions_refusal():
    assert validation_message(amount_refusal("prepare_send")) == READABLE


def test_reads_every_issue_and_nested_paths():
    text = "MCP error -32602: Input validation error: Invalid arguments for tool prepare_swap: " + json.dumps([
        {"path": ["amount"], "message": "A decimal number, e.g. \"1.5\""},
        {"path": ["route", 0, "chain_id"], "message": "Expected number, received string"},
        {"path": [], "message": "Unrecognized key: \"bogus\""},
    ])
    assert validation_message(text) == (
        'amount: A decimal number, e.g. "1.5"; route.0.chain_id: Expected number, '
        'received string; Unrecognized key: "bogus"'
    )


def test_unreadable_detail_still_hides_the_dump():
    assert validation_message("MCP error -32602: Input validation error: [not json") == (
        "CoinFello did not accept those arguments.")
    assert validation_message("whatever", code=-32602) == "CoinFello did not accept those arguments."


def test_other_errors_are_left_alone():
    assert validation_message('recipient must be a 0x address; got "bob".') is None
    assert validation_message("This confirmation expired.", code=-32603) is None
    # A tool's own JSON error quoting a node's -32602 keeps its flags.
    outcome = json.dumps({"outcomeUnknown": True, "error": "RPC -32602: Input validation error: [\"x\"]"})
    assert validation_message(outcome) is None


def _client(server):
    host, port = server.server_address[:2]
    return CoinFelloMCP(f"http://{host}:{port}/mcp", session_token="tok-live")


def test_tool_refusal_raises_readable_and_logs_the_detail(server, caplog):
    caplog.set_level(logging.WARNING, logger="coinfello_mcp")
    with pytest.raises(ToolError) as caught:
        _client(server).call_tool("prepare_send", {"chain_id": 8453, "token": "ETH",
                                                   "amount": ".001", "recipient": RECIPIENT})
    assert str(caught.value) == READABLE
    assert caught.value.detail == amount_refusal("prepare_send")
    assert '"invalid_format"' in caplog.text and "prepare_send" in caplog.text


def test_card_results_carry_the_readable_text(server):
    result = _client(server).call_tool_result("prepare_swap", {"amount": ".1"})
    assert result["isError"] is True
    assert result_text(result) == READABLE


def test_json_rpc_refusal_is_readable(server):
    with pytest.raises(MCPError) as caught:
        _client(server).call_tool("strict_rpc", {})
    assert str(caught.value) == READABLE
    assert "Invalid arguments for tool strict_rpc" in caught.value.detail


def test_a_stricter_server_still_reads_plainly(server, monkeypatch):
    # Should production ever refuse what the normalizer let through, the
    # user still sees words, not the issue array.
    monkeypatch.setattr(core, "normalize_amount", lambda value: str(value))
    with pytest.raises(ToolError, match=r'^amount: A decimal number, e\.g\. "1\.5"$'):
        core.prepare_send(8453, "0xUSDC", ".001", RECIPIENT)
