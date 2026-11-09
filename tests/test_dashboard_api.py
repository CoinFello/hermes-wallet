"""HTTP-level tests for the dashboard router the desktop pane calls.

Exercises the real FastAPI request parsing (the layer that produced the 422
"query.args / query.kwargs required" bug), against the mock MCP server.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import coinfello_core as core  # noqa: E402

API_FILE = Path(__file__).resolve().parent.parent / "dashboard" / "plugin_api.py"


def _load_router():
    # Mirror the dashboard importer: spec_from_file_location, no package.
    spec = importlib.util.spec_from_file_location("coinfello_plugin_api", API_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.router


@pytest.fixture
def client(mock_mcp, isolated_state, monkeypatch):
    host, port = mock_mcp.server_address[:2]
    monkeypatch.setattr(core, "mcp_url", lambda: f"http://{host}:{port}/mcp")
    app = FastAPI()
    app.include_router(_load_router(), prefix="/api/plugins/coinfello")
    return TestClient(app)


BASE = "/api/plugins/coinfello"


def test_status_no_query_params_required(client):
    response = client.get(f"{BASE}/status")
    assert response.status_code == 200, response.text
    assert response.json()["connected"] is False


def test_full_sign_in_over_http(client):
    sent = client.post(f"{BASE}/connect", json={"email": "user@example.com"})
    assert sent.status_code == 200, sent.text
    assert sent.json()["ok"] is True

    verified = client.post(
        f"{BASE}/verify", json={"email": "user@example.com", "code": "111111"}
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "signed_in"

    status = client.get(f"{BASE}/status").json()
    assert status["connected"] is True
    assert "session_token" not in status

    portfolio = client.get(f"{BASE}/portfolio")
    assert portfolio.status_code == 200, portfolio.text
    model = portfolio.json()
    assert model["total_text"] == "$2,500.00"
    assert [n["chain_id"] for n in model["networks"]] == [1, 8453]

    wallet = client.get(f"{BASE}/wallet")
    assert wallet.status_code == 200, wallet.text
    assert wallet.json()["address"] == "0xWALLET"

    out = client.post(f"{BASE}/disconnect")
    assert out.status_code == 200, out.text
    assert client.get(f"{BASE}/status").json()["connected"] is False


def test_approval_route(client):
    client.post(f"{BASE}/connect", json={"email": "approval@example.com"})
    verified = client.post(
        f"{BASE}/verify", json={"email": "approval@example.com", "code": "111111"}
    ).json()
    assert verified["status"] == "approval_required"

    pending = client.post(f"{BASE}/approval", json={"approval_id": verified["approval_id"]})
    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == "pending"

    # body with no approval_id falls back to the stored pending one
    stored = client.post(f"{BASE}/approval", json={})
    assert stored.status_code == 200, stored.text


def test_failures_fold_into_ok_false(client):
    bad = client.post(f"{BASE}/verify", json={"email": "user@example.com", "code": "12"})
    assert bad.status_code == 200
    assert bad.json() == {"ok": False, "error": "the login code is 6 digits"}

    unsigned = client.get(f"{BASE}/portfolio")
    assert unsigned.status_code == 200
    assert unsigned.json()["ok"] is False


def test_browser_sign_in_over_http(client, mock_mcp):
    mock_mcp.mock_state["browser_sign_in"] = True
    started = client.post(f"{BASE}/connect", json={})
    assert started.status_code == 200, started.text
    assert started.json()["user_code"] == "WDJB-MJHT"

    status = client.get(f"{BASE}/status").json()
    assert status["sign_in_mode"] == "browser"
    assert status["pending_user_code"] == "WDJB-MJHT"

    mock_mcp.mock_state["browser_approved"] = True
    done = client.post(f"{BASE}/approval", json={})
    assert done.json()["status"] == "signed_in"

    cancelled = client.post(f"{BASE}/cancel-sign-in")
    assert cancelled.status_code == 200


def test_wallet_requires_sign_in(client):
    response = client.get(f"{BASE}/wallet")
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_send_and_swap_routes_over_http(client, mock_mcp):
    mock_mcp.mock_state["actions"] = True
    client.post(f"{BASE}/connect", json={"email": "user@example.com"})
    client.post(f"{BASE}/verify", json={"email": "user@example.com", "code": "111111"})

    prepared = client.post(f"{BASE}/send/prepare", json={
        "chain_id": 8453, "token": "0xUSDC", "amount": "25.5",
        "recipient": "0x1111111111111111111111111111111111111111",
    })
    assert prepared.status_code == 200, prepared.text
    intent = prepared.json()["intent_id"]

    executed = client.post(f"{BASE}/intent/execute", json={"intent_id": intent})
    assert executed.status_code == 200, executed.text
    assert executed.json()["explorer_url"].endswith("0xabc123")

    replay = client.post(f"{BASE}/intent/execute", json={"intent_id": intent})
    assert replay.json()["ok"] is False

    token = client.post(f"{BASE}/embed-token")
    assert token.status_code == 200, token.text
    assert token.json()["token"].startswith("cfemb_")


def test_send_validation_errors_fold_into_ok_false(client, mock_mcp):
    mock_mcp.mock_state["actions"] = True
    client.post(f"{BASE}/connect", json={"email": "user@example.com"})
    client.post(f"{BASE}/verify", json={"email": "user@example.com", "code": "111111"})
    bad = client.post(f"{BASE}/send/prepare", json={
        "chain_id": 8453, "token": "0xUSDC", "amount": "1", "recipient": "bob"})
    assert bad.status_code == 200
    assert bad.json()["ok"] is False
    assert "0x address" in bad.json()["error"]


def test_limit_routes_over_http(client, mock_mcp):
    mock_mcp.mock_state.update(browser_sign_in=True, actions=True, access_mode=True, limit_mode=True)
    core.save_state({"session_token": "tok-trade", "wallet_address": "0xWALLET"})
    client.get(f"{BASE}/status")

    lowered = client.post(f"{BASE}/limit", json={"limit_usd": 100})
    assert lowered.status_code == 200, lowered.text
    assert lowered.json()["status"] == "changed"

    raised = client.post(f"{BASE}/limit", json={"limit_usd": 9000})
    assert raised.json()["status"] == "approval_required"
    assert client.post(f"{BASE}/limit/poll").json()["status"] == "pending"
    assert client.post(f"{BASE}/limit/cancel").json()["ok"] is True

    read_only = client.post(f"{BASE}/limit", json={"limit_usd": None})
    assert read_only.json()["access"] == "read_only"
