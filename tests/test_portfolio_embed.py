"""The in-app portfolio (coinfello-web /embed/portfolio, scope 'portfolio')."""

import importlib.util
import sys
from pathlib import Path

import pytest

import coinfello_core as core


@pytest.fixture
def server(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/api/mcp")
    core.save_state({"signed_in": True, "test_grant": "tok-live", "wallet_address": "0xWALLET"})
    mock_mcp.mock_state.update(actions=True, portfolio_embed=True)
    return mock_mcp


def _embed_calls(server):
    return [args for name, args in server.mock_state["tool_calls"] if name == "create_embed_token"]


def test_portfolio_token_is_scoped_and_not_the_session_token(server):
    minted = core.embed_token("portfolio")
    assert minted["token"] == "cfemb_portfolio"
    assert "tok-live" not in repr(minted)
    assert minted["embed_url"].endswith("/embed/portfolio")
    assert _embed_calls(server) == [{"scope": "portfolio"}]


def test_read_only_sessions_can_open_the_portfolio_but_not_swap(server):
    server.mock_state["access_mode"] = True
    core.save_state({"signed_in": True, "test_grant": "tok-old", "wallet_address": "0xWALLET", "access": "read_only"})
    assert core.embed_token("portfolio")["token"] == "cfemb_portfolio"
    with pytest.raises(core.NeedsTradingAccess):
        core.embed_token("swap")


def test_capability_comes_from_the_scope_enum(server):
    assert core.portfolio()["can_view_portfolio"] is True


def test_servers_without_the_scope_keep_the_browser_link(server):
    server.mock_state["portfolio_embed"] = False  # create_embed_token exists, swap only
    core.server_tools(refresh=True)
    assert core.portfolio()["can_view_portfolio"] is False
    with pytest.raises(RuntimeError, match="needs a CoinFello server update"):
        core.embed_token("portfolio")
    assert _embed_calls(server) == []  # never sends a scope the server did not advertise


def test_unknown_scopes_are_refused_locally(server):
    with pytest.raises(ValueError):
        core.embed_token("admin")
    assert _embed_calls(server) == []


def _api():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    path = Path(__file__).resolve().parents[1] / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("cf_plugin_api_embed", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # as the dashboard importer does
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/coinfello")
    return TestClient(app)


def test_route_defaults_to_swap_and_accepts_portfolio(server):
    client = _api()
    assert client.post("/api/plugins/coinfello/embed-token").json()["embed_url"].endswith("/embed/swap")
    portfolio = client.post("/api/plugins/coinfello/embed-token", json={"scope": "portfolio"}).json()
    assert portfolio["ok"] is True and portfolio["embed_url"].endswith("/embed/portfolio")
    assert client.post("/api/plugins/coinfello/embed-token", json={"scope": "admin"}).status_code == 422


# -- alongside the Earn embed: one create_embed_token, one scope enum -----------------


def test_one_server_can_offer_earn_and_the_portfolio(server):
    server.mock_state["embed_scopes"] = ("swap", "earn")  # plus portfolio, from portfolio_embed
    core.server_tools(refresh=True)
    model = core.portfolio()
    assert model["can_view_portfolio"] is True and model["earn_supported"] is True
    assert core.embed_token("earn")["token"] == "cfemb_earn"
    assert core.embed_token("portfolio")["token"] == "cfemb_portfolio"
    assert _embed_calls(server) == [{"scope": "earn"}, {"scope": "portfolio"}]


def test_an_earn_only_enum_keeps_the_portfolio_in_the_browser(server):
    server.mock_state.update(embed_scopes=("swap", "earn"), portfolio_embed=False)
    core.server_tools(refresh=True)
    model = core.portfolio()
    assert model["can_view_portfolio"] is False and model["earn_supported"] is True
    with pytest.raises(RuntimeError, match="needs a CoinFello server update"):
        core.embed_token("portfolio")
    assert _embed_calls(server) == []


def test_the_route_mints_every_scope_the_pane_hosts(server):
    server.mock_state["embed_scopes"] = ("swap", "earn")
    core.server_tools(refresh=True)
    client = _api()
    for scope in ("swap", "earn", "portfolio"):
        minted = client.post("/api/plugins/coinfello/embed-token", json={"scope": scope}).json()
        assert minted["ok"] is True and minted["embed_url"].endswith(f"/embed/{scope}")
    assert _embed_calls(server) == [{"scope": "swap"}, {"scope": "earn"}, {"scope": "portfolio"}]
