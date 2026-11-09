"""MCP App cards: coinfello_show_card, the card records, and the bridge relay.

The contract under test:
  - the plugin calls show_<card>_card with the stored session, sending only
    the arguments the server declares and never a session token;
  - on Hermes desktop the raw result becomes a card record (memory + disk,
    24 hours) and the pane is told; every other surface gets the full text;
  - only ui://coinfello/ HTML of the MCP Apps type is rendered, behind a
    CSP built from the resource's own _meta.ui.csp;
  - a card may relay only its own tools (refresh, named reads, prepare_*);
    execute_intent runs only for an intent this card prepared, and
    cancel_automation only for an automation it listed, each after a
    confirmation the pane draws; everything else is refused;
  - credentials never cross to the card, in either direction.
"""

from __future__ import annotations

import base64
import json
import time

import pytest

import coinfello_cards as cards
import coinfello_core as core
import coinfello_trades as trades
from coinfello_mcp import CoinFelloMCP, MCPError

INTENT = "66666666-6666-6666-6666-666666666666"


@pytest.fixture
def server(mock_mcp, isolated_state, monkeypatch, tmp_path):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp")
    core.save_state({"session_token": "tok-live", "wallet_address": "0xWALLET"})
    mock_mcp.mock_state.update(cards=True, actions=True)
    with trades._intents_lock:
        trades._intents.clear()
    cards.reset_for_tests()
    monkeypatch.setattr(cards, "cards_dir", lambda: tmp_path / "cards")
    announced: list[str] = []
    monkeypatch.setattr(cards, "_announce", lambda card_id: announced.append(card_id) or True)
    mock_mcp.announced = announced
    monkeypatch.setattr(cards, "_surface_reader", None)
    return mock_mcp


def _calls(server):
    return server.mock_state["tool_calls"]


def _show(name="portfolio", arguments=None, surface="desktop"):
    return cards.show_card(name, arguments or {}, session_id="sess-7", surface=surface)


# -- showing a card: surface-dependent replies ---------------------------------

def test_desktop_stores_the_raw_result_and_tells_the_pane(server):
    out = _show(arguments={"chain_ids": [8453], "session_token": "tok-model", "bogus": 1})
    assert out["shown"] == "coinfello_pane"
    assert out["note"] == cards.PANE_NOTE
    # The server's "Model note" assumes the card sits at the tool call; ours
    # says where it really is. The data text stays whole.
    assert out["text"].startswith("Portfolio: $2,500.00")
    assert "Model note" not in out["text"]
    assert server.announced == [out["card_id"]]
    # Only declared arguments, never the model's token: the stored one is sent.
    assert _calls(server)[-1] == ("show_portfolio_card", {"chain_ids": [8453]})
    assert server.mock_state["auth_headers"][-1] == "Bearer tok-live"
    record = cards.get_card(out["card_id"])
    assert record["session_id"] == "sess-7"
    assert record["result"]["structuredContent"]["totalValueUsd"] == 2500.0


@pytest.mark.parametrize("surface", ["telegram", "cli", ""])
def test_other_surfaces_get_the_full_text_and_no_card(server, surface):
    out = _show(surface=surface)
    assert out["shown"] is False
    assert "USDC on Base: $1,000.00" in out["text"]
    assert (surface or "unknown") in out["note"]
    assert "include its items" in out["note"]
    assert cards.list_cards() == []
    assert server.announced == []


def test_the_surface_comes_from_the_plugin_context(server):
    class Ctx:
        def session_surface(self):
            return "desktop"

    cards.bind_host(Ctx())
    assert cards.show_card("portfolio", {})["shown"] == "coinfello_pane"
    cards.bind_host(object())  # Hermes before 0.22.3: no session_surface
    assert cards.session_surface() == ""
    assert cards.show_card("portfolio", {})["shown"] is False


def test_the_sign_in_card_is_not_offered(server):
    with pytest.raises(ValueError, match="unknown card"):
        _show("sign_in")
    assert "sign_in" not in cards.card_names()


def test_a_card_declaring_an_unknown_resource_is_not_drawn(server):
    with pytest.raises(RuntimeError, match="only draws the CoinFello cards it knows"):
        _show("status")
    assert [name for name, _ in _calls(server)] == []


def test_the_flat_ui_resourceUri_key_still_counts(server):
    assert _show("yield", {"token": "USDC"})["shown"] == "coinfello_pane"
    assert _calls(server)[-1] == ("show_yield_card", {"token": "USDC"})


def test_a_missing_required_argument_names_it_and_the_call_shape(server):
    with pytest.raises(ValueError) as caught:
        _show("yield", {"chain_ids": [8453]})
    message = str(caught.value)
    assert "needs token" in message and "session_token" not in message
    assert '{"card": "yield", "arguments": {"token": "..."}}' in message
    assert _calls(server) == []  # the server never sees the incomplete call


def test_a_server_without_the_card_says_so(server):
    with pytest.raises(RuntimeError, match="no perp card yet"):
        _show("perp")


# -- secrets ------------------------------------------------------------------

def test_strip_secrets_any_depth_and_spelling():
    value = {
        "session_token": "a", "sessionToken": "b", "Embed-Token": "c", "token": "USDC",
        "nested": [{"embed_token": "d", "amount": "1", "deeper": {"Authorization": "Bearer x"}}],
        "__proto__": {"polluted": True},
    }
    assert cards.strip_secrets(value) == {"token": "USDC", "nested": [{"amount": "1", "deeper": {}}]}


def test_results_reach_the_pane_without_credentials(server):
    card_id = _show()["card_id"]
    document = cards.card_document(card_id)
    blob = json.dumps(document)
    assert "tok-leaked" not in blob and "cfemb_leaked" not in blob
    assert document["tool_result"]["structuredContent"]["nested"] == {"token": "USDC"}


def test_relayed_arguments_lose_credentials(server):
    card_id = _show("quote", {"intent_id": INTENT})["card_id"]
    cards.card_call(card_id, "prepare_swap", {
        "from_chain_id": 1, "from_token": "ETH", "to_token": "POL", "amount": "0.1",
        "session_token": "tok-card", "embed_token": "cfemb", "unknown": "x",
    })
    name, arguments = _calls(server)[-1]
    assert name == "prepare_swap"
    assert arguments == {"from_chain_id": 1, "from_token": "ETH", "to_token": "POL", "amount": "0.1"}
    assert server.mock_state["auth_headers"][-1] == "Bearer tok-live"


# -- the card resource: URI, type, CSP ------------------------------------------

def _client(server):
    host, port = server.server_address[:2]
    return CoinFelloMCP(f"http://{host}:{port}/mcp", session_token="tok-live")


@pytest.mark.parametrize("uri", [
    "ui://other/card.html", "https://app.coinfello.com/card.html",
    "ui://coinfello/../other/card.html", "", None,
])
def test_only_coinfello_card_uris_are_read(server, uri):
    with pytest.raises(MCPError, match="refusing"):
        _client(server).read_resource(uri)
    assert server.mock_state["resource_reads"] == []


def test_a_resource_of_another_type_is_refused(server):
    server.mock_state["resource_mime"] = "text/html"
    with pytest.raises(MCPError, match="not an MCP App card"):
        _client(server).read_resource("ui://coinfello/portfolio-card.html")


def test_a_resource_answered_for_another_uri_is_refused(server):
    server.mock_state["resource_uri_override"] = "ui://coinfello/other.html"
    with pytest.raises(MCPError, match="no card document"):
        _client(server).read_resource("ui://coinfello/portfolio-card.html")


def test_the_client_never_advertises_mcp_apps_and_names_itself(server):
    # Card tools then answer with their full text on every surface; the
    # plugin decides per surface what the model reads.
    client = _client(server)
    assert client._headers()["User-Agent"] == "hermes-coinfello-plugin/0.1.0"
    sent = {}
    original = client._post

    def spy(payload):
        if payload.get("method") == "initialize":
            sent.update(payload["params"])
        return original(payload)

    client._post = spy
    client.initialize()
    assert "extensions" not in sent["capabilities"]


def test_the_mime_check_ignores_case_and_spacing(server):
    server.mock_state["resource_mime"] = "Text/HTML; profile=mcp-app"
    resource = _client(server).read_resource("ui://coinfello/portfolio-card.html")
    assert resource["text"].startswith("<!DOCTYPE html>")


def test_csp_from_resource_domains():
    csp = cards.card_csp({"ui": {"csp": {
        "resourceDomains": ["https://fonts.googleapis.com", "https://fonts.gstatic.com",
                            "http://insecure.test", "https://evil.test; script-src *", 42],
        "connectDomains": ["https://api.example.com"],
        "frameDomains": ["https://frame.example.com"],
    }}})
    assert csp == (
        "default-src 'none'; script-src 'unsafe-inline'; "
        "style-src 'unsafe-inline' https://fonts.googleapis.com https://fonts.gstatic.com; "
        "font-src https://fonts.googleapis.com https://fonts.gstatic.com; img-src data:; "
        "connect-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'"
    )


def test_csp_without_domains_allows_no_remote_styles_or_fonts():
    csp = cards.card_csp(None)
    assert "style-src 'unsafe-inline';" in csp
    assert "font-src 'none'" in csp


def test_the_csp_is_the_first_thing_in_head_and_the_theme_is_set():
    html = '<!DOCTYPE html>\n<html lang="en" data-theme="light">\n<head>\n<meta charset="utf-8"></head><body></body></html>'
    out = cards.prepare_html(html, "default-src 'none'", "dark")
    assert '<html lang="en" data-theme="dark">' in out
    head = out.index("<head>") + len("<head>")
    assert out[head:].startswith('<meta http-equiv="Content-Security-Policy" content="default-src &#x27;none&#x27;">')
    assert cards.prepare_html(html, "x", "neon").count("data-theme") == 1  # unknown theme: untouched


@pytest.mark.parametrize("html", [
    "<script>alert(1)</script><head></head>",
    "<!-- <head> --><html><head></head></html>",
    "<html><body>no head</body></html>",
])
def test_a_document_that_does_not_open_with_head_is_refused(html):
    with pytest.raises(MCPError, match="does not open with <head>"):
        cards.prepare_html(html, "default-src 'none'")


def test_card_document_is_a_ready_data_url_and_html_is_cached(server):
    card_id = _show()["card_id"]
    document = cards.card_document(card_id, "dark")
    assert document["src"].startswith("data:text/html;base64,")
    html = base64.b64decode(document["src"].split(",", 1)[1]).decode()
    assert 'data-theme="dark"' in html
    assert "Content-Security-Policy" in html and "https://evil.test" not in html
    assert document["tool_input"] == {"arguments": {}}
    assert document["relay"] == ["show_portfolio_card", "whoami"]
    assert document["confirm"] == []
    assert document["prefers_border"] is True
    cards.card_document(card_id, "light")
    assert server.mock_state["resource_reads"] == ["ui://coinfello/portfolio-card.html"]


# -- the relay allowlist --------------------------------------------------------

NEVER = ["sign_out", "fello_chat", "privy_complete_approval", "privy_send_login_code",
         "start_browser_sign_in", "renew_session", "create_embed_token",
         "set_daily_limit", "start_limit_change", "get_balances", "execute_intent",
         "cancel_automation", "show_quote_card", "anything_else", ""]


@pytest.mark.parametrize("tool", NEVER)
def test_a_portfolio_card_relays_only_its_refresh_and_whoami(server, tool):
    card_id = _show()["card_id"]
    before = len(_calls(server))
    with pytest.raises(cards.CardRefused, match="not available from this card"):
        cards.card_call(card_id, tool, {})
    assert len(_calls(server)) == before


def test_allowed_relays_reach_the_server_raw(server):
    card_id = _show()["card_id"]
    refreshed = cards.card_call(card_id, "show_portfolio_card", {})
    assert refreshed["result"]["structuredContent"]["totalValueUsd"] == 2500.0
    who = cards.card_call(card_id, "whoami", {})
    assert json.loads(who["result"]["content"][0]["text"])["wallet_address"] == "0xWALLET"


def test_error_card_retry_is_rechecked_against_the_retryable_list(server):
    card_id = _show("error", {"kind": "network", "retry_tool": "get_balances"})["card_id"]
    assert cards.card_call(card_id, "get_balances", {})["ok"] is True
    for tool in ("get_positions", "fello_chat", "execute_intent"):
        with pytest.raises(cards.CardRefused):
            cards.card_call(card_id, tool, {})
    # A record claiming a non-retryable retry tool still gets nothing.
    record = cards.get_card(card_id)
    for tool in ("fello_chat", "sign_out", "execute_intent"):
        record["result"]["structuredContent"]["retryTool"] = tool
        assert cards.relay_decision(record, tool) == "deny"


def test_a_relay_flood_is_cut_off(server):
    card_id = _show()["card_id"]
    for _ in range(cards.CALLS_PER_MINUTE):
        cards.card_call(card_id, "whoami", {})
    with pytest.raises(cards.CardRefused, match="Too many requests"):
        cards.card_call(card_id, "whoami", {})


# -- confirm-gated tools ----------------------------------------------------------

def _prepare_bridge():
    return trades.prepare_swap({"from_chain_id": 1, "from_token": "ETH", "to_chain_id": 137,
                                "to_token": "POL", "amount": "0.004186"})


def test_execute_runs_once_for_an_intent_this_card_owns(server):
    _prepare_bridge()
    card_id = _show("quote", {"intent_id": INTENT})["card_id"]
    before = [name for name, _ in _calls(server)]
    preview = cards.card_call(card_id, "execute_intent", {"intent_id": INTENT})["confirm"]
    # The preview runs nothing, and shows the SERVER's summary from prepare.
    assert [name for name, _ in _calls(server)] == before
    assert preview["description"].startswith("Bridge 0.004186 ETH on Ethereum Mainnet to at least 113.25 POL")
    assert 0 < preview["expires_in_seconds"] <= 120
    out = cards.card_execute(card_id, preview["confirm_id"])
    assert out["tool"] == "execute_intent"
    assert json.loads(out["result"]["content"][0]["text"])["success"] is True
    assert _calls(server)[-1] == ("execute_intent", {"intent_id": INTENT})
    # Single use: the confirmation and the intent are both spent.
    with pytest.raises(cards.CardRefused, match="expired"):
        cards.card_execute(card_id, preview["confirm_id"])
    with pytest.raises(cards.CardRefused):
        cards.card_call(card_id, "execute_intent", {"intent_id": INTENT})
    assert trades.recall_intent(INTENT) is None
    assert cards.get_card(card_id)["intents"] == {}


def test_execute_works_from_the_pane_process(server):
    # Hermes loads plugin_api.py as its own module (and tools may run in a
    # turn-isolation child): the pane's side sees the card record on disk,
    # not the tools' in-memory intent cache.
    _prepare_bridge()
    card_id = _show("quote", {"intent_id": INTENT})["card_id"]
    with trades._intents_lock:
        trades._intents.clear()
    cards.reset_for_tests()
    preview = cards.card_call(card_id, "execute_intent", {"intent_id": INTENT})["confirm"]
    assert preview["description"].startswith("Bridge 0.004186 ETH")
    assert cards.card_execute(card_id, preview["confirm_id"])["tool"] == "execute_intent"


def test_an_expired_intent_cannot_be_confirmed(server):
    _prepare_bridge()
    card_id = _show("quote", {"intent_id": INTENT})["card_id"]
    record = cards.get_card(card_id)
    record["intents"][INTENT]["expires_at"] = time.time() - 1
    cards.save_card(record)
    with pytest.raises(cards.CardRefused, match="expired"):
        cards.card_call(card_id, "execute_intent", {"intent_id": INTENT})


def test_execute_refuses_an_intent_the_card_did_not_produce(server):
    _prepare_bridge()
    card_id = _show("quote", {"intent_id": "77777777-7777-7777-7777-777777777777"})["card_id"]
    with pytest.raises(cards.CardRefused, match="did not prepare that trade"):
        cards.card_call(card_id, "execute_intent", {"intent_id": INTENT})
    assert "execute_intent" not in [name for name, _ in _calls(server)]


def test_execute_refuses_an_intent_hermes_never_prepared(server):
    # The card names the intent, but this process holds no server summary
    # for it (prepared elsewhere, or a record restored after a restart).
    card_id = _show("quote", {"intent_id": INTENT})["card_id"]
    with pytest.raises(cards.CardRefused, match="not prepared in Hermes"):
        cards.card_call(card_id, "execute_intent", {"intent_id": INTENT})


def test_a_fresh_quote_from_the_card_becomes_the_cards_intent(server):
    card_id = _show("quote", {"intent_id": "77777777-7777-7777-7777-777777777777"})["card_id"]
    cards.card_call(card_id, "prepare_swap", {"from_chain_id": 1, "from_token": "ETH",
                                              "to_chain_id": 137, "to_token": "POL", "amount": "0.004186"})
    assert cards.get_card(card_id)["intents"][INTENT]["summary"]["bridges"] == ["layerswap"]
    preview = cards.card_call(card_id, "execute_intent", {"intent_id": INTENT})["confirm"]
    assert "layerswap" in preview["description"]


def test_a_confirmation_belongs_to_its_card(server):
    _prepare_bridge()
    first = _show("quote", {"intent_id": INTENT})["card_id"]
    second = _show("quote", {"intent_id": INTENT})["card_id"]
    preview = cards.card_call(first, "execute_intent", {"intent_id": INTENT})["confirm"]
    with pytest.raises(cards.CardRefused, match="expired"):
        cards.card_execute(second, preview["confirm_id"])
    assert "execute_intent" not in [name for name, _ in _calls(server)]


def test_an_expired_confirmation_sends_nothing(server, monkeypatch):
    _prepare_bridge()
    card_id = _show("quote", {"intent_id": INTENT})["card_id"]
    preview = cards.card_call(card_id, "execute_intent", {"intent_id": INTENT})["confirm"]
    monkeypatch.setattr(cards, "CONFIRM_TTL_SECONDS", 0)
    with cards._lock:
        cards._confirms[preview["confirm_id"]]["expires"] = time.monotonic() - 1
    with pytest.raises(cards.CardRefused, match="expired"):
        cards.card_execute(card_id, preview["confirm_id"])
    assert "execute_intent" not in [name for name, _ in _calls(server)]


def test_read_only_sessions_cannot_quote_from_a_card(server):
    core.save_state({"access": "read_only"})
    card_id = _show("quote", {"intent_id": INTENT})["card_id"]
    with pytest.raises(core.NeedsTradingAccess):
        cards.card_call(card_id, "prepare_swap", {"from_chain_id": 1, "from_token": "ETH",
                                                  "to_token": "POL", "amount": "1"})


def test_cancel_only_an_automation_the_card_listed(server):
    card_id = _show("automations")["card_id"]
    assert cards.card_call(card_id, "pause_automation", {"trigger_id": "trg-1"})["ok"] is True
    with pytest.raises(cards.CardRefused, match="did not list"):
        cards.card_call(card_id, "cancel_automation", {"trigger_id": "trg-other"})
    preview = cards.card_call(card_id, "cancel_automation", {"trigger_id": "trg-1"})["confirm"]
    assert "Weekly ETH" in preview["description"]
    assert "cancel_automation" not in [name for name, _ in _calls(server)]
    cards.card_execute(card_id, preview["confirm_id"])
    assert _calls(server)[-1] == ("cancel_automation", {"trigger_id": "trg-1"})


# -- records: disk + TTL -----------------------------------------------------------

def test_records_survive_a_restart_and_expire_after_a_day(server, tmp_path):
    card_id = _show()["card_id"]
    path = tmp_path / "cards" / f"{card_id}.json"
    assert path.exists() and (path.stat().st_mode & 0o777) == 0o600
    cards.reset_for_tests()  # a new process: memory is empty
    assert cards.get_card(card_id)["uri"] == "ui://coinfello/portfolio-card.html"
    assert [card["id"] for card in cards.list_cards()] == [card_id]

    record = cards.get_card(card_id)
    record["created_at"] = time.time() - cards.CARD_TTL_SECONDS - 1
    cards.save_card(record)
    with pytest.raises(cards.CardRefused, match="expired"):
        cards.get_card(card_id)
    assert not path.exists()
    assert cards.list_cards() == []


def test_list_drops_expired_cards_and_orders_newest_first(server):
    old = _show()["card_id"]
    new = _show("yield", {"token": "ETH"})["card_id"]
    record = cards.get_card(old)
    record["created_at"] -= 10
    cards.save_card(record)
    assert [card["id"] for card in cards.list_cards()] == [new, old]
    record["created_at"] = time.time() - cards.CARD_TTL_SECONDS - 5
    cards.save_card(record)
    assert [card["id"] for card in cards.list_cards()] == [new]


@pytest.mark.parametrize("card_id", ["../../etc/passwd", "ABC", "", "0" * 31])
def test_malformed_card_ids_are_refused(server, card_id):
    with pytest.raises(cards.CardRefused, match="Unknown card"):
        cards.get_card(card_id)


def test_dismissed_cards_are_gone(server):
    card_id = _show()["card_id"]
    cards.dismiss_card(card_id)
    assert cards.list_cards() == []


# -- the agent tool, as Hermes registers and dispatches it -------------------------

def _load_plugin(monkeypatch):
    import importlib.util
    import sys
    import types
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    registry = types.ModuleType("tools.registry")
    registry.tool_error = lambda message: json.dumps({"error": message})
    registry.tool_result = lambda payload: json.dumps(payload)
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.registry", registry)
    for name in [n for n in sys.modules if n == "coinfello_pkg" or n.startswith("coinfello_pkg.")]:
        monkeypatch.delitem(sys.modules, name)
    spec = importlib.util.spec_from_file_location(
        "coinfello_pkg", root / "__init__.py", submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "coinfello_pkg", module)
    spec.loader.exec_module(module)
    return module


class _Ctx:
    def __init__(self, surface):
        self.handlers, self.schemas, self.surface = {}, {}, surface

    def register_tool(self, **kwargs):
        self.handlers[kwargs["name"]] = kwargs["handler"]
        self.schemas[kwargs["name"]] = kwargs["schema"]

    def register_hook(self, name, callback):
        pass

    def session_surface(self):
        return self.surface


def test_the_tool_takes_hermes_context_keywords_and_reads_the_surface(monkeypatch):
    plugin = _load_plugin(monkeypatch)
    ctx = _Ctx("desktop")
    plugin.register(ctx)
    seen = {}

    def fake_show(card, arguments, *, session_id=""):
        seen.update(card=card, arguments=arguments, session_id=session_id,
                    surface=plugin._cards.session_surface())
        return {"ok": True, "shown": "coinfello_pane"}

    monkeypatch.setattr(plugin._cards, "show_card", fake_show)
    handler = ctx.handlers["coinfello_show_card"]
    # What model_tools passes every plugin handler (narrowed by signature).
    out = json.loads(handler({"card": "yield", "arguments": {"token": "USDC"}},
                             task_id="t-1", session_id="sess-9", user_task="..."))
    assert out == {"ok": True, "shown": "coinfello_pane"}
    assert seen == {"card": "yield", "arguments": {"token": "USDC"}, "session_id": "sess-9", "surface": "desktop"}
    assert json.loads(handler({"card": "yield", "arguments": "USDC"}))["error"].startswith("arguments is an object")


@pytest.fixture
def show_tool(monkeypatch, server):
    """coinfello_show_card's handler on the desktop surface, over the same
    modules the ``server`` fixture points at the mock."""
    import importlib
    import sys
    import types

    registry = types.ModuleType("tools.registry")
    registry.tool_error = lambda message: json.dumps({"error": message})
    registry.tool_result = lambda payload: json.dumps(payload)
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.registry", registry)
    monkeypatch.delitem(sys.modules, "coinfello_tools", raising=False)
    tools = importlib.import_module("coinfello_tools")
    monkeypatch.setattr(cards, "_surface_reader", lambda: "desktop")
    name, _schema, handler = tools._SHOW_CARD
    assert name == "coinfello_show_card"
    return lambda args: json.loads(handler(args, session_id="sess-9"))


def test_arguments_beside_card_are_taken_as_the_cards_own(show_tool, server):
    # What Claude Sonnet 4.6 sent live: the yield card's arguments at the top level.
    out = show_tool({"card": "yield", "token": "USDC", "chain_ids": [8453]})
    assert out["shown"] == "coinfello_pane"
    assert _calls(server)[-1] == ("show_yield_card", {"token": "USDC", "chain_ids": [8453]})


def test_nested_arguments_win_over_the_same_key_beside_card(show_tool, server):
    show_tool({"card": "yield", "token": "ETH", "chain_ids": [1], "arguments": {"token": "USDC"}})
    assert _calls(server)[-1] == ("show_yield_card", {"token": "USDC", "chain_ids": [1]})


def test_folded_arguments_lose_secrets_and_undeclared_keys(show_tool, server):
    show_tool({"card": "yield", "token": "USDC", "session_token": "tok-model",
               "sessionToken": "tok-model", "bogus": 1, "arguments": {"also_bogus": 2}})
    assert _calls(server)[-1] == ("show_yield_card", {"token": "USDC"})
    assert server.mock_state["auth_headers"][-1] == "Bearer tok-live"


def test_a_missing_required_argument_reaches_the_model_as_a_clear_error(show_tool, server):
    out = show_tool({"card": "yield", "chain_ids": [8453]})
    assert "needs token, inside `arguments`" in out["error"]
    assert "-32602" not in out["error"]
    assert _calls(server) == []


def test_the_tool_schema_offers_every_card_but_sign_in(monkeypatch):
    plugin = _load_plugin(monkeypatch)
    ctx = _Ctx("cli")
    plugin.register(ctx)
    schema = ctx.schemas["coinfello_show_card"]["parameters"]
    assert schema["required"] == ["card"]
    assert schema["properties"]["card"]["enum"] == list(cards.CARDS)
    assert "sign_in" not in schema["properties"]["card"]["enum"]


# -- the pane's HTTP surface --------------------------------------------------------

@pytest.fixture
def api(server):
    import importlib.util
    import sys
    from pathlib import Path

    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    api_file = Path(__file__).resolve().parent.parent / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("coinfello_plugin_api_cards", api_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/coinfello")
    return TestClient(app)


BASE = "/api/plugins/coinfello"


def test_pane_lists_mounts_relays_and_confirms_over_http(api, server):
    _prepare_bridge()
    card_id = _show("quote", {"intent_id": INTENT})["card_id"]
    listed = api.get(f"{BASE}/cards").json()
    assert [card["id"] for card in listed["cards"]] == [card_id]

    document = api.get(f"{BASE}/cards/{card_id}", params={"theme": "dark"}).json()
    assert document["ok"] is True and document["confirm"] == ["execute_intent"]
    assert document["relay"] == ["prepare_send", "prepare_swap", "show_quote_card", "whoami"]

    refused = api.post(f"{BASE}/cards/{card_id}/call", json={"tool": "fello_chat", "arguments": {"message": "x"}}).json()
    assert refused["ok"] is False and "not available" in refused["error"]

    preview = api.post(f"{BASE}/cards/{card_id}/call",
                       json={"tool": "execute_intent", "arguments": {"intent_id": INTENT}}).json()
    assert "execute_intent" not in [name for name, _ in _calls(server)]
    done = api.post(f"{BASE}/cards/{card_id}/execute", json={"confirm_id": preview["confirm"]["confirm_id"]}).json()
    assert done["ok"] is True and done["tool"] == "execute_intent"
    again = api.post(f"{BASE}/cards/{card_id}/execute", json={"confirm_id": preview["confirm"]["confirm_id"]}).json()
    assert again["ok"] is False

    assert api.post(f"{BASE}/cards/{card_id}/dismiss").json() == {"ok": True}
    assert api.get(f"{BASE}/cards/{card_id}").json()["ok"] is False


def test_pane_read_only_quote_says_enable_trading(api, server):
    core.save_state({"access": "read_only"})
    card_id = _show("quote", {"intent_id": INTENT})["card_id"]
    out = api.post(f"{BASE}/cards/{card_id}/call", json={"tool": "prepare_swap", "arguments": {}}).json()
    assert out["ok"] is False and out["needs_trading_access"] is True
