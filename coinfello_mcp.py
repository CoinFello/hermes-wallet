"""Minimal MCP streamable-HTTP client for the CoinFello MCP server.

Stdlib only. Both the agent tools and the dashboard API run inside Hermes
processes, so this client deliberately speaks just enough JSON-RPC 2.0 over
the streamable-HTTP transport to initialize a session and call tools,
tolerating both ``application/json`` and ``text/event-stream`` responses
(the spec allows the server to answer either way).
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "hermes-coinfello-plugin", "version": "0.1.0"}


class MCPError(Exception):
    """Transport- or protocol-level failure (unreachable, bad response)."""


class ToolError(MCPError):
    """The tool ran and reported an error (its text is the message)."""


class SessionExpired(MCPError):
    """The server dropped our MCP session (HTTP 404); caller may re-init."""


def _header(headers: dict, name: str) -> str | None:
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return value
    return None


def _parse_sse(text: str) -> list:
    """Every SSE ``data:`` payload that parses as JSON, in stream order."""
    messages: list = []
    for event in text.replace("\r\n", "\n").split("\n\n"):
        data_lines = [
            line[5:].lstrip() for line in event.split("\n") if line.startswith("data:")
        ]
        if not data_lines:
            continue
        try:
            messages.append(json.loads("\n".join(data_lines)))
        except ValueError:
            continue
    return messages


def _select(payload, want_id):
    """The JSON-RPC response carrying ``want_id`` (or the only response there is)."""
    if payload is None:
        return None
    items = payload if isinstance(payload, list) else [payload]
    fallback = None
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("id") == want_id and ("result" in item or "error" in item):
            return item
        if fallback is None and ("result" in item or "error" in item):
            fallback = item
    return fallback


class CoinFelloMCP:
    """A lazy, thread-safe streamable-HTTP MCP client for one CoinFello session."""

    def __init__(self, url: str, session_token: str | None = None, timeout: float = 90.0):
        self.url = str(url).rstrip("/")
        self.session_token = session_token
        self.timeout = timeout
        self._session_id: str | None = None
        self._initialized = False
        self._next_id = 0
        self._lock = threading.RLock()

    # -- low level -----------------------------------------------------------

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_token:
            headers["Authorization"] = f"Bearer {self.session_token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, payload: dict) -> tuple[int, dict, bytes]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.url, data=body, headers=self._headers(), method="POST"
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers or {}), error.read() or b""
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise MCPError(f"could not reach {self.url}: {error}") from error
        return response.status, dict(response.headers), response.read() or b""

    def _parse_message(self, body: bytes, want_id):
        text = body.decode("utf-8", "replace").strip()
        if not text:
            return None
        try:
            payload = json.loads(text)
        except ValueError:
            payload = _parse_sse(text)
        return _select(payload, want_id)

    @staticmethod
    def _raise_rpc_error(message: dict, context: str):
        error = message.get("error") or {}
        raise MCPError(f"{context}: {error.get('message') or error}")

    # -- protocol ------------------------------------------------------------

    def initialize(self) -> dict:
        """Negotiate a fresh MCP session, discarding any previous one."""
        with self._lock:
            self._session_id = None
            self._initialized = False
            self._next_id += 1
            request_id = self._next_id
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            }
            status, headers, body = self._post(payload)
            if status != 200:
                raise MCPError(f"MCP initialize failed with HTTP {status} at {self.url}")
            message = self._parse_message(body, request_id)
            if message is None:
                raise MCPError("MCP initialize returned no response")
            if "error" in message:
                self._raise_rpc_error(message, "MCP initialize failed")
            session_id = _header(headers, "Mcp-Session-Id")
            if session_id:
                self._session_id = session_id
            self._notify_initialized()
            self._initialized = True
            return message.get("result") or {}

    def _notify_initialized(self):
        payload = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        status, _headers, _body = self._post(payload)
        if status not in (200, 202):
            raise MCPError(f"MCP initialized notification failed with HTTP {status}")

    def ensure_initialized(self):
        if not self._initialized:
            self.initialize()

    def _rpc(self, method: str, params: dict | None = None) -> dict | None:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
            if params is not None:
                payload["params"] = params
            status, _headers, body = self._post(payload)
            if status == 404:
                self._initialized = False
                raise SessionExpired("MCP session expired (HTTP 404)")
            if status != 200:
                raise MCPError(f"{method} failed with HTTP {status}")
            message = self._parse_message(body, request_id)
            if message is not None and "error" in message:
                self._raise_rpc_error(message, method)
            return message

    # -- public API ----------------------------------------------------------

    def list_tools(self) -> list:
        self.ensure_initialized()
        try:
            message = self._rpc("tools/list")
        except SessionExpired:
            self.initialize()
            message = self._rpc("tools/list")
        result = (message or {}).get("result") or {}
        return result.get("tools") or []

    def call_tool(self, name: str, arguments: dict | None = None, *, _retry: bool = True):
        """Call a tool; returns the parsed JSON payload, or the plain text."""
        self.ensure_initialized()
        try:
            message = self._rpc("tools/call", {"name": name, "arguments": dict(arguments or {})})
        except SessionExpired:
            if not _retry:
                raise
            self.initialize()
            return self.call_tool(name, arguments, _retry=False)
        if message is None:
            raise MCPError(f"{name}: no response from server")
        result = message.get("result") or {}
        content = result.get("content") or []
        text = "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if result.get("isError"):
            raise ToolError(text or f"{name}: tool reported an error without detail")
        if not text:
            return {}
        try:
            return json.loads(text)
        except ValueError:
            return text