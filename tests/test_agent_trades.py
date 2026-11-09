"""Agent trades: prepare -> human approval -> execute -> verify delivery.

The contract under test (an earlier incident: a model "executed" a quote
through Fello, got a different bridge and token, then ran repair trades
nobody approved):
  - prepare executes nothing and caches the SERVER's summary;
  - coinfello_execute and coinfello_chat are escalated to the human-approval
    gate, the prompt showing the server's summary (never model text), with a
    per-intent / per-message rule key so no [a]lways answer covers another;
  - an intent this process did not prepare (or that expired) is refused
    outright, and each runs once;
  - route_changed / price_moved say nothing was sent;
  - transfer status reports wrong_token / refunded plainly, from the server or
    straight from LI.FI on older servers.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
from pathlib import Path

import pytest

import coinfello_core as core
import coinfello_trades as trades

ROOT = Path(__file__).resolve().parent.parent
INTENT = "66666666-6666-6666-6666-666666666666"
SOURCE = "0x" + "3e" * 32


@pytest.fixture
def server(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp/mcp")
    core.save_state({"session_token": "tok-live", "wallet_address": "0x2222222222222222222222222222222222222222"})
    mock_mcp.mock_state["actions"] = True
    with trades._intents_lock:
        trades._intents.clear()
    return mock_mcp


def _calls(server):
    return [name for name, _ in server.mock_state["tool_calls"]]


def _bridge():
    return trades.prepare_swap({
        "from_chain_id": 1, "from_token": "ETH", "to_chain_id": 137,
        "to_token": "POL", "amount": "0.004186",
    })


# -- prepare ------------------------------------------------------------------

def test_prepare_executes_nothing_and_describes_the_server_summary(server):
    prepared = _bridge()
    assert prepared["intent_id"] == INTENT
    assert _calls(server) == ["prepare_swap"]
    assert prepared["description"] == (
        "Bridge 0.004186 ETH on Ethereum Mainnet to at least 113.25 POL on "
        "Polygon via layerswap (expected 113.82; gas ~$0.12, fees ~$0.06)."
    )
    assert trades.recall_intent(INTENT)["bridges"] == ["layerswap"]


def test_prepare_on_an_older_server_says_so_and_points_away_from_chat(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp/mcp")
    core.save_state({"session_token": "tok-live", "wallet_address": "0xW"})
    with pytest.raises(RuntimeError, match="cannot prepare trades yet"):
        _bridge()


def test_send_description_names_the_full_recipient(server):
    prepared = trades.prepare_send({
        "chain_id": 8453, "token": "0xUSDC", "amount": "25.5",
        "recipient": "0x1111111111111111111111111111111111111111",
    })
    assert prepared["description"] == (
        "Send 25.5 USDC (~$25.50) on Base to "
        "0x1111111111111111111111111111111111111111. Irreversible."
    )


# -- the approval hook --------------------------------------------------------

def test_execute_is_escalated_with_the_server_summary(server):
    _bridge()
    directive = trades.approval_directive("coinfello_execute", {"intent_id": INTENT})
    assert directive["action"] == "approve"
    assert "113.25 POL on Polygon via layerswap" in directive["message"]
    assert directive["message"].startswith("CoinFello, ON-CHAIN from your automation wallet")
    assert directive["rule_key"] == f"coinfello_execute:{INTENT}"


def test_an_unprepared_intent_is_blocked_before_any_prompt(server):
    directive = trades.approval_directive(
        "coinfello_execute", {"intent_id": "77777777-7777-7777-7777-777777777777"})
    assert directive["action"] == "block"
    assert "not prepared in this session" in directive["message"]
    assert "execute_intent" not in _calls(server)


def test_an_expired_intent_is_blocked(server, monkeypatch):
    _bridge()
    later = trades.time.monotonic() + 3600
    monkeypatch.setattr(trades.time, "monotonic", lambda: later)
    assert trades.approval_directive("coinfello_execute", {"intent_id": INTENT})["action"] == "block"


def test_every_fello_message_is_escalated_on_its_own_key():
    first = trades.approval_directive("coinfello_chat", {"message": "Stake 1 ETH on Lido"})
    second = trades.approval_directive("coinfello_chat", {"message": "Stake 2 ETH on Lido"})
    assert first["action"] == "approve" and "Stake 1 ETH on Lido" in first["message"]
    assert first["rule_key"] != second["rule_key"]


def test_reads_are_not_gated():
    for name in ("coinfello_balances", "coinfello_quote", "coinfello_prepare_swap",
                 "coinfello_transfer_status", "terminal"):
        assert trades.approval_directive(name, {}) is None


# -- execute ------------------------------------------------------------------

def test_execute_runs_once_and_points_a_bridge_at_transfer_status(server):
    _bridge()
    result = trades.execute(INTENT)
    assert result["ok"] is True
    assert "coinfello_transfer_status" in result["next"]
    assert "via layerswap" in result["summary"]
    # Forgotten after one run: the hook now blocks a replay.
    assert trades.approval_directive("coinfello_execute", {"intent_id": INTENT})["action"] == "block"
    with pytest.raises(ValueError, match="prepare it again"):
        trades.execute(INTENT)
    assert _calls(server).count("execute_intent") == 1


def test_a_changed_route_says_nothing_was_sent(server):
    server.mock_state["route_changed"] = True
    _bridge()
    result = trades.execute(INTENT)
    assert result["ok"] is False
    assert result["route_changed"] is True
    assert result["outcome_unknown"] is False
    assert "Nothing was sent" in result["next"]


# -- delivery status ----------------------------------------------------------

def test_transfer_status_uses_the_server_when_it_can(server):
    server.mock_state["transfer_status"] = True
    status = trades.transfer_status(SOURCE)
    assert status["outcome"] == "wrong_token"
    assert ("get_transfer_status", {"tx_hash": SOURCE}) in server.mock_state["tool_calls"]


def _lifi(monkeypatch, payload):
    seen = []

    def fake_open(request, timeout=0):
        seen.append(request.full_url)
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(trades, "_open", fake_open)
    return seen


ACROSS_PARTIAL = {
    "status": "DONE", "substatus": "PARTIAL", "tool": "across",
    "fromAddress": "0x2222222222222222222222222222222222222222",
    "lifiExplorerLink": "https://scan.li.fi/tx/0xa633",
    "sending": {"txHash": SOURCE, "chainId": 1, "amount": "4186000000000000",
                "token": {"symbol": "ETH", "decimals": 18, "address": "0x" + "0" * 40}},
    "receiving": {"txHash": "0x90d3", "chainId": 137, "amount": "4149590496376045",
                  "token": {"symbol": "WETH", "decimals": 18,
                            "address": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"}},
    "quote": {"action": {"toChainId": 137, "toToken": {
        "chainId": 137, "symbol": "POL", "address": "0x" + "0" * 40}}},
}


def test_older_servers_read_lifi_directly(server, monkeypatch):
    seen = _lifi(monkeypatch, ACROSS_PARTIAL)
    status = trades.transfer_status(SOURCE)
    assert seen == [f"https://li.quest/v1/status?txHash={SOURCE}"]
    assert status["outcome"] == "wrong_token"
    assert status["delivered_requested_token"] is False
    assert status["requested"]["symbol"] == "POL"
    assert status["received"] == {
        "chain_id": 137, "symbol": "WETH",
        "address": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
        "amount": "0.004149590496376045", "tx_hash": "0x90d3",
    }
    assert status["sending"]["amount"] == "0.004186"


def test_a_refund_is_not_reported_as_delivered(server, monkeypatch):
    _lifi(monkeypatch, {**ACROSS_PARTIAL, "substatus": "REFUNDED", "tool": "layerswap"})
    status = trades.transfer_status(SOURCE)
    assert status["outcome"] == "refunded"
    assert status["delivered_requested_token"] is False


def test_another_wallets_transfer_is_refused(server, monkeypatch):
    _lifi(monkeypatch, {**ACROSS_PARTIAL, "fromAddress": "0x" + "b" * 40})
    with pytest.raises(ValueError, match="not sent from this CoinFello"):
        trades.transfer_status(SOURCE)


def test_a_malformed_hash_is_refused_without_a_request(server, monkeypatch):
    seen = _lifi(monkeypatch, ACROSS_PARTIAL)
    with pytest.raises(ValueError, match="32-byte transaction hash"):
        trades.transfer_status("0x1234")
    assert seen == []


# -- registration -------------------------------------------------------------

def _load_plugin(monkeypatch):
    """Import the repo as the ``coinfello`` package, like Hermes does."""
    registry = types.ModuleType("tools.registry")
    registry.tool_error = lambda message: json.dumps({"error": message})
    registry.tool_result = lambda payload: json.dumps(payload)
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.registry", registry)
    for name in [n for n in sys.modules if n == "coinfello_pkg" or n.startswith("coinfello_pkg.")]:
        monkeypatch.delitem(sys.modules, name)
    spec = importlib.util.spec_from_file_location(
        "coinfello_pkg", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "coinfello_pkg", module)
    spec.loader.exec_module(module)
    return module


class _Ctx:
    def __init__(self):
        self.tools, self.hooks = [], {}

    def register_tool(self, **kwargs):
        self.tools.append(kwargs["name"])

    def register_hook(self, name, callback):
        self.hooks[name] = callback


def test_register_wires_every_manifest_tool_and_the_approval_hook(monkeypatch):
    plugin = _load_plugin(monkeypatch)
    ctx = _Ctx()
    plugin.register(ctx)
    manifest = (ROOT / "plugin.yaml").read_text()
    provided = [line.strip()[2:] for line in manifest.splitlines()
                if line.strip().startswith("- coinfello_")]
    assert sorted(ctx.tools) == sorted(provided)
    assert "pre_tool_call" in ctx.hooks
    assert "- pre_tool_call" in manifest


def test_every_fund_moving_agent_tool_is_gated(monkeypatch):
    # The agent surface may move funds only through tools the hook escalates.
    plugin = _load_plugin(monkeypatch)
    ctx = _Ctx()
    plugin.register(ctx)
    hook = ctx.hooks["pre_tool_call"]
    assert hook(tool_name="coinfello_chat", args={"message": "send 1 ETH to bob"})["action"] == "approve"
    assert hook(tool_name="coinfello_execute", args={"intent_id": "nope"})["action"] == "block"
    # No agent tool reaches the server's execute_intent / embed token directly.
    for name in ctx.tools:
        assert "embed" not in name and "intent" not in name, name


def test_the_hook_fails_closed(monkeypatch):
    plugin = _load_plugin(monkeypatch)
    ctx = _Ctx()
    plugin.register(ctx)

    def boom(*_args, **_kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(plugin._trades, "approval_directive", boom)
    hook = ctx.hooks["pre_tool_call"]
    assert hook(tool_name="coinfello_execute", args={"intent_id": INTENT})["action"] == "block"
    assert hook(tool_name="coinfello_chat", args={"message": "hi"})["action"] == "block"
    assert hook(tool_name="coinfello_balances", args={}) is None
