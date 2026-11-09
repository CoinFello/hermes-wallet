"""Tests for the stdlib MCP streamable-HTTP client."""

from __future__ import annotations

import pytest

import coinfello_mcp
from coinfello_mcp import CoinFelloMCP, MCPError, ToolError


def _url(server) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/mcp"


def test_initialize_and_call_tool(mock_mcp):
    client = CoinFelloMCP(_url(mock_mcp))
    server_info = client.initialize()
    assert server_info["serverInfo"]["name"] == "coinfello"
    assert mock_mcp.mock_state["initialized_notices"] == 1

    result = client.call_tool("whoami", {})
    assert result["wallet_address"] == "0xWALLET"
    # exactly one initialize so far
    assert mock_mcp.mock_state["initialize_calls"] == 1


def test_lazy_initialization_and_sse_response(mock_mcp):
    client = CoinFelloMCP(_url(mock_mcp))
    mock_mcp.mock_state["sse_mode"] = True

    # no explicit initialize: call_tool must initialize lazily and parse the
    # SSE-encoded response
    result = client.call_tool("get_balances", {})
    assert result["totalValueUsd"] == 2500.0
    assert [token["symbol"] for token in result["tokens"]] == ["USDC", "ETH"]


def test_tool_error_raises_with_server_text(mock_mcp):
    client = CoinFelloMCP(_url(mock_mcp))
    with pytest.raises(ToolError) as excinfo:
        client.call_tool("boom")
    assert "boom failed" in str(excinfo.value)


def test_text_result_returned_verbatim(mock_mcp):
    client = CoinFelloMCP(_url(mock_mcp))
    result = client.call_tool("privy_send_login_code", {"email": "a@b.c"})
    assert "login code was sent" in result


def test_session_expiry_reinitializes_and_retries(mock_mcp):
    client = CoinFelloMCP(_url(mock_mcp))
    client.initialize()

    # invalidates the server-side session; the next call 404s, and the client
    # must re-initialize and succeed without surfacing the error
    client.call_tool("expire_session")
    result = client.call_tool("whoami", {})
    assert result["wallet_address"] == "0xWALLET"
    assert mock_mcp.mock_state["initialize_calls"] == 2


def test_retry_disabled_surfaces_session_expiry(mock_mcp):
    client = CoinFelloMCP(_url(mock_mcp))
    client.initialize()
    client.call_tool("expire_session")
    with pytest.raises(coinfello_mcp.SessionExpired):
        client.call_tool("whoami", {}, _retry=False)


def test_unreachable_server_raises_mcp_error():
    client = CoinFelloMCP("http://127.0.0.1:1/mcp", timeout=2.0)
    with pytest.raises(MCPError):
        client.call_tool("whoami", {})