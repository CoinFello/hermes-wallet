"""The pane's Activity tab: get_activity shaped like the CoinFello activity feed.

Wording tests pin the en catalog templates of coinfello-web
``components/ActivityFeed/sentence.ts`` / ``result.ts`` (see
coinfello_activity's module docstring), so a web-side wording change shows up
here as a deliberate diff.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import coinfello_activity as a
import coinfello_core as core

ME = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"


def _leg(symbol="USDC", amount="10", usd=None, chain=8453):
    return {"symbol": symbol, "address": "0xa", "chainId": chain, "amount": amount, "amountUsd": usd}


def _tx(verb, *, attempted=False, src=None, dst=None, counterparty=None, protocol=None, more=0, status="done", wallet=None):
    return {
        "status": status, "wallet": wallet,
        "what": {"kind": "transaction", "verb": verb, "attempted": attempted, "from": src, "to": dst,
                 "counterparty": counterparty, "protocol": protocol, "moreCount": more},
    }


# -- format-utils.ts ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("amount", "expected"),
    [("0", "0.00 ETH"), ("0.0004", "<0.001 ETH"), ("1", "1.00 ETH"),
     ("0.0161", "0.0161 ETH"), ("1234.5", "1,234.50 ETH"), ("0.12345678", "0.123457 ETH"), ("junk", "0.00 ETH")],
)
def test_format_token_amount(amount, expected):
    assert a.format_token_amount(amount, "ETH") == expected


def test_format_usd_value():
    assert a.format_usd_value("0.004") == "< $0.01"
    assert a.format_usd_value("1234.5") == "$1,234.50"
    assert a.format_usd_value(None) is None


# -- sentence.ts ------------------------------------------------------------------

@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (_tx("swapped", src=_leg("USDC", "50"), dst=_leg("ETH", "0.0161"), protocol="Uniswap", more=1),
         "Swapped 50.00 USDC for 0.0161 ETH on Uniswap. (+1 more step)"),
        (_tx("swapped", attempted=True, src=_leg("USDC", "50")), "Tried to swap 50.00 USDC."),
        (_tx("bridged", src=_leg("ETH", "0.1", chain=1), dst=_leg("ETH", "0.1", chain=8453)),
         "Bridged 0.10 ETH from Ethereum Mainnet to Base."),
        (_tx("sent", src=_leg(), counterparty=OTHER), "Sent 10.00 USDC to 0x2222...2222."),
        (_tx("received", dst=_leg(), counterparty=OTHER), "Received 10.00 USDC from 0x2222...2222."),
        (_tx("moved", src=_leg(), counterparty=OTHER, wallet=ME), "Moved 10.00 USDC from this wallet to 0x2222...2222."),
        (_tx("staked", src=_leg(), protocol="Aave"), "Deposited 10.00 USDC into Aave."),
        (_tx("unstaked", dst=_leg(), protocol="Aave"), "Withdrew 10.00 USDC from Aave."),
        (_tx("lp_deposit", src=_leg("ETH", "1"), dst=_leg("USDC", "3000"), protocol="Uniswap"),
         "Added 1.00 ETH and 3,000.00 USDC to a pool on Uniswap."),
        (_tx("lp_withdraw", src=_leg("ETH", "1")), "Removed 1.00 ETH from a pool."),
        (_tx("approved", src=_leg("USDC", "unlimited"), protocol="Uniswap"), "Allowed Uniswap to spend any amount of USDC."),
        (_tx("approved", src=_leg("USDC", "5"), counterparty=OTHER), "Allowed 0x2222...2222 to spend up to 5.00 USDC."),
        (_tx("approved", src=_leg("USDC", "5")), "Allowed an app to spend up to 5.00 USDC."),
        (_tx("executed", attempted=True), "Tried to call a contract."),
        (_tx("sent", src=_leg(symbol=OTHER)), "Sent 10.00 Unknown."),  # an address in place of a symbol
    ],
)
def test_sentence_matches_web_catalog(entry, expected):
    assert a.sentence_text(entry, ME) == expected


def test_run_sentences_use_headline_or_fallback():
    run = lambda headline, status: {"status": status, "what": {"kind": "run", "headline": headline}}  # noqa: E731
    assert a.sentence_text(run("Bought the dip on ETH", "done")) == "Bought the dip on ETH"
    assert a.sentence_text(run(None, "done")) == "Ran the automation"
    assert a.sentence_text(run(None, "failed")) == "Did not finish"
    assert a.sentence_text(run(None, "running")) == "In progress"


# -- result.ts ---------------------------------------------------------------------

def test_result_is_signed_only_when_settled_in_or_out():
    leg = _leg(usd="250")
    assert a.result_of({"kind": "amount", "flow": "in", "leg": leg}, "done") == {"text": "+$250.00", "tone": "positive"}
    assert a.result_of({"kind": "amount", "flow": "out", "leg": leg}, "done") == {"text": "-$250.00", "tone": "default"}
    assert a.result_of({"kind": "amount", "flow": "exchange", "leg": leg}, "done")["text"] == "$250.00"
    assert a.result_of({"kind": "amount", "flow": "out", "leg": leg}, "pending")["text"] == "$250.00"
    # No USD price: the token amount instead.
    assert a.result_of({"kind": "amount", "flow": "in", "leg": _leg()}, "done")["text"] == "+10.00 USDC"


def test_result_failures_and_plain_kinds():
    assert a.result_of({"kind": "failed", "reason": {"code": "reverted"}}, "failed") == {"text": "reverted", "tone": "error"}
    assert a.result_of({"kind": "failed", "reason": {"code": "did_not_finish"}}, "failed")["text"] == "did not finish"
    assert a.result_of({"kind": "no_move"}, "done")["text"] == "no move"
    assert a.result_of({"kind": "acted"}, "done")["text"] == "done"
    assert a.result_of(None, "done")["text"] == ""


# -- rows and pages ------------------------------------------------------------------

def test_fill_rows_show_direction_price_and_pnl():
    row = a.fill_row({"at": "t", "coin": "ETH", "direction": "Close Long", "price": "3120.4", "size": "0.5",
                      "closedPnl": "-4", "orderId": 1, "txHash": "0x" + "ef" * 32})
    assert row["sentence"] == "Close Long 0.5 ETH at $3,120.40."
    assert row["result"] == {"text": "-$4.00", "tone": "negative"}
    assert row["source"] == "Hyperliquid"
    opened = a.fill_row({"coin": "BTC", "direction": "Open Short", "price": "100000", "size": "0.01", "closedPnl": "0"})
    assert opened["result"] == {"text": "$1,000.00", "tone": "default"}
    assert opened["tx_url"] is None


def test_shape_keeps_section_errors_separate():
    page = a.shape_activity({"transactions": {"error": "Could not read transactions"},
                             "hyperliquidFills": {"data": {"fills": []}}})
    assert page["rows"] == [] and page["error"] == "Could not read transactions"
    assert page["fills_error"] is None
    assert a.shape_activity({})["rows"] == []  # unknown shape degrades, never raises


# -- core + route against the mock server -------------------------------------------

@pytest.fixture
def server(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp")
    core.save_state({"session_token": "tok-live", "wallet_address": ME})
    return mock_mcp


def test_older_servers_report_unsupported_without_calling(server):
    result = core.activity()
    assert result["ok"] is False and result["unsupported"] is True
    assert not [c for c in server.mock_state["tool_calls"] if c[0] == "get_activity"]


def test_pages_follow_the_cursor_and_fills_ride_only_on_page_one(server):
    server.mock_state["activity"] = True
    first = core.activity()
    assert [r["sentence"] for r in first["rows"]] == [
        "Swapped 50.00 USDC for 0.0161 ETH on Uniswap. (+1 more step)",
        "Received 250.00 USDC from 0x2222...2222.",
    ]
    assert first["rows"][0]["source"] == "Fello · Dip buyer"
    assert first["rows"][0]["tx_url"] == "https://blockscan.com/tx/0x" + "ab" * 32
    assert first["rows"][1]["result"] == {"text": "+$250.00", "tone": "positive"}
    assert first["next_cursor"] == "cursor-2"
    assert [f["sentence"] for f in first["fills"]] == ["Close Long 0.5 ETH at $3,120.40."]

    older = core.activity("cursor-2")
    assert older["rows"][0]["sentence"] == "Tried to send 10.00 USDC to 0x3333...3333."
    assert older["rows"][0]["status_label"] == "Failed"
    assert older["next_cursor"] is None
    assert older["fills"] == [] and older["fills_error"] is None
    calls = [args for name, args in server.mock_state["tool_calls"] if name == "get_activity"]
    assert calls == [{}, {"before": "cursor-2"}]


def test_activity_route(server, monkeypatch):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    server.mock_state["activity"] = True
    path = Path(__file__).resolve().parent.parent / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("coinfello_plugin_api_activity", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/coinfello")
    client = TestClient(app)
    assert len(client.get("/api/plugins/coinfello/activity").json()["rows"]) == 2
    older = client.get("/api/plugins/coinfello/activity", params={"before": "cursor-2"}).json()
    assert older["ok"] is True and older["next_cursor"] is None


# -- aggregators are never named; the venue underneath is --------------------------

import coinfello_venues as v

LIFI_SWAP = {**_tx("swapped", src=_leg("POL", "10.9"), dst=_leg("ETH", "0.0045"), protocol="LI.FI"),
             "chainId": 1, "txHash": "0x" + "ab" * 32}


@pytest.fixture(autouse=True)
def _venue_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "CACHE_FILE", tmp_path / "venues.json")


@pytest.mark.parametrize("label", ["LI.FI", "li.fi", "LiFi", "Jumper", "1inch", "0x", "ParaSwap", "KyberSwap"])
def test_aggregator_labels_are_recognised(label):
    assert v.is_aggregator(label)


@pytest.mark.parametrize("label", ["Uniswap", "Curve", "Aave", "Across", None, ""])
def test_venues_are_not_aggregators(label):
    assert not v.is_aggregator(label)


def test_aggregator_is_dropped_when_no_venue_is_known():
    assert a.sentence_text(LIFI_SWAP, ME) == "Swapped 10.90 POL for 0.0045 ETH."
    assert a.sentence_text(_tx("executed", protocol="LI.FI")) == "Called a contract."


def test_resolved_venues_replace_the_aggregator():
    assert a.sentence_text(LIFI_SWAP, ME, ["Uniswap"]) == "Swapped 10.90 POL for 0.0045 ETH on Uniswap."
    assert a.sentence_text(LIFI_SWAP, ME, ["Uniswap", "Curve"]).endswith("on Uniswap and Curve.")
    bridge = _tx("bridged", src=_leg("ETH", "0.1", chain=1), dst=_leg("ETH", "0.1", chain=137), protocol="LI.FI")
    assert a.sentence_text(bridge, ME) == "Bridged 0.10 ETH from Ethereum Mainnet to Polygon Mainnet."
    assert a.sentence_text(bridge, ME, ["Across"]).endswith("to Polygon Mainnet via Across.")


def test_aggregator_approvals_name_neither_the_aggregator_nor_its_address():
    entry = _tx("approved", src=_leg("POL", "10.9"), protocol="LI.FI",
                counterparty="0x1231deb6f5749ef6ce6943a275a1d3e7486f4eae")
    assert a.sentence_text(entry, ME) == "Allowed a swap contract to spend up to 10.90 POL."


def test_venue_jobs_only_ask_about_settled_routed_swaps_and_bridges():
    raw = {"transactions": {"data": {"entries": [
        LIFI_SWAP,
        {**LIFI_SWAP, "status": "failed"},
        {**_tx("swapped", protocol="Uniswap"), "chainId": 1, "txHash": "0x" + "01" * 32},
        {**_tx("bridged", protocol="LI.FI"), "chainId": 1, "txHash": "0x" + "02" * 32},
        {**_tx("approved", protocol="LI.FI"), "chainId": 1, "txHash": "0x" + "03" * 32},
    ]}}}
    assert a.venue_jobs(raw) == [
        {"kind": "swap", "chain_id": 1, "tx_hash": "0x" + "ab" * 32},
        {"kind": "bridge", "chain_id": 1, "tx_hash": "0x" + "02" * 32},
    ]


def _log(topic, address):
    return {"topics": [topic], "address": address}


def test_venues_from_logs_attributes_pools_by_factory_and_singletons_by_address():
    uni_v3_pool, unknown_pool = "0x" + "aa" * 20, "0x" + "bb" * 20
    factories = {uni_v3_pool: "0x1f98431c8ad98523631ae4a59f267346ea31f984", unknown_pool: "0x" + "cc" * 20}
    logs = [
        _log("0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef", "0x" + "dd" * 20),  # Transfer
        _log(v.V3_SWAP, uni_v3_pool),
        _log(v.V4_SWAP, "0x000000000004444c5dc75cb358380d2e3de08a90"),  # Uniswap again: listed once
        _log(v.V2_SWAP, unknown_pool),  # unknown factory: never guessed
        _log(sorted(v.CURVE_EXCHANGES)[0], "0x" + "ee" * 20),
        _log(v.BALANCER_V2_SWAP, "0xba12222222228d8ba445958a75a0704d566bf2c8"),
    ]
    assert v.venues_from_logs(1, logs, factories.get) == ["Uniswap", "Curve", "Balancer"]
    # A v4 Swap from some other contract is not Uniswap.
    assert v.venues_from_logs(1, [_log(v.V4_SWAP, "0x" + "ff" * 20)], factories.get) == []


def test_bridge_names_only_known_bridges():
    assert v.bridge_name("across") == "Across"
    assert v.bridge_name("stargateV2") == "Stargate"
    assert v.bridge_name("sushiswap") is None  # a nested router is not a bridge
    assert v.bridge_name(None) is None


def test_resolve_caches_answers_and_retries_failures(monkeypatch):
    calls = []

    def fake_swap(chain_id, tx_hash):
        calls.append(tx_hash)
        if tx_hash.endswith("02"):
            raise v.LookupFailed("rpc down")
        return ["Uniswap"]

    monkeypatch.setattr(v, "swap_venues", fake_swap)
    jobs = [{"kind": "swap", "chain_id": 1, "tx_hash": "0x01"}, {"kind": "swap", "chain_id": 1, "tx_hash": "0x02"},
            {"kind": "bridge", "chain_id": 1, "tx_hash": "0x03"}]
    status = {"0x03": {"status": "DONE", "tool": "across"}}
    first = v.resolve(jobs, status.get)
    assert first == {"1:0x01": ["Uniswap"], "1:0x03": ["Across"]}
    second = v.resolve(jobs, status.get)
    assert second == first
    assert calls == ["0x01", "0x02", "0x02"]  # 0x01 cached; the failure retried


def test_pending_bridges_are_not_cached(monkeypatch):
    job = [{"kind": "bridge", "chain_id": 1, "tx_hash": "0x04"}]
    assert v.resolve(job, lambda tx: {"status": "PENDING", "tool": "across"}) == {}
    assert v.resolve(job, lambda tx: {"status": "DONE", "tool": "across"}) == {"1:0x04": ["Across"]}


def test_core_activity_never_names_the_aggregator(server, monkeypatch):
    import copy
    import json as _json

    import conftest

    page = copy.deepcopy(conftest.ACTIVITY_PAGE_1)
    swap = page["transactions"]["data"]["entries"][0]
    swap["what"]["protocol"] = "LI.FI"
    monkeypatch.setattr(conftest, "ACTIVITY_PAGE_1", page)
    monkeypatch.setattr(v, "swap_venues", lambda chain_id, tx_hash: ["Uniswap"])
    server.mock_state["activity"] = True
    result = core.activity()
    assert result["rows"][0]["sentence"] == "Swapped 50.00 USDC for 0.0161 ETH on Uniswap. (+1 more step)"
    assert "li.fi" not in _json.dumps(result).lower()

    monkeypatch.setattr(v, "CACHE_FILE", v.CACHE_FILE.with_name("other.json"))
    monkeypatch.setattr(v, "swap_venues", lambda chain_id, tx_hash: (_ for _ in ()).throw(v.LookupFailed("down")))
    assert core.activity()["rows"][0]["sentence"] == "Swapped 50.00 USDC for 0.0161 ETH. (+1 more step)"


def test_rows_carry_their_verb_for_the_icon():
    assert a.transaction_row(LIFI_SWAP)["verb"] == "swapped"
    assert a.transaction_row(_tx("approved"))["verb"] == "approved"
    assert a.transaction_row({"status": "done", "what": {"kind": "run", "headline": None}})["verb"] == "run"
    assert a.transaction_row(_tx("teleported"))["verb"] is None
    assert a.fill_row({"coin": "ETH"})["verb"] == "fill"
