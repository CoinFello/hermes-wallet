"""The in-app strategies view (coinfello-web /embed/strategies, scope 'strategies')."""

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
    mock_mcp.mock_state.update(actions=True, portfolio_embed=True, strategies_embed=True)
    return mock_mcp


def _embed_calls(server):
    return [args for name, args in server.mock_state["tool_calls"] if name == "create_embed_token"]


def test_strategies_token_is_scoped_and_not_the_session_token(server):
    minted = core.embed_token("strategies")
    assert minted["token"] == "cfemb_strategies"
    assert "tok-live" not in repr(minted)
    assert minted["embed_url"].endswith("/embed/strategies")
    assert _embed_calls(server) == [{"scope": "strategies"}]


def test_read_only_sessions_can_browse_strategies_but_not_swap(server):
    server.mock_state["access_mode"] = True
    core.save_state({"signed_in": True, "test_grant": "tok-old", "wallet_address": "0xWALLET", "access": "read_only"})
    assert core.embed_token("strategies")["token"] == "cfemb_strategies"
    with pytest.raises(core.NeedsTradingAccess):
        core.embed_token("swap")


def test_capability_comes_from_the_scope_enum(server):
    model = core.portfolio()
    assert model["can_view_strategies"] is True and model["can_view_portfolio"] is True


def test_a_server_with_the_portfolio_embed_only_keeps_the_strategies_link(server):
    server.mock_state["strategies_embed"] = False
    core.server_tools(refresh=True)
    model = core.portfolio()
    assert model["can_view_portfolio"] is True and model["can_view_strategies"] is False
    with pytest.raises(RuntimeError, match="Strategies in Hermes needs a CoinFello server update"):
        core.embed_token("strategies")
    assert _embed_calls(server) == []  # never sends a scope the server did not advertise


def _api():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    path = Path(__file__).resolve().parents[1] / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location("cf_plugin_api_strategies", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # as the dashboard importer does
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/coinfello")
    return TestClient(app)


def test_route_mints_a_strategies_token(server):
    minted = _api().post("/api/plugins/coinfello/embed-token", json={"scope": "strategies"}).json()
    assert minted["ok"] is True and minted["embed_url"].endswith("/embed/strategies")
