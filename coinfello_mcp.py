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
import urllib.parse
import urllib.request

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "hermes-coinfello-plugin", "version": "0.1.0"}


#: The only MCP App resources the plugin renders: CoinFello's own cards.
CARD_URI_PREFIX = "ui://coinfello/"
#: MCP Apps (SEP-1865) HTML resource type.
CARD_MIME = "text/html;profile=mcp-app"


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


def is_card_mime(value) -> bool:
    """``text/html;profile=mcp-app``, ignoring case and spacing."""
    return isinstance(value, str) and value.replace(" ", "").lower() == CARD_MIME


def result_text(result: dict) -> str:
    """The text blocks of a CallToolResult, joined."""
    content = (result or {}).get("content") or []
    return "\n".join(
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


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
            # Our own name, not Python-urllib's: coinfello-web remembers per
            # user-agent whether a client renders MCP App cards, and must not
            # mistake this plugin for another Python client that does.
            "User-Agent": f"{CLIENT_INFO['name']}/{CLIENT_INFO['version']}",
        }
        if self.session_token:
            headers["Authorization"] = f"Bearer {self.session_token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, payload: dict) -> tuple[int, dict, bytes]:
        body = json.dumps(payload).encode("utf-8")
        for _hop in range(3):
            request = urllib.request.Request(
                self.url, data=body, headers=self._headers(), method="POST"
            )
            try:
                response = urllib.request.urlopen(request, timeout=self.timeout)
            except urllib.error.HTTPError as error:
                target = self._same_host_redirect(error)
                if target:
                    # 307/308 keep the method and body. The server moved the
                    # endpoint (CoinFello's /api/mcp/mcp -> /api/mcp, a 308):
                    # follow it, and remember it for every later call.
                    self.url = target
                    continue
                return error.code, dict(error.headers or {}), error.read() or b""
            except (urllib.error.URLError, OSError, TimeoutError) as error:
                raise MCPError(f"could not reach {self.url}: {error}") from error
            return response.status, dict(response.headers), response.read() or b""
        raise MCPError(f"too many redirects from {self.url}")

    def _same_host_redirect(self, error: urllib.error.HTTPError) -> str | None:
        """The 307/308 target, only on the same scheme and host: the request
        carries the session's bearer token, which must never follow a
        redirect to another site."""
        if error.code not in (307, 308):
            return None
        location = (error.headers or {}).get("Location")
        if not location:
            return None
        target = urllib.parse.urljoin(self.url, location)
        here, there = urllib.parse.urlsplit(self.url), urllib.parse.urlsplit(target)
        if (here.scheme, here.netloc) != (there.scheme, there.netloc):
            return None
        return target.rstrip("/")

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
                    # Deliberately NOT advertising the MCP Apps extension
                    # (io.modelcontextprotocol/ui): a server that sees it
                    # sends card tools a headline instead of the full text,
                    # and one plugin process serves desktop (card on screen)
                    # and Telegram/CLI (no card) alike. Card results always
                    # carry structuredContent, which is all the card needs.
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

    def call_tool_result(self, name: str, arguments: dict | None = None, *, _retry: bool = True) -> dict:
        """Call a tool; returns the raw CallToolResult (``content``,
        ``structuredContent``, ``isError``), without raising on ``isError``.

        MCP App cards need the result exactly as the server sent it: the card
        renders ``structuredContent`` and handles its own tool errors.
        """
        self.ensure_initialized()
        try:
            message = self._rpc("tools/call", {"name": name, "arguments": dict(arguments or {})})
        except SessionExpired:
            if not _retry:
                raise
            self.initialize()
            return self.call_tool_result(name, arguments, _retry=False)
        if message is None:
            raise MCPError(f"{name}: no response from server")
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def call_tool(self, name: str, arguments: dict | None = None, *, _retry: bool = True):
        """Call a tool; returns the parsed JSON payload, or the plain text."""
        result = self.call_tool_result(name, arguments, _retry=_retry)
        text = result_text(result)
        if result.get("isError"):
            raise ToolError(text or f"{name}: tool reported an error without detail")
        if not text:
            return {}
        try:
            return json.loads(text)
        except ValueError:
            return text

    def read_resource(self, uri: str) -> dict:
        """Read one CoinFello MCP App card document (``resources/read``).

        Only ``ui://coinfello/`` URIs, and only the MCP Apps HTML type: this
        is the one kind of resource the plugin renders, and anything else
        (another server's card, a plain web page) is refused before it could
        reach a frame. Returns ``{"uri", "text", "_meta"}``.
        """
        if not isinstance(uri, str) or not uri.startswith(CARD_URI_PREFIX) or ".." in uri:
            raise MCPError(f"refusing to read {uri!r}: only {CARD_URI_PREFIX} cards are rendered")
        self.ensure_initialized()
        try:
            message = self._rpc("resources/read", {"uri": uri})
        except SessionExpired:
            self.initialize()
            message = self._rpc("resources/read", {"uri": uri})
        contents = ((message or {}).get("result") or {}).get("contents") or []
        for item in contents:
            if not isinstance(item, dict) or item.get("uri") != uri:
                continue
            if not is_card_mime(item.get("mimeType")):
                raise MCPError(f"{uri} is {item.get('mimeType')!r}, not an MCP App card")
            text = item.get("text")
            if not isinstance(text, str) or not text.strip():
                raise MCPError(f"{uri} has no HTML")
            meta = item.get("_meta")
            return {"uri": uri, "text": text, "_meta": meta if isinstance(meta, dict) else {}}
        raise MCPError(f"{uri}: the server returned no card document")
