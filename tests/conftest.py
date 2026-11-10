"""Test fixtures: a local mock of the CoinFello MCP server.

Implements just enough of the streamable-HTTP MCP transport to exercise the
plugin's client: initialize (issues a session id), notifications/initialized,
tools/call with canned sign-in/read results, SSE-encoded responses, and
session invalidation for the 404-retry path.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pytest  # noqa: E402

# canned tool results ---------------------------------------------------------

CODE_SENT = f"A login code was sent. Expires in a few minutes."

SESSION = {
    "session_token": "tok-abc123",
    "wallet_address": "0xWALLET",
    "expires_at": "2026-11-17T00:00:00Z",
    "next": "Call fello_chat with a message describing what you want done.",
}

APPROVAL_REQUIRED = {
    "approval_required": True,
    "approval_url": "https://example.test/authorize",
    "approval_id": "11111111-1111-1111-1111-111111111111",
    "expires_in_seconds": 600,
    "next": "Give the human approval_url to open in a browser.",
}

PENDING = {"status": "pending", "next": "Not approved yet. Call again."}

BALANCES = {
    "tokens": [
        {"chainId": 8453, "symbol": "USDC", "balance": "1000", "valueUsd": 1000.0},
        {"chainId": 1, "symbol": "ETH", "balance": "0.5", "valueUsd": 1500.0},
    ],
    "totalValueUsd": 2500.0,
}

BALANCES_TEXT = json.dumps(BALANCES)

WHOAMI = {"wallet_address": "0xWALLET", "expires_at": "2026-11-17T00:00:00Z"}

BROWSER_SIGN_IN = {
    # Production: the link never carries the code.
    "approval_url": "https://example.test/authorize",
    "user_code": "WDJB-MJHT",
    "approval_id": "22222222-2222-2222-2222-222222222222",
    "expires_in_seconds": 600,
    "next": "Show the human user_code and give them approval_url.",
}

RENEWED = {
    "session_token": "tok-renewed",
    "wallet_address": "0xWALLET",
    "expires_at": "2099-01-01T00:00:00Z",
}

BASE_TOOLS = (
    "privy_send_login_code", "privy_verify_login_code", "privy_complete_approval",
    "whoami", "sign_out", "fello_chat", "fello_job_status", "get_balances",
)

ACTION_TOOLS = ("prepare_send", "prepare_swap", "execute_intent", "create_embed_token")
# Added after a bridge incident.
STATUS_TOOLS = ("get_transfer_status",)

PREPARED_BRIDGE = {
    "intentId": "66666666-6666-6666-6666-666666666666",
    "expiresInSeconds": 120,
    "summary": {
        "kind": "bridge", "fromChainId": 1, "toChainId": 137,
        "fromChainName": "Ethereum Mainnet", "toChainName": "Polygon",
        "from": {"symbol": "ETH", "address": "0x0000000000000000000000000000000000000000",
                 "amount": "0.004186", "valueUsd": 10.0},
        "to": {"symbol": "POL", "address": "0x0000000000000000000000000000000000000000",
               "amount": "113.82", "minimumAmount": "113.25", "valueUsd": 10.28},
        "slippage": 0.005, "gasUsd": 0.12, "feesUsd": 0.06, "valueLossPct": -2.8,
        "estimatedSeconds": 18, "bridges": ["layerswap"],
    },
}

TRANSFER_WRONG_TOKEN = {
    "txHash": "0x" + "3e" * 32, "status": "DONE", "substatus": "PARTIAL",
    "outcome": "wrong_token", "deliveredRequestedToken": False, "tool": "across",
    "received": {"chainId": 137, "symbol": "WETH", "amount": "0.004149590496376045"},
}

PREPARED_SEND = {
    "intentId": "33333333-3333-3333-3333-333333333333",
    "expiresInSeconds": 120,
    "summary": {
        "kind": "send", "chainId": 8453, "chainName": "Base",
        "token": {"symbol": "USDC", "address": "0xUSDC", "decimals": 6},
        "amount": "25.5", "valueUsd": 25.5,
        "recipient": "0x1111111111111111111111111111111111111111",
    },
}

#: the server's prepare_earn_deposit, for a yield the yield card listed.
EARN_INTENT = "88888888-8888-8888-8888-888888888888"
PREPARED_EARN = {
    "intentId": EARN_INTENT,
    "expiresInSeconds": 120,
    "summary": {
        "kind": "earn_deposit", "yieldId": "base-usdc-aave-v3-lending", "name": "Aave v3 USDC",
        "protocol": "aave", "chainId": 8453, "chainName": "Base",
        "token": {"symbol": "USDC", "address": "0xUSDC", "decimals": 6},
        "amount": "50", "valueUsd": 50.0, "ratePct": 4.8,
    },
}
#: the server's yield card rows: Deposit only where the earn card can take it.
EARN_FLOW_YIELD_ROWS = [
    {"id": "base-usdc-aave-v3-lending", "name": "Aave v3 USDC", "protocol": "aave",
     "network": "Base", "ratePct": 4.8, "tvlUsd": 120_000_000, "outlier": False,
     "flags": [], "depositable": True},
    {"id": "base-usdc-weth-aerodrome", "name": "USDC/WETH", "protocol": "aerodrome",
     "network": "Base", "ratePct": 12.0, "tvlUsd": 9_000_000, "outlier": False,
     "flags": [], "depositable": False},
]

EMBED_TOKEN = {
    "embed_token": "cfemb_test",
    "expires_at": "2099-01-01T00:15:00Z",
    "embed_url": "https://app.coinfello.test/embed/swap",
}


# MCP App cards ------------------------------------

CARD_MIME = "text/html;profile=mcp-app"
MODEL_NOTE = (
    "Model note: the host shows the card above your reply, at this tool call. "
    "The card is the list."
)
CARD_HTML = (
    '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora">\n'
    "</head>\n<body><div class=\"card\" id=\"root\"></div>"
    "<script>parent.postMessage({jsonrpc: '2.0', id: 1, method: 'ui/initialize'}, '*')</script>"
    "</body>\n</html>"
)
CARD_RESOURCE_META = {"ui": {"prefersBorder": True, "csp": {"resourceDomains": [
    "https://fonts.googleapis.com", "https://fonts.gstatic.com",
    "http://insecure.test", "https://evil.test; script-src *", 42,
]}}}
RETRYABLE = {"get_balances", "get_positions", "prepare_swap", "whoami"}


def _ui_meta(uri, *, flat_only=False):
    meta = {"ui/resourceUri": uri}
    if not flat_only:
        meta["ui"] = {"resourceUri": uri, "visibility": ["model", "app"]}
    return meta


def _props(*names, required=()):
    schema = {"type": "object", "properties": {name: {"type": "string"} for name in names}}
    if required:
        schema["required"] = list(required)
    return schema


CARD_TOOLS = [
    {"name": "show_portfolio_card", "inputSchema": _props("chain_ids", "session_token"),
     "_meta": _ui_meta("ui://coinfello/portfolio-card.html")},
    {"name": "show_quote_card", "inputSchema": _props("intent_id", "session_token"),
     "_meta": _ui_meta("ui://coinfello/quote-card.html")},
    {"name": "show_error_card", "inputSchema": _props("kind", "message", "retry_tool", "session_token"),
     "_meta": _ui_meta("ui://coinfello/error-card.html")},
    {"name": "show_automations_card", "inputSchema": _props("session_token"),
     "_meta": _ui_meta("ui://coinfello/automations-card.html")},
    # Only the deprecated flat key, like hosts before the MCP Apps rename.
    # Requires its token, like the live server (and a session token the
    # plugin sends as a header instead).
    {"name": "show_yield_card", "inputSchema": _props("token", "chain_ids", "session_token",
                                                      required=("token", "session_token")),
     "_meta": _ui_meta("ui://coinfello/yield-card.html", flat_only=True)},
    # Declares a card URI the plugin does not know: never drawn.
    # The typed-yield-id deposit card, which desktop replaces with the Earn view.
    {"name": "show_earn_deposit_card", "inputSchema": _props("yield_id", "amount", "session_token"),
     "_meta": _ui_meta("ui://coinfello/earn-deposit-card.html")},
    {"name": "show_status_card", "inputSchema": _props("session_token"),
     "_meta": _ui_meta("ui://elsewhere/status-card.html")},
    {"name": "show_sign_in_card", "inputSchema": _props("session_token"),
     "_meta": _ui_meta("ui://coinfello/sign-in-card.html")},
    {"name": "prepare_earn_deposit", "inputSchema": _props("yield_id", "amount", "session_token")},
    {"name": "pause_automation", "inputSchema": _props("trigger_id", "session_token")},
    {"name": "cancel_automation", "inputSchema": _props("trigger_id", "session_token")},
    {"name": "get_positions", "inputSchema": _props("session_token")},
]
CARD_TRADE_SCHEMAS = {
    "prepare_swap": _props("from_chain_id", "from_token", "to_chain_id", "to_token", "amount", "slippage", "session_token"),
    "prepare_send": _props("chain_id", "token", "amount", "recipient", "session_token"),
    "execute_intent": _props("intent_id", "session_token"),
    "get_balances": _props("chain_ids", "session_token"),
}
AUTOMATION_ROWS = [
    {"id": "trg-1", "name": "Weekly ETH", "summary": "Buys $10 of ETH every week", "whyPaused": None},
]


def _card_result(text, data):
    return {"content": [{"type": "text", "text": f"{MODEL_NOTE}\n{text}"}], "structuredContent": data}


def _card_tool(name, arguments, state=None):
    """The mock's show_*_card answers, or None for any other tool.
    ``state["earn_flow"]``: the yield and earn cards of the server."""
    earn_flow = bool(state and state.get("earn_flow"))
    if name == "show_portfolio_card":
        return _card_result(
            "Portfolio: $2,500.00\nUSDC on Base: $1,000.00\nETH on Ethereum: $1,500.00",
            {"totalValueUsd": 2500.0, "session_token": "tok-leaked",
             "nested": {"embedToken": "cfemb_leaked", "token": "USDC"}},
        )
    if name == "show_quote_card":
        return _card_result("Bridge 0.004186 ETH to POL.", {"kind": "bridge", "intentId": arguments.get("intent_id")})
    if name == "show_error_card":
        retry = arguments.get("retry_tool")
        return _card_result("Network did not answer.", {
            "kind": "network", "retryTool": retry if retry in RETRYABLE else None, "retryArgs": {}})
    if name == "show_automations_card":
        return _card_result("1 open automation.\nWeekly ETH", {"rows": AUTOMATION_ROWS, "note": None})
    if name == "show_earn_deposit_card" and earn_flow:
        yield_id = arguments.get("yield_id")
        row = next((r for r in EARN_FLOW_YIELD_ROWS if r["id"] == yield_id), None)
        opportunity = None if row is None else {
            "yieldId": row["id"], "name": row["name"], "protocol": row["protocol"],
            "chainName": row["network"], "token": {"symbol": "USDC", "decimals": 6},
            "ratePct": row["ratePct"], "balance": "120.5"}
        return _card_result("Earn deposit.", {
            "kind": "earn_deposit", "phase": "form", "intentId": None,
            "prepareTool": "prepare_earn_deposit",
            "prepareBase": {"yield_id": yield_id} if opportunity else {},
            "opportunity": opportunity, "browseToken": None if opportunity else "USDC"})
    if name == "show_earn_deposit_card":
        return _card_result("Deposit into a yield: enter its id.", {"yieldId": arguments.get("yield_id")})
    if name == "show_yield_card" and earn_flow:
        return _card_result("Yields for USDC.", {"token": arguments.get("token"), "rows": EARN_FLOW_YIELD_ROWS})
    if name == "prepare_earn_deposit":
        return _tool_result(PREPARED_EARN)
    if name in ("show_yield_card", "show_status_card", "show_sign_in_card"):
        return _card_result(f"{name} text", {"rows": []})
    if name in ("pause_automation", "cancel_automation"):
        return _tool_result({"ok": True, "trigger_id": arguments.get("trigger_id")})
    if name == "get_positions":
        return _tool_result({"defi": []})
    return None

# coinfello-web lib/mcp/read_tools.ts readActivity: two independently read
# sections, each {data} or {error}. Page 1 has a cursor; page 2 ends.
ACTIVITY_PAGE_1 = {
    "address": "0x1111111111111111111111111111111111111111",
    "transactions": {"data": {
        "entries": [
            {"at": "2026-11-09T14:02:00Z", "status": "done", "actor": "fello", "automation": "Dip buyer",
             "what": {"kind": "transaction", "verb": "swapped", "attempted": False, "protocol": "Uniswap",
                      "counterparty": None, "moreCount": 1,
                      "from": {"symbol": "USDC", "address": "0xa", "chainId": 8453, "amount": "50", "amountUsd": "50"},
                      "to": {"symbol": "ETH", "address": "0xb", "chainId": 8453, "amount": "0.0161", "amountUsd": "49.9"}},
             "result": {"kind": "amount", "flow": "exchange",
                        "leg": {"symbol": "ETH", "address": "0xb", "chainId": 8453, "amount": "0.0161", "amountUsd": "49.9"}},
             "chainId": 8453, "txHash": "0x" + "ab" * 32},
            {"at": "2026-11-08T09:00:00Z", "status": "done", "actor": "incoming", "automation": None,
             "what": {"kind": "transaction", "verb": "received", "attempted": False, "protocol": None,
                      "counterparty": "0x2222222222222222222222222222222222222222", "moreCount": 0,
                      "from": None,
                      "to": {"symbol": "USDC", "address": "0xa", "chainId": 8453, "amount": "250", "amountUsd": "250"}},
             "result": {"kind": "amount", "flow": "in",
                        "leg": {"symbol": "USDC", "address": "0xa", "chainId": 8453, "amount": "250", "amountUsd": "250"}},
             "chainId": 8453, "txHash": "0x" + "cd" * 32},
        ],
        "nextCursor": "cursor-2",
        "incomplete": False,
    }},
    "hyperliquidFills": {"data": {"fills": [
        {"at": "2026-11-09T10:00:00Z", "coin": "ETH", "side": "sell", "direction": "Close Long",
         "price": "3120.4", "size": "0.5", "closedPnl": "12.3", "fee": "0.4", "feeToken": "USDC",
         "orderId": 77, "txHash": "0x" + "ef" * 32, "liquidation": False},
    ], "truncated": False}},
}

ACTIVITY_PAGE_2 = {
    "address": "0x1111111111111111111111111111111111111111",
    "transactions": {"data": {
        "entries": [
            {"at": "2026-11-10T09:00:00Z", "status": "failed", "actor": "you", "automation": None,
             "what": {"kind": "transaction", "verb": "sent", "attempted": True, "protocol": None,
                      "counterparty": "0x3333333333333333333333333333333333333333", "moreCount": 0,
                      "from": {"symbol": "USDC", "address": "0xa", "chainId": 8453, "amount": "10", "amountUsd": "10"},
                      "to": None},
             "result": {"kind": "failed", "reason": {"code": "reverted"}},
             "chainId": 8453, "txHash": "0x" + "12" * 32},
        ],
        "nextCursor": None,
        "incomplete": False,
    }},
    "hyperliquidFills": {"error": "Hyperliquid fills did not answer within 20s"},
}


def _access_for(authorization, state):
    override = state.get("access_override", {}).get(authorization)
    if override is not None:
        return dict(override)
    if authorization == "Bearer tok-trade":
        return {"access": "trade", "daily_limit_usd": 250,
                "spent_today_usd": 40.5, "remaining_today_usd": 209.5}
    return {"access": "read_only"}


def _tool_result(payload, *, error=False):
    if isinstance(payload, str):
        content = [{"type": "text", "text": payload}]
    else:
        content = [{"type": "text", "text": json.dumps(payload)}]
    return {"content": content, **({"isError": True} if error else {})}


def _rpc_response(message_id, result):
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


#: Production's schema for a trade amount: a leading digit, no sign or exponent.
SERVER_AMOUNT_RE = re.compile(r"^\d+(\.\d+)?$")


def amount_refusal(tool):
    """The text production sends when its schema refuses ``amount``, verbatim
    (seen in the Hermes pane, 2026-11-09)."""
    issues = [{
        "origin": "string", "code": "invalid_format", "format": "regex",
        "pattern": "/^\\d+(\\.\\d+)?$/", "path": ["amount"],
        "message": 'A decimal number, e.g. "1.5"',
    }]
    return (f"MCP error -32602: Input validation error: Invalid arguments for tool {tool}: "
            + json.dumps(issues, indent=2))


class MockMCPHandler(BaseHTTPRequestHandler):
    server_version = "MockCoinFelloMCP/0.1"

    # state shared across instances via the server object
    @property
    def state(self):
        return self.server.mock_state

    def log_message(self, *args):  # silence the request log
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            message = json.loads(raw)
        except ValueError:
            self._json(400, {"error": "bad json"})
            return

        method = message.get("method", "")
        self.state["user_agents"].append(self.headers.get("User-Agent"))
        if method == "initialize":
            self.state["initialize_calls"] += 1
            self._json(
                200,
                _rpc_response(message.get("id"), {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {"name": "coinfello", "version": "1.0.0"},
                }),
                session_id=self.state["session_id"],
            )
            return

        if method == "notifications/initialized":
            self.state["initialized_notices"] += 1
            self._empty(202)
            return

        # every other method requires the live session id
        if self.headers.get("Mcp-Session-Id") != self.state["session_id"]:
            self._empty(404)
            return

        if method == "tools/call":
            name = (message.get("params") or {}).get("name", "")
            arguments = (message.get("params") or {}).get("arguments") or {}
            self.state["tool_calls"].append((name, arguments))
            self.state["auth_headers"].append(self.headers.get("Authorization"))
            self._handle_tool(message.get("id"), name, arguments)
            return

        if method == "resources/read":
            uri = (message.get("params") or {}).get("uri", "")
            self.state["resource_reads"].append(uri)
            item = {"uri": self.state["resource_uri_override"] or uri,
                    "mimeType": self.state["resource_mime"], "text": CARD_HTML, "_meta": CARD_RESOURCE_META}
            self._json(200, _rpc_response(message.get("id"), {"contents": [item]}))
            return

        if method == "tools/list":
            self.state["list_calls"] += 1
            tools = [{"name": name, "inputSchema": {"type": "object"}} for name in BASE_TOOLS]
            if self.state["access_mode"]:
                for tool in tools:
                    if tool["name"] == "whoami":
                        tool["description"] = (
                            "Shows which CoinFello account and automation wallet the session "
                            "acts as, whether it is read-only or can trade (and its daily "
                            "limit), and when it expires."
                        )
            if self.state["browser_sign_in"]:
                tools += [
                    {"name": name, "inputSchema": {"type": "object"}}
                    for name in ("start_browser_sign_in", "renew_session")
                ]
                if self.state["account_hint"]:
                    for tool in tools:
                        if tool["name"] == "start_browser_sign_in":
                            tool["inputSchema"] = {"type": "object", "properties": {
                                "expected_wallet": {"type": "string"},
                                "expected_email": {"type": "string"}}}
            if self.state["actions"]:
                tools += [{"name": name, "inputSchema": {"type": "object"}} for name in ACTION_TOOLS]
                scopes = self.state["embed_scopes"]
                if self.state["portfolio_embed"]:
                    # coinfello-web /embed/portfolio: scope advertised as an enum.
                    scopes = ("swap",) if scopes is None else scopes
                    scopes = tuple(scopes) + (("portfolio",) if scopes and "portfolio" not in scopes else ())
                if self.state["strategies_embed"]:
                    # coinfello-web /embed/strategies: also in the enum.
                    scopes = ("swap",) if scopes is None else scopes
                    scopes = tuple(scopes) + (("strategies",) if scopes and "strategies" not in scopes else ())
                if scopes is not None:
                    # create_embed_token takes a scope: the Earn and/or the
                    # portfolio embed's server. () = a scope with no enum.
                    scope = {"type": "string"}
                    if scopes:
                        scope["enum"] = list(scopes)
                    for tool in tools:
                        if tool["name"] == "create_embed_token":
                            tool["inputSchema"] = {"type": "object", "properties": {
                                "scope": scope, "session_token": {"type": "string"}}}
            if self.state["limit_mode"]:
                tools += [{"name": name, "inputSchema": {"type": "object"}}
                          for name in ("set_daily_limit", "start_limit_change", "get_limit_change")]
            if self.state["transfer_status"]:
                tools += [{"name": name, "inputSchema": {"type": "object"}} for name in STATUS_TOOLS]
            if self.state["cards"]:
                tools = [{**tool, "inputSchema": CARD_TRADE_SCHEMAS.get(tool["name"], tool["inputSchema"])}
                         for tool in tools] + CARD_TOOLS
            if self.state["activity"]:
                tools.append({"name": "get_activity", "inputSchema": {"type": "object", "properties": {
                    "before": {"type": "string"}, "chain_ids": {"type": "array"},
                    "fills_since_hours": {"type": "integer"}}}})
            self._json(200, _rpc_response(message.get("id"), {"tools": tools}))
            return

        self._json(400, {"error": f"unsupported method {method}"})

    def _limit_tool(self, message_id, name, arguments):
        """Mirrors coinfello-web: the token may only LOWER its own limit; a
        raise is a pending change the human approves in the browser."""
        state, auth = self.state, self.headers.get("Authorization")
        current = _access_for(auth, state)
        cur = current.get("daily_limit_usd") if current["access"] == "trade" else None

        def access(limit):
            return {"access": "read_only"} if limit is None else {
                "access": "trade", "daily_limit_usd": limit,
                "spent_today_usd": 0, "remaining_today_usd": limit}

        if name == "set_daily_limit":
            new = arguments.get("limit_usd")
            if new is not None and (cur is None or new > cur):
                self._json(200, _rpc_response(message_id, _tool_result(
                    "raise_needs_approval: a raise needs the human's approval; "
                    "call start_limit_change.", error=True)))
                return
            state["access_override"][auth] = access(new)
            self._json(200, _rpc_response(message_id, _tool_result(access(new))))
        elif name == "start_limit_change":
            state["limit_changes"]["chg-1"] = {
                "auth": auth, "limit": arguments.get("limit_usd"), "status": "pending"}
            self._json(200, _rpc_response(message_id, _tool_result({
                "approval_url": "https://example.test/authorize/limit?change=chg-1",
                "change_id": "chg-1", "expires_in_seconds": 600,
                "current": {k: v for k, v in current.items() if k in ("access", "daily_limit_usd")},
                "requested": access(arguments.get("limit_usd")),
            })))
        else:  # get_limit_change
            change = state["limit_changes"].get(arguments.get("change_id"))
            if change is None or change["auth"] != auth:
                self._json(200, _rpc_response(message_id, _tool_result({"status": "expired"})))
                return
            if change["status"] == "approved":
                state["access_override"][auth] = access(change["limit"])
                self._json(200, _rpc_response(message_id, _tool_result(
                    {"status": "approved", **access(change["limit"])})))
            else:
                self._json(200, _rpc_response(message_id, _tool_result({"status": change["status"]})))

    def _handle_tool(self, message_id, name, arguments):
        state = self.state
        card = _card_tool(name, arguments, state) if state["cards"] else None
        if card is not None:
            self._json(200, _rpc_response(message_id, card))
            return
        if name == "start_browser_sign_in" and state["browser_sign_in"]:
            self._json(200, _rpc_response(message_id, _tool_result(BROWSER_SIGN_IN)))
            return
        if name == "renew_session" and state["browser_sign_in"]:
            renewed = dict(RENEWED)
            if self.headers.get("Authorization") == "Bearer tok-trade":
                renewed["session_token"] = "tok-trade"  # renewal keeps the access
            self._json(200, _rpc_response(message_id, _tool_result(renewed)))
            return
        if name == "sign_out":
            time.sleep(state["sign_out_delay"])
            state["signed_out_tokens"].append(self.headers.get("Authorization"))
            self._json(200, _rpc_response(message_id, _tool_result("Signed out.")))
            return
        if name in ("set_daily_limit", "start_limit_change", "get_limit_change") and state["limit_mode"]:
            self._limit_tool(message_id, name, arguments)
            return
        browse_only = (name == "create_embed_token" and arguments.get("scope") == "earn"
                       and state["earn_read_only_mint"])
        if (name in ("prepare_send", "prepare_swap", "execute_intent", "create_embed_token")
                and not (name == "create_embed_token" and arguments.get("scope") in ("portfolio", "strategies"))
                and state["access_mode"] and not browse_only
                and _access_for(self.headers.get("Authorization"), state)["access"] == "read_only"):
            state["refused_read_only"].append(name)
            self._json(200, _rpc_response(message_id, _tool_result(
                "This session is read-only, so it cannot move funds. To trade, sign in "
                "again with start_browser_sign_in and choose a daily limit on the "
                "approval page. Email-code sign-in always gives a read-only session.",
                error=True)))
            return
        if (name in ("prepare_send", "prepare_swap", "get_quote") and state["actions"]
                and not SERVER_AMOUNT_RE.match(str(arguments.get("amount", "")))):
            self._json(200, _rpc_response(message_id, _tool_result(amount_refusal(name), error=True)))
            return
        if name == "strict_rpc":
            # An older SDK answers a schema refusal as a JSON-RPC error instead.
            self._json(200, {"jsonrpc": "2.0", "id": message_id, "error": {
                "code": -32602,
                "message": amount_refusal(name).removeprefix("MCP error -32602: "),
            }})
            return
        if name == "prepare_send" and state["actions"]:
            if not str(arguments.get("recipient", "")).startswith("0x"):
                self._json(200, _rpc_response(
                    message_id, _tool_result('recipient must be a 0x address; got "bob".', error=True)))
                return
            self._json(200, _rpc_response(message_id, _tool_result(PREPARED_SEND)))
            return
        if name == "prepare_swap" and state["actions"]:
            self._json(200, _rpc_response(message_id, _tool_result(PREPARED_BRIDGE)))
            return
        if name == "get_transfer_status" and state["transfer_status"]:
            self._json(200, _rpc_response(message_id, _tool_result(TRANSFER_WRONG_TOKEN)))
            return
        if name == "execute_intent" and state["actions"]:
            intent = arguments.get("intent_id")
            if intent in state["used_intents"]:
                self._json(200, _rpc_response(message_id, _tool_result(
                    "This confirmation expired or was already used. Prepare it again.", error=True)))
                return
            state["used_intents"].append(intent)
            if state["outcome_unknown"]:
                self._json(200, _rpc_response(message_id, _tool_result(
                    {"success": False, "kind": "swap", "outcomeUnknown": True,
                     "transactionHash": "0xbroadcast",
                     "error": "The swap was broadcast (tx 0xbroadcast) but its outcome could not be confirmed. Do not retry."},
                    error=True)))
                return
            if state["route_changed"]:
                self._json(200, _rpc_response(message_id, _tool_result(
                    {"success": False, "kind": "bridge", "routeChanged": True,
                     "error": "The approved route went through layerswap, which no longer offers this transfer."},
                    error=True)))
                return
            if state["price_moved"]:
                self._json(200, _rpc_response(message_id, _tool_result(
                    {"success": False, "kind": "swap", "priceMoved": True,
                     "error": "The price moved since this swap was approved."}, error=True)))
                return
            self._json(200, _rpc_response(message_id, _tool_result(
                {"success": True, "kind": "send", "transactionHash": "0xabc123"})))
            return
        if name == "create_embed_token" and state["actions"]:
            if arguments.get("scope") == "portfolio":
                if not state["portfolio_embed"]:
                    self._json(200, _rpc_response(message_id, _tool_result(
                        "scope: Invalid enum value. Expected 'swap'", error=True)))
                    return
                self._json(200, _rpc_response(message_id, _tool_result(
                    dict(EMBED_TOKEN, embed_token="cfemb_portfolio",
                         embed_url="https://app.coinfello.test/embed/portfolio"))))
                return
            if arguments.get("scope") == "strategies":
                if not state["strategies_embed"]:
                    self._json(200, _rpc_response(message_id, _tool_result(
                        "scope: Invalid enum value. Expected 'swap'", error=True)))
                    return
                self._json(200, _rpc_response(message_id, _tool_result(
                    dict(EMBED_TOKEN, embed_token="cfemb_strategies",
                         embed_url="https://app.coinfello.test/embed/strategies"))))
                return
            minted = dict(EMBED_TOKEN)
            if arguments.get("scope") == "earn":
                minted.update(embed_token="cfemb_earn", embed_url="https://app.coinfello.test/embed/earn")
            self._json(200, _rpc_response(message_id, _tool_result(minted)))
            return
        if name == "expire_session":
            state["session_id"] = f"sess-{state['generation'] + 1}"
            state["generation"] += 1
            self._json(200, _rpc_response(message_id, _tool_result("session expired")))
            return
        if name == "privy_send_login_code":
            self._json(200, _rpc_response(message_id, _tool_result(CODE_SENT)))
            return
        if name == "privy_verify_login_code":
            if arguments.get("email") == "approval@example.com":
                self._json(200, _rpc_response(message_id, _tool_result(APPROVAL_REQUIRED)))
            elif arguments.get("code") == "111111":
                self._json(200, _rpc_response(message_id, _tool_result(SESSION)))
            else:
                self._json(
                    200,
                    _rpc_response(
                        message_id,
                        _tool_result("Sign-in failed: wrong code.", error=True),
                    ),
                )
            return
        if name == "privy_complete_approval":
            approval_id = arguments.get("approval_id", "")
            if approval_id.startswith("2222"):  # a browser sign-in
                payload = SESSION if state["browser_approved"] else PENDING
                if state["browser_approved"] and state["access_mode"]:
                    payload = {**SESSION, "session_token": "tok-trade",
                               "access": "trade", "daily_limit_usd": 250}
                self._json(200, _rpc_response(message_id, _tool_result(payload)))
            elif approval_id.startswith("1111"):
                self._json(200, _rpc_response(message_id, _tool_result(PENDING)))
            elif arguments.get("approval_id") == "done-approval":
                self._json(200, _rpc_response(message_id, _tool_result(SESSION)))
            else:
                self._json(
                    200,
                    _rpc_response(message_id, _tool_result("expired approval", error=True)),
                )
            return
        if name == "whoami":
            payload = dict(WHOAMI)
            if state["access_mode"]:
                payload.update(_access_for(self.headers.get("Authorization"), state))
            self._json(200, _rpc_response(message_id, _tool_result(payload)))
            return
        if name == "get_activity":
            page = ACTIVITY_PAGE_2 if arguments.get("before") == "cursor-2" else ACTIVITY_PAGE_1
            self._json(200, _rpc_response(message_id, _tool_result(json.dumps(page))))
            return
        if name == "get_balances":
            if state["sse_mode"]:
                self._sse(message_id, _tool_result(BALANCES_TEXT))
            else:
                self._json(200, _rpc_response(message_id, _tool_result(BALANCES_TEXT)))
            return
        if name == "boom":
            self._json(
                200,
                _rpc_response(message_id, _tool_result("boom failed", error=True)),
            )
            return
        self._json(
            200,
            _rpc_response(message_id, _tool_result(f"unknown tool {name}", error=True)),
        )

    # -- responders ------------------------------------------------------------

    def _json(self, status, payload, session_id=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if session_id:
            self.send_header("Mcp-Session-Id", session_id)
        self.end_headers()
        self.wfile.write(body)

    def _sse(self, message_id, result):
        event = (
            "event: message\n"
            f"data: {json.dumps(_rpc_response(message_id, result))}\n\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(event)))
        self.end_headers()
        self.wfile.write(event)

    def _empty(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


@pytest.fixture
def mock_mcp(monkeypatch):
    """A live mock MCP server on a random port; yields its base URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockMCPHandler)
    server.mock_state = {
        "session_id": "sess-1",
        "generation": 1,
        "initialize_calls": 0,
        "initialized_notices": 0,
        "tool_calls": [],
        "auth_headers": [],
        "user_agents": [],
        "list_calls": 0,
        "sse_mode": False,
        # Servers deployed before browser sign-in offer neither of its tools;
        # tests opt in to the new server shape.
        "browser_sign_in": False,
        "browser_approved": False,
        # tokens are read-only unless minted with trade
        # access ("tok-trade" here); whoami and refusals follow the token.
        "access_mode": False,
        "refused_read_only": [],
        # Adjustable limits (the follow-up to access levels): off = servers without them.
        "limit_mode": False,
        # start_browser_sign_in advertises expected_wallet / expected_email.
        "account_hint": False,
        "access_override": {},
        "limit_changes": {},
        "sign_out_delay": 0.0,
        "signed_out_tokens": [],
        # Older servers have no send/swap/embed tools.
        "actions": False,
        "portfolio_embed": False,
        "strategies_embed": False,
        "used_intents": [],
        "price_moved": False,
        "route_changed": False,
        "outcome_unknown": False,
        # The Earn embed: None = create_embed_token without `scope` (production
        # before it ships); a list = `scope` with that enum; () = no enum.
        "embed_scopes": None,
        # The server mints Earn tokens for read-only sessions (browse only).
        "earn_read_only_mint": False,
        "transfer_status": False,
        # MCP App cards: show_*_card tools with _meta.ui and resources/read.
        "cards": False,
        # yield rows with Deposit, an earn card by yield_id.
        "earn_flow": False,
        "resource_reads": [],
        "resource_mime": CARD_MIME,
        "resource_uri_override": "",
        "activity": False,
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    """Force the file fallback for state storage, in a temp directory."""
    import coinfello_core
    import coinfello_state

    fallback = tmp_path / "state.json"
    monkeypatch.setattr(coinfello_state, "FALLBACK_FILE", fallback)
    monkeypatch.setattr(coinfello_state, "_auth_helpers", lambda: None)
    # Capability probes are cached per process; every test starts cold.
    coinfello_core._capabilities.update(url=None, tools=frozenset(), at=0.0)
    yield fallback