"""The Earn view: CoinFello's real Earn UI (/embed/earn) in the desktop pane.

The contract under test:
  - an Earn token is minted with ``scope: "earn"``, and ``scope`` is only
    ever sent to a server whose create_embed_token declares it;
  - a server without that ``scope`` (production before the Earn embed) gets
    no Earn entry, and earn_deposit falls back to the yield card;
  - a read-only session still asks the server (it may allow browsing), and a
    refusal reaches the pane in its own words;
  - the preselect the frame URL carries is validated and percent-encoded;
  - earn_deposit on Hermes desktop opens the pane's Earn view (no typed yield
    id, no CoinFello call); every other surface keeps the card's text.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import coinfello_cards as cards
import coinfello_core as core
import coinfello_earn as earn

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.fixture
def server(mock_mcp, isolated_state, monkeypatch, tmp_path):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp")
    core.save_state({"session_token": "tok-live", "wallet_address": "0xWALLET"})
    mock_mcp.mock_state.update(cards=True, actions=True, embed_scopes=("swap", "earn"))
    cards.reset_for_tests()
    monkeypatch.setattr(cards, "cards_dir", lambda: tmp_path / "cards")
    monkeypatch.setattr(cards, "_announce", lambda card_id: True)
    monkeypatch.setattr(cards, "_surface_reader", None)
    monkeypatch.setattr(earn, "store_path", lambda: tmp_path / "coinfello" / "earn-request.json")
    announced: list[str] = []
    monkeypatch.setattr(earn, "_announce", lambda request_id: announced.append(request_id) or True)
    mock_mcp.announced = announced
    return mock_mcp


def _calls(server):
    return server.mock_state["tool_calls"]


def _older_server(server):
    server.mock_state["embed_scopes"] = None
    core._capabilities.update(url=None, tools=frozenset(), at=0.0)


# -- minting ---------------------------------------------------------------------------

def test_an_earn_token_is_minted_for_the_earn_scope(server):
    minted = core.embed_token("earn")
    assert minted["token"] == "cfemb_earn" and minted["token"] != "tok-live"
    assert minted["embed_url"] == "https://app.coinfello.test/embed/earn"
    assert _calls(server)[-1] == ("create_embed_token", {"scope": "earn"})


def test_swap_names_its_scope_where_the_server_declares_it(server):
    assert core.embed_token()["embed_url"].endswith("/embed/swap")
    assert _calls(server)[-1] == ("create_embed_token", {"scope": "swap"})


def test_swap_sends_no_undeclared_scope_to_an_older_server(server):
    _older_server(server)
    assert core.embed_token()["token"] == "cfemb_test"
    assert _calls(server)[-1] == ("create_embed_token", {})


def test_an_unknown_scope_is_refused_before_any_call(server):
    with pytest.raises(ValueError, match="unknown embed scope"):
        core.embed_token("bridge")
    assert _calls(server) == []


# -- feature detection -------------------------------------------------------------------

@pytest.mark.parametrize("scopes, expected", [
    (("swap", "earn"), True),
    ((), True),            # `scope` with no enum: the server validates it
    (("swap",), False),    # a scope that cannot be earn
    (None, False),         # no `scope` at all: production before the Earn embed
])
def test_earn_is_offered_only_when_the_server_mints_it(server, scopes, expected):
    server.mock_state["embed_scopes"] = scopes
    assert core.embeds_earn() is expected
    assert core.portfolio()["earn_supported"] is expected
    assert core.status()["earn_supported"] is expected


def test_an_older_server_refuses_earn_without_calling_it(server):
    _older_server(server)
    with pytest.raises(RuntimeError, match="Earn in Hermes needs a CoinFello server update"):
        core.embed_token("earn")
    assert "create_embed_token" not in [name for name, _ in _calls(server)]


def test_a_server_without_embeds_offers_no_earn(server):
    server.mock_state["actions"] = False
    assert core.embeds_earn() is False
    with pytest.raises(RuntimeError, match="Earn in Hermes needs a CoinFello server update"):
        core.embed_token("earn")


def test_the_portfolio_links_earn_on_the_app(server):
    assert core.portfolio()["earn_url"].endswith("/earn")


# -- read-only sessions -----------------------------------------------------------------

@pytest.fixture
def read_only(server):
    server.mock_state["access_mode"] = True
    core.save_state({"session_token": "tok-old", "access": "read_only"})
    return server


def test_read_only_earn_still_asks_the_server(read_only):
    # Swap is refused locally once read-only is known; Earn is the server's call.
    with pytest.raises(core.NeedsTradingAccess):
        core.embed_token("swap")
    assert read_only.mock_state["refused_read_only"] == []
    with pytest.raises(core.NeedsTradingAccess):
        core.embed_token("earn")
    assert read_only.mock_state["refused_read_only"] == ["create_embed_token"]


def test_read_only_earn_opens_when_the_server_allows_browsing(read_only):
    read_only.mock_state["earn_read_only_mint"] = True
    assert core.embed_token("earn")["token"] == "cfemb_earn"
    assert core.portfolio()["earn_supported"] is True


# -- the preselect --------------------------------------------------------------------------

def test_an_opportunity_wins_over_a_token_filter():
    assert earn.preselect({"opportunity": " base-usdc-aave ", "token": "USDC", "chain_id": 8453}) == {
        "opportunity": "base-usdc-aave"}
    assert earn.preselect({"yield_id": "y-1"}) == {"opportunity": "y-1"}
    assert earn.preselect({"yieldId": "y-2"}) == {"opportunity": "y-2"}


def test_a_token_and_chain_filter_the_list():
    assert earn.preselect({"token": "USDC", "chain_id": "8453"}) == {"token": "USDC", "chain_id": 8453}
    # The yield card's own spelling, from a model that just showed it.
    assert earn.preselect({"token": "USDC", "chain_ids": [8453]}) == {"token": "USDC", "chain_id": 8453}
    assert earn.preselect({"token": "USDC", "chain_ids": [8453, 1]}) == {"token": "USDC"}
    assert earn.preselect({"symbol": "ETH"}) == {"token": "ETH"}
    assert earn.preselect({}) == {} and earn.preselect(None) == {}
    assert earn.preselect({"opportunity": "  ", "token": ""}) == {}


@pytest.mark.parametrize("arguments", [
    {"chain_id": "base"}, {"chain_id": -1}, {"chain_id": True},
    {"token": "US\nDC"}, {"opportunity": "x" * 201}, {"token": "T" * 33},
])
def test_a_preselect_that_cannot_be_meant_is_refused(arguments):
    with pytest.raises(ValueError):
        earn.preselect(arguments)


def test_the_frame_query_escapes_every_value():
    assert earn.frame_query({"opportunity": "a&b=c#d e/f?g"}) == "opportunity=a%26b%3Dc%23d%20e%2Ff%3Fg"
    assert earn.frame_query({"token": "USD₮0", "chain_id": 8453}) == "token=USD%E2%82%AE0&chain_id=8453"
    assert earn.frame_query({"token": "theme=light&x"}) == "token=theme%3Dlight%26x"
    # One or the other, as the embed expects; nothing at all for no preselect.
    assert earn.frame_query({"opportunity": "y-1", "token": "USDC"}) == "opportunity=y-1"
    assert earn.frame_query({}) == ""


# -- coinfello_show_card(card="earn_deposit") -----------------------------------------------

def _show(arguments=None, surface="desktop"):
    return cards.show_card("earn_deposit", arguments or {}, session_id="sess-7", surface=surface)


def test_desktop_opens_the_earn_view_and_calls_nothing(server):
    out = _show({"token": "USDC", "chain_id": 8453})
    assert out["shown"] == "coinfello_pane" and out["view"] == "earn"
    assert out["preselect"] == {"token": "USDC", "chain_id": 8453}
    assert "Earn view is open" in out["note"] and "USDC on chain 8453" in out["note"]
    # No typed-id card, and nothing prepared: the human deposits in the view.
    assert [name for name, _ in _calls(server) if name.startswith(("show_", "prepare_"))] == []
    assert server.announced == [out["request_id"]]
    pending = earn.pending_request()
    assert pending["id"] == out["request_id"]
    assert pending["query"] == "token=USDC&chain_id=8453"
    assert "session_id" not in pending
    assert cards.list_cards() == []  # not a card: the pane opens a view


def test_desktop_passes_an_opportunity_through(server):
    out = _show({"yield_id": "base usdc&aave"})
    assert out["preselect"] == {"opportunity": "base usdc&aave"}
    assert earn.pending_request()["query"] == "opportunity=base%20usdc%26aave"


def test_the_request_opens_once_and_goes_stale(server, monkeypatch):
    first = _show()["request_id"]
    second = _show({"token": "ETH"})["request_id"]
    assert earn.pending_request()["id"] == second  # the newest wins
    earn.consume_request(first)
    assert earn.pending_request()["id"] == second  # only its own id clears it
    earn.consume_request(second)
    assert earn.pending_request() is None
    _show()
    later = time.time() + earn.REQUEST_TTL_SECONDS + 1
    monkeypatch.setattr(earn.time, "time", lambda: later)
    assert earn.pending_request() is None


def test_desktop_needs_a_session_first(server):
    core.clear_state()
    with pytest.raises(core.NotSignedIn):
        _show()
    assert earn.pending_request() is None


@pytest.mark.parametrize("surface", ["telegram", "cli", ""])
def test_other_surfaces_keep_the_cards_text(server, surface):
    out = _show({"yield_id": "y-1"}, surface=surface)
    assert out["shown"] is False and out["card"] == "earn_deposit"
    assert out["text"] == "Deposit into a yield: enter its id."
    assert _calls(server)[-1] == ("show_earn_deposit_card", {"yield_id": "y-1"})
    assert earn.pending_request() is None


def test_an_older_server_shows_the_yield_card_instead(server):
    _older_server(server)
    out = _show({"token": "USDC", "chain_id": 8453})
    assert out["shown"] == "coinfello_pane" and out["card"] == "yield" and out["earn_view"] is False
    assert "no Earn view for Hermes yet" in out["note"] and out["note"].startswith(cards.PANE_NOTE)
    assert _calls(server)[-1] == ("show_yield_card", {"token": "USDC", "chain_ids": [8453]})
    assert earn.pending_request() is None


def test_an_older_server_whose_yield_card_has_deposit_says_so(server):
    _older_server(server)
    server.mock_state["earn_flow"] = True
    out = _show({"token": "USDC", "chain_id": 8453})
    assert out["card"] == "yield"
    assert "Deposit button on a row opens the deposit" in out["note"]
    assert "cannot be made from Hermes" not in out["note"]


def test_an_older_server_without_a_token_keeps_the_deposit_card(server):
    # The yield card needs a token; a bare yield id is what the deposit card takes.
    _older_server(server)
    out = _show({"yield_id": "y-1"})
    assert out["card"] == "earn_deposit" and out["shown"] == "coinfello_pane"
    assert _calls(server)[-1] == ("show_earn_deposit_card", {"yield_id": "y-1"})


def test_the_yield_card_is_still_the_mcp_card_on_desktop(server):
    out = cards.show_card("yield", {"token": "USDC"}, surface="desktop")
    assert out["card"] == "yield" and "card_id" in out
    assert earn.pending_request() is None


def test_the_show_card_tool_offers_earn_deposit_as_the_way_to_deposit():
    source = (ROOT / "coinfello_tools.py").read_text()
    assert "earn_deposit: on desktop it opens CoinFello's" in source
    assert "earn_deposit" in cards.card_names()


# -- the pane's HTTP surface -----------------------------------------------------------------

@pytest.fixture
def api(server):
    import importlib.util
    import sys

    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    api_file = ROOT / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("coinfello_plugin_api_earn", api_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/coinfello")
    return TestClient(app)


BASE = "/api/plugins/coinfello"


def test_the_pane_mints_by_scope_with_swap_the_default(api, server):
    assert api.post(f"{BASE}/embed-token").json()["token"] == "cfemb_test"
    assert api.post(f"{BASE}/embed-token", json={}).json()["token"] == "cfemb_test"
    earned = api.post(f"{BASE}/embed-token", json={"scope": "earn"}).json()
    assert earned["ok"] is True and earned["token"] == "cfemb_earn"
    assert [args for name, args in _calls(server) if name == "create_embed_token"] == [
        {"scope": "swap"}, {"scope": "swap"}, {"scope": "earn"}]
    # An unknown scope is refused at the route (the body's scope is a Literal).
    assert api.post(f"{BASE}/embed-token", json={"scope": "bridge"}).status_code == 422


def test_the_pane_reads_a_read_only_refusal_in_plain_words(api, read_only):
    refused = api.post(f"{BASE}/embed-token", json={"scope": "earn"}).json()
    assert refused["ok"] is False and refused["needs_trading_access"] is True
    assert refused["error"].startswith("This session is read-only")
    assert "start_browser_sign_in" not in refused["error"]


def test_the_pane_on_an_older_server_is_told_earn_needs_an_update(api, server):
    _older_server(server)
    refused = api.post(f"{BASE}/embed-token", json={"scope": "earn"}).json()
    assert refused == {"ok": False, "error": core.EARN_NEEDS_UPDATE}


def test_the_pane_picks_up_and_consumes_the_models_request(api, server):
    assert api.get(f"{BASE}/earn/request").json() == {"ok": True, "request": None}
    request_id = _show({"opportunity": "y-1"})["request_id"]
    pending = api.get(f"{BASE}/earn/request").json()["request"]
    assert pending["id"] == request_id and pending["query"] == "opportunity=y-1"
    assert api.post(f"{BASE}/earn/request/{request_id}/consume").json() == {"ok": True}
    assert api.get(f"{BASE}/earn/request").json()["request"] is None


# -- the pane's embed host, under node ----------------------------------------------------------

@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_embed_host_suite_passes():
    run = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "embed_host.test.mjs")],
        capture_output=True, text=True, timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "fail 0" in run.stdout


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_pane_builds_the_frame_url_the_backend_escaped():
    # The pane appends coinfello_earn.frame_query verbatim after the theme.
    script = """
const fs = require('fs')
const source = fs.readFileSync(process.argv[1], 'utf8')
const body = source.slice(source.indexOf('/* embed-host:start */'), source.indexOf('/* embed-host:end */'))
const { embedFrameSrc } = new Function(body + '\\nreturn { embedFrameSrc }')()
console.log(JSON.stringify(embedFrameSrc({ appUrl: process.argv[2], path: '/embed/earn', theme: 'dark', query: process.argv[3] })))
"""
    query = earn.frame_query({"opportunity": "a&b=c#d e"})
    run = subprocess.run(
        [NODE, "-e", script, str(ROOT / "desktop" / "plugin.js"), "https://app.coinfello.test/", query],
        capture_output=True, text=True, timeout=60, check=True,
    )
    assert json.loads(run.stdout) == "https://app.coinfello.test/embed/earn?theme=dark&opportunity=a%26b%3Dc%23d%20e"
