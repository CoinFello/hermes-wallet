"""Shared service layer for the CoinFello plugin.

Everything the agent tools and the dashboard/desktop API do goes through
here: sign-in (browser-first, with the email-code flow as a fallback for
servers that predate it), keeping the session renewed, the status read, the
pane's wallet and portfolio models, and pass-through MCP tool calls for the
``get_*`` reads and ``fello_chat``. Raises typed exceptions; callers format
them.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

try:  # package import inside Hermes; plain import in tests / standalone use
    from .coinfello_mcp import CoinFelloMCP, MCPError, ToolError, result_text  # noqa: F401 (re-exported)
    from .coinfello_activity import shape_activity, venue_jobs
    from . import coinfello_venues
    from .coinfello_portfolio import qr_svg_data_uri, shape_portfolio
    from .coinfello_state import (
        clear_state, forget_account_hint, load_state, mcp_url, save_state, signed_in)
except ImportError:  # pragma: no cover
    from coinfello_mcp import CoinFelloMCP, MCPError, ToolError, result_text  # type: ignore[no-redef]
    from coinfello_activity import shape_activity, venue_jobs  # type: ignore[no-redef]
    import coinfello_venues  # type: ignore[no-redef]
    from coinfello_portfolio import qr_svg_data_uri, shape_portfolio  # type: ignore[no-redef]
    from coinfello_state import (  # type: ignore[no-redef]
        clear_state, forget_account_hint, load_state, mcp_url, save_state, signed_in)

#: Renew once the session has less than this left (the server issues 30 days).
RENEW_WITHIN_SECONDS = 14 * 24 * 60 * 60
#: After a failed renewal attempt, wait this long before trying again.
RENEW_RETRY_SECONDS = 60 * 60
#: How long a server capability probe (tools/list) is trusted.
CAPABILITY_TTL_SECONDS = 10 * 60

_capabilities: dict[str, Any] = {"url": None, "tools": frozenset(), "at": 0.0}


class NotSignedIn(Exception):
    """Raised when an action needs a CoinFello session and none is stored."""


class NeedsTradingAccess(Exception):
    """The session is read-only: it can read and quote,
    but the server refuses anything that moves funds."""

    MESSAGE = (
        "This CoinFello session is read-only, so it cannot move funds. Nothing "
        "was sent. To trade, ask the human for a daily limit and call "
        "coinfello_set_daily_limit (they approve it in their browser, same "
        "session); on servers without it, call coinfello_connect for a new "
        "browser sign-in. Send the returned user_message exactly as written."
    )

    def __init__(self) -> None:
        super().__init__(self.MESSAGE)


def _is_read_only_refusal(exc: Exception) -> bool:
    text = str(exc).lower()
    return "read-only" in text or "read only" in text


def trading_call(name: str, payload: dict | None = None, *, timeout: float = 90.0,
                 refuse_locally: bool = True):
    """``call`` for the tools that move funds: refuses up front when the
    session is known read-only, and turns the server's read-only refusal into
    NeedsTradingAccess, so callers get one clear next step either way.

    ``refuse_locally=False`` always asks the server, for a call it may allow
    a read-only session (the Earn embed, which can be browsed)."""
    if refuse_locally and load_state().get("access") == "read_only":
        raise NeedsTradingAccess()
    try:
        return call(name, payload, timeout=timeout)
    except ToolError as exc:
        if _is_read_only_refusal(exc):
            save_state({"access": "read_only", "daily_limit_usd": None})
            raise NeedsTradingAccess() from exc
        raise


def _text(result) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("message", "text", "reply", "next"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return str(result)


def _client(state: dict | None = None, timeout: float = 90.0) -> CoinFelloMCP:
    state = state if state is not None else load_state()
    return CoinFelloMCP(
        mcp_url(),
        session_token=(state.get("session_token") or "").strip() or None,
        timeout=timeout,
    )


# -- server capabilities -----------------------------------------------------

def server_tools(*, refresh: bool = False) -> frozenset:
    """Tool names the configured server offers (cached; probes on miss)."""
    url = mcp_url()
    fresh = (
        _capabilities["url"] == url
        and time.monotonic() - _capabilities["at"] < CAPABILITY_TTL_SECONDS
    )
    if refresh or not fresh:
        tools = _client(timeout=20.0).list_tools()
        names = frozenset(tool.get("name", "") for tool in tools)
        descriptions = {tool.get("name", ""): tool.get("description") or "" for tool in tools}
        properties = {tool.get("name", ""): _properties(tool) for tool in tools}
        params = {name: frozenset(props) for name, props in properties.items()}
        required = {tool.get("name", ""): _required_params(tool) for tool in tools}
        card_uris = {
            tool.get("name", ""): uri for tool in tools if (uri := _card_resource_uri(tool))
        }
        enums = {
            tool.get("name", ""): {
                param: frozenset(str(v) for v in spec["enum"])
                for param, spec in (((tool.get("inputSchema") or {}).get("properties") or {}).items())
                if isinstance(spec, dict) and isinstance(spec.get("enum"), list)
            }
            for tool in tools
        }
        _capabilities.update(
            url=url, tools=names, descriptions=descriptions, params=params,
            properties=properties, required=required, card_uris=card_uris, enums=enums,
            at=time.monotonic(),
        )
    return _capabilities["tools"]


def _properties(tool: dict) -> dict:
    """The schema's ``properties``: name -> its own schema."""
    schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    return {name: spec if isinstance(spec, dict) else {} for name, spec in properties.items()}


def _required_params(tool: dict) -> tuple:
    """The schema's ``required`` names, in the server's order."""
    schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {}
    required = schema.get("required")
    if not isinstance(required, list):
        return ()
    return tuple(name for name in required if isinstance(name, str))


def _card_resource_uri(tool: dict) -> str:
    """The MCP App card a tool renders into: ``_meta.ui.resourceUri`` (the
    MCP Apps key), else the deprecated flat ``_meta["ui/resourceUri"]``."""
    meta = tool.get("_meta") if isinstance(tool.get("_meta"), dict) else {}
    ui = meta.get("ui") if isinstance(meta.get("ui"), dict) else {}
    uri = ui.get("resourceUri") or meta.get("ui/resourceUri")
    return uri if isinstance(uri, str) else ""


def card_resource_uri(tool: str) -> str:
    """The card URI the server declared for ``tool`` ("" when none)."""
    try:
        server_tools()
    except MCPError:
        return ""
    return (_capabilities.get("card_uris") or {}).get(tool, "")


def tool_params(tool: str) -> frozenset:
    """The argument names the server's schema declares for ``tool``."""
    try:
        server_tools()
    except MCPError:
        return frozenset()
    return (_capabilities.get("params") or {}).get(tool, frozenset())


def tool_required(tool: str) -> tuple:
    """The argument names the server's schema for ``tool`` requires."""
    try:
        server_tools()
    except MCPError:
        return ()
    return (_capabilities.get("required") or {}).get(tool, ())


def supports(tool: str) -> bool:
    try:
        return tool in server_tools()
    except MCPError:
        return False


def accepts_param(tool: str, param: str) -> bool:
    """True when the server's schema for ``tool`` declares ``param``; never
    send an argument an older server has not advertised."""
    try:
        server_tools()
    except MCPError:
        return False
    return param in (_capabilities.get("params") or {}).get(tool, frozenset())


def accepts_value(tool: str, param: str, value: str) -> bool:
    """True when the server's schema lists ``value`` in ``param``'s enum
    (e.g. create_embed_token's scope); a value an older server never
    advertised is treated as unsupported."""
    try:
        server_tools()
    except MCPError:
        return False
    return value in ((_capabilities.get("enums") or {}).get(tool) or {}).get(param, frozenset())


def mask_email(value: str) -> str:
    """j…@example.com: enough to recognize your account on screen."""
    if "@" not in (value or ""):
        return value or ""
    name, domain = value.split("@", 1)
    return f"{name[:1]}…@{domain}"


def account_hint() -> dict:
    """The account this plugin last used (non-secret), for the next sign-in."""
    state = load_state()
    return {
        "email": state.get("last_signed_in_as") or "",
        "wallet": state.get("last_wallet_address") or "",
    }


def offers_access_choice() -> bool:
    """True on servers where a session is read-only unless the human picks a
    daily trading limit at browser sign-in. Detected
    from whoami's own description, so older servers keep the old flow."""
    try:
        server_tools()
    except MCPError:
        return False
    whoami = (_capabilities.get("descriptions") or {}).get("whoami", "")
    return "read-only" in whoami.lower()


def sign_in_mode() -> str:
    """``browser`` on servers with browser sign-in, else ``email``."""
    return "browser" if supports("start_browser_sign_in") else "email"


def app_url(path: str = "/") -> str:
    """A CoinFello web-app URL on the same deployment as the MCP endpoint."""
    parts = urlsplit(mcp_url())
    return f"{parts.scheme}://{parts.netloc}{path}"


# -- session use + renewal ---------------------------------------------------

def _seconds_left(expires_at: str) -> float | None:
    try:
        when = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return (when - datetime.now(timezone.utc)).total_seconds()


def maybe_renew(state: dict | None = None) -> dict:
    """Renew the stored session when it nears expiry; returns current state.

    Never raises: a failed renewal leaves the (still valid) session in place
    and is retried after ``RENEW_RETRY_SECONDS``.
    """
    state = state if state is not None else load_state()
    if not signed_in(state):
        return state
    left = _seconds_left(state.get("expires_at") or "")
    if left is None or left > RENEW_WITHIN_SECONDS:
        return state
    last_attempt = float(state.get("renew_attempted_at") or 0)
    if time.time() - last_attempt < RENEW_RETRY_SECONDS:
        return state
    if not supports("renew_session"):
        return state
    try:
        result = _client(state, timeout=20.0).call_tool("renew_session", {})
    except MCPError:
        return save_state({"renew_attempted_at": time.time()})
    if isinstance(result, dict) and result.get("session_token"):
        return save_state(
            {
                "session_token": result["session_token"],
                "wallet_address": result.get("wallet_address") or state.get("wallet_address") or "",
                "expires_at": result.get("expires_at") or "",
                "renew_attempted_at": 0,
            }
        )
    return save_state({"renew_attempted_at": time.time()})


def _resolve_token(args: dict) -> str:
    """An explicit session_token argument wins; otherwise the stored one."""
    explicit = str((args or {}).get("session_token") or "").strip()
    if explicit:
        return explicit
    stored = (maybe_renew().get("session_token") or "").strip()
    if not stored:
        raise NotSignedIn(
            "call coinfello_connect to start a browser sign-in, then "
            "coinfello_poll_approval once the human has approved"
        )
    return stored


def call(name: str, payload: dict | None = None, *, timeout: float = 90.0):
    """Call any MCP tool with the stored (or explicit) session attached."""
    payload = dict(payload or {})
    token = _resolve_token(payload)
    payload.pop("session_token", None)
    client = _client(timeout=timeout)
    client.session_token = token
    return client.call_tool(name, payload)


def call_result(name: str, payload: dict | None = None, *, timeout: float = 90.0) -> dict:
    """``call``, returning the raw CallToolResult (no raise on ``isError``).

    For MCP App cards, which render the result exactly as the server sent it.
    Always the stored session: a card never supplies a token.
    """
    payload = {k: v for k, v in dict(payload or {}).items() if k != "session_token"}
    token = _resolve_token({})
    client = _client(timeout=timeout)
    client.session_token = token
    return client.call_tool_result(name, payload)


def trading_call_result(name: str, payload: dict | None = None, *, timeout: float = 90.0) -> dict:
    """``trading_call`` for card relays: the same read-only handling, raw result."""
    if load_state().get("access") == "read_only":
        raise NeedsTradingAccess()
    result = call_result(name, payload, timeout=timeout)
    if result.get("isError") and _is_read_only_refusal(Exception(result_text(result))):
        save_state({"access": "read_only", "daily_limit_usd": None})
        raise NeedsTradingAccess()
    return result


def read_card_resource(uri: str) -> dict:
    """One ``ui://coinfello/`` card document (see ``CoinFelloMCP.read_resource``)."""
    client = _client(timeout=20.0)
    client.session_token = (maybe_renew().get("session_token") or "").strip() or None
    return client.read_resource(uri)


# -- sign-in -----------------------------------------------------------------

def sign_in_steps(code: str, url: str, *, upgrade: bool = False) -> list[str]:
    """The approval page's steps, in the order it asks for them.

    One source for the pane and the agent: the agent relays ``user_message``
    verbatim rather than paraphrasing, because a paraphrase put the code
    before the CoinFello login and the login then looked like a mistake.
    """
    steps = [
        f"Open {url} in your regular web browser (if you're already signed in "
        "to CoinFello there, the next step is skipped).",
        _sign_in_step(),
        f"When the page asks for your agent's code, type: {code}",
    ]
    if offers_access_choice():
        adjustable = can_adjust_limit()
        steps.append(
            "Choose what your agent may do: Read only, or trade up to a daily "
            + ("limit ($50, $250, $1,000, or a custom amount)." if adjustable
               else "limit ($50, $250 or $1,000).")
            + (" Pick a daily limit, since you're enabling trading." if upgrade else "")
            + (" You can change it later from the CoinFello pane in Hermes, "
               "without signing in again." if adjustable else "")
        )
    steps.append("Approve. Hermes picks up the sign-in on its own; nothing to paste back.")
    return steps


def _sign_in_step() -> str:
    hint = account_hint()
    who = (
        f"the CoinFello account you use in Hermes ({mask_email(hint['email'])})"
        if hint["email"] and "@" in hint["email"]
        else "your CoinFello account"
    )
    return (
        f"Sign in to {who} with your email or phone. If the browser asks you to "
        "sign in or sign a message with a wallet extension such as MetaMask, "
        "cancel it: that is a different account. This is not where the code goes."
    )


def _sign_in_message(code: str, url: str, *, upgrade: bool) -> str:
    lead = (
        "Your CoinFello session is read-only. To let me trade, sign in again "
        "and choose a daily limit:"
        if upgrade
        else "To connect CoinFello:"
    )
    numbered = "\n".join(f"{i}. {step}" for i, step in enumerate(sign_in_steps(code, url, upgrade=upgrade), 1))
    return f"{lead}\n{numbered}\nThe code expires in 10 minutes."

def _access_fields(result: dict) -> dict:
    """The session's access as the server reports it (whoami / sign-in result).
    Absent on older servers, whose sessions could always trade."""
    if "access" not in result:
        return {}
    access = result.get("access")
    return {
        "access": access,
        "daily_limit_usd": result.get("daily_limit_usd") if access == "trade" else None,
    }


def _store_session(result: dict, **extra) -> dict:
    previous = (load_state().get("session_token") or "").strip()
    state = save_state(
        {
            "session_token": result["session_token"],
            "wallet_address": result.get("wallet_address") or "",
            "expires_at": result.get("expires_at") or "",
            # Who approved the sign-in (email, else phone). Whoever approves
            # the browser link is who the plugin now acts as, so it is shown.
            "signed_in_as": result.get("signed_in_as") or "",
            "access": None,
            "daily_limit_usd": None,
            **_access_fields(result),
            "pending_approval_id": "",
            "pending_user_code": "",
            "pending_approval_url": "",
            "pending_upgrade": False,
            "renew_attempted_at": 0,
            **extra,
        }
    )
    # An upgrade (read-only -> trading) replaces a live session: end the old
    # one server-side so a read-only token is not left valid for 30 days.
    if previous and previous != result["session_token"]:
        threading.Thread(
            target=_revoke_on_server, args=(previous,), name="coinfello-replace", daemon=True
        ).start()
    return state


def start_browser_sign_in() -> dict:
    """Browser-first sign-in: one approval in a browser, no email code."""
    if not supports("start_browser_sign_in"):
        raise RuntimeError(
            "this CoinFello server does not offer browser sign-in yet; "
            "sign in with an email code instead (coinfello_connect with email)"
        )
    hint = account_hint()
    args: dict[str, Any] = {}
    if hint["wallet"] and accepts_param("start_browser_sign_in", "expected_wallet"):
        args["expected_wallet"] = hint["wallet"]
    if hint["email"] and "@" in hint["email"] and accepts_param("start_browser_sign_in", "expected_email"):
        args["expected_email"] = hint["email"]
    result = _client().call_tool("start_browser_sign_in", args)
    if not isinstance(result, dict) or not result.get("approval_url"):
        raise RuntimeError(_text(result))
    upgrade = signed_in()
    code = result.get("user_code") or ""
    save_state(
        {
            "pending_approval_id": result.get("approval_id") or "",
            "pending_user_code": code,
            "pending_approval_url": result["approval_url"],
            "pending_upgrade": upgrade,
        }
    )
    return {
        "ok": True,
        "status": "approval_required",
        "approval_url": result["approval_url"],
        "user_code": code,
        "approval_id": result.get("approval_id") or "",
        "expires_in_seconds": result.get("expires_in_seconds"),
        "upgrade": upgrade,
        "steps": sign_in_steps(code, result["approval_url"], upgrade=upgrade),
        "user_message": _sign_in_message(code, result["approval_url"], upgrade=upgrade),
        "next": (
            "Send user_message to the human exactly as written (the steps are "
            "in the order the page asks for them; do not reorder or shorten "
            "them, and do not open the link yourself or in an in-app preview). "
            "Then call coinfello_poll_approval every 5-10 seconds."
        ),
    }


def connect(email: str = "") -> dict:
    """Start signing in. Browser-first when the server supports it (``email``
    is then ignored); otherwise email a Privy login code."""
    email = str(email or "").strip()
    if sign_in_mode() == "browser":
        return start_browser_sign_in()
    if not email or "@" not in email:
        raise ValueError(
            "this CoinFello server only supports email sign-in: a valid email "
            "address is required"
        )
    save_state({"email": email})
    result = _client().call_tool("privy_send_login_code", {"email": email})
    return {"ok": True, "status": "code_sent", "email": email, "message": _text(result)}


def verify(email: str, code: str) -> dict:
    """Email flow, step 2: exchange the code for a session, or the approval step."""
    email = str(email or "").strip()
    code = str(code or "").strip()
    if not (code.isdigit() and len(code) == 6):
        raise ValueError("the login code is 6 digits")
    result = _client().call_tool(
        "privy_verify_login_code", {"email": email, "code": code}
    )
    if not isinstance(result, dict):
        result = {"text": str(result)}
    if result.get("session_token"):
        state = _store_session(result, email=email)
        return {
            "ok": True,
            "status": "signed_in",
            "wallet_address": state.get("wallet_address") or "",
            "expires_at": state.get("expires_at") or "",
            "message": _text(result),
        }
    if result.get("approval_required"):
        save_state(
            {
                "email": email,
                "pending_approval_id": result.get("approval_id") or "",
                "pending_approval_url": result.get("approval_url") or "",
                "session_token": "",
                "wallet_address": "",
                "expires_at": "",
            }
        )
        return {
            "ok": True,
            "status": "approval_required",
            "approval_url": result.get("approval_url") or "",
            "approval_id": result.get("approval_id") or "",
            "expires_in_seconds": result.get("expires_in_seconds"),
            "message": _text(result),
        }
    # The server refused with human-readable guidance (not linked, not
    # delegated, ...) — surface it verbatim.
    raise RuntimeError(_text(result))


def poll_approval(approval_id: str | None = None) -> dict:
    """Finish an approval-link sign-in (browser-first, or email + approval)."""
    approval_id = str(approval_id or load_state().get("pending_approval_id") or "").strip()
    if not approval_id:
        raise ValueError("no pending approval — start again from coinfello_connect")
    result = _client().call_tool("privy_complete_approval", {"approval_id": approval_id})
    if not isinstance(result, dict):
        result = {"text": str(result)}
    if result.get("status") == "pending":
        return {"ok": True, "status": "pending"}
    if result.get("session_token"):
        state = _store_session(result)
        out = {
            "ok": True,
            "status": "signed_in",
            "wallet_address": state.get("wallet_address") or "",
            "signed_in_as": state.get("signed_in_as") or "",
            "expires_at": state.get("expires_at") or "",
            **_access_summary(state),
        }
        out["user_message"] = _signed_in_message(out)
        return out
    raise RuntimeError(_text(result))


def _access_summary(state: dict) -> dict:
    """``access`` / ``can_trade`` / ``daily_limit_usd`` for status and results.
    No access field means an older server, where any session traded."""
    access = state.get("access")
    if not access:
        return {"access": "unknown", "can_trade": True}
    return {
        "access": access,
        "can_trade": access == "trade",
        "daily_limit_usd": state.get("daily_limit_usd"),
    }


def _signed_in_message(result: dict) -> str:
    who = result.get("signed_in_as") or result.get("wallet_address") or "your account"
    if result.get("access") == "read_only":
        what = (
            "The session is read-only: I can read balances and quote trades but "
            "not move funds. To trade, ask me to enable trading."
        )
    elif result.get("access") == "trade":
        what = f"I can trade up to ${result.get('daily_limit_usd')} a day, each trade after you approve it."
    else:
        what = ""
    return f"Signed in to CoinFello as {who}. {what} If that's not your account, sign out now.".replace("  ", " ")


def cancel_sign_in() -> dict:
    """Forget a pending approval (the link simply expires server-side)."""
    save_state(
        {
            "pending_approval_id": "",
            "pending_user_code": "",
            "pending_approval_url": "",
            "pending_upgrade": False,
        }
    )
    return {"ok": True}


def _revoke_on_server(token: str, *, attempts: int = 3) -> str | None:
    """Sign the session out server-side; returns the last error, or None."""
    client = CoinFelloMCP(mcp_url(), session_token=token, timeout=20.0)
    error: str | None = None
    for attempt in range(attempts):
        try:
            client.call_tool("sign_out", {})
            return None
        except ToolError as exc:
            return str(exc)  # the server answered (e.g. already signed out): no retry
        except MCPError as exc:
            error = str(exc)
            time.sleep(2 ** attempt)
    return error


def disconnect(*, wait: bool = True) -> dict:
    """Forget the session locally at once, and revoke it server-side.

    ``wait=False`` (the pane) returns as soon as the local session is gone and
    revokes in a background thread with retries: signing out is instant for
    the user, and the token is already unusable from here. ``wait=True`` (the
    agent tool) reports the server's answer.
    """
    token = (load_state().get("session_token") or "").strip()
    clear_state()
    result: dict[str, Any] = {"ok": True, "signed_out": True}
    if not token:
        return result
    if not wait:
        threading.Thread(
            target=_revoke_on_server, args=(token,), name="coinfello-sign-out", daemon=True
        ).start()
        return result
    error = _revoke_on_server(token)
    if error:
        result["warning"] = (
            "the local session was cleared, but the server sign-out failed: " + error
        )
    return result


def param_enum(tool: str, param: str) -> tuple | None:
    """The values the server's schema allows for ``param`` (None when the
    schema names no ``enum``, so any value it validates is allowed)."""
    try:
        server_tools()
    except MCPError:
        return None
    spec = ((_capabilities.get("properties") or {}).get(tool) or {}).get(param) or {}
    values = spec.get("enum")
    return tuple(values) if isinstance(values, list) else None


# -- status + pane models ----------------------------------------------------

def status(*, live: bool = True) -> dict:
    """Connection state for the pane and the agent. Never leaks the token."""
    state = maybe_renew() if live else load_state()
    summary: dict[str, Any] = {
        "endpoint": mcp_url(),
        "app_url": app_url("/"),
        "email": state.get("email") or "",
        "connected": False,
    }
    if not signed_in(state):
        hint = account_hint()
        summary["account_hint"] = mask_email(hint["email"]) if hint["email"] else ""
        summary["pending_approval_id"] = state.get("pending_approval_id") or ""
        summary["pending_user_code"] = state.get("pending_user_code") or ""
        summary["pending_approval_url"] = state.get("pending_approval_url") or ""
        if live:
            summary["sign_in_mode"] = sign_in_mode()
            if summary["pending_approval_id"]:
                summary["sign_in_steps"] = sign_in_steps(
                    summary["pending_user_code"], summary["pending_approval_url"]
                )
        return summary
    summary["connected"] = True
    summary["wallet_address"] = state.get("wallet_address") or ""
    summary["expires_at"] = state.get("expires_at") or ""
    summary["signed_in_as"] = state.get("signed_in_as") or state.get("email") or ""
    summary.update(_access_summary(state))
    if state.get("pending_approval_id"):
        # Signed in, with a sign-in in flight: the read-only -> trading upgrade.
        summary["pending_approval_id"] = state["pending_approval_id"]
        summary["pending_user_code"] = state.get("pending_user_code") or ""
        summary["pending_approval_url"] = state.get("pending_approval_url") or ""
        summary["pending_upgrade"] = bool(state.get("pending_upgrade"))
    if not live:
        return summary
    # Carried while signed in so the pane can show the right sign-in form the
    # instant the user signs out (cached capability probe: no extra request).
    summary["sign_in_mode"] = sign_in_mode()
    summary["can_adjust_limit"] = can_adjust_limit()
    summary["earn_supported"] = embeds_earn()
    if state.get("pending_limit_change_id"):
        summary["pending_limit_change_url"] = state.get("pending_limit_change_url") or ""
        summary["pending_limit_requested"] = state.get("pending_limit_requested")
    if summary.get("pending_approval_id"):
        summary["sign_in_steps"] = sign_in_steps(
            summary["pending_user_code"], summary["pending_approval_url"],
            upgrade=summary.get("pending_upgrade", False),
        )
    try:
        who = call("whoami", {}, timeout=15.0)
        if isinstance(who, dict):
            summary["wallet_address"] = who.get("wallet_address") or summary["wallet_address"]
            summary["expires_at"] = who.get("expires_at") or summary["expires_at"]
            summary["server_confirmed"] = True
            access = _access_fields(who)
            if access:
                save_state(access)  # the server decides; keep the local copy honest
                summary.update(_access_summary({**state, **access}))
            for key in ("spent_today_usd", "remaining_today_usd"):
                if who.get(key) is not None:
                    summary[key] = who[key]
    except (MCPError, ToolError, NotSignedIn) as exc:
        summary["connected"] = False
        summary["error"] = str(exc)
        summary["sign_in_mode"] = sign_in_mode()
    if summary.get("access") == "read_only":
        summary["next"] = (
            "Read-only session: reads and quotes work, trades are refused. To "
            + ("trade, call coinfello_set_daily_limit with the human's chosen "
               "daily limit (they approve it in their browser; no new sign-in)."
               if summary.get("can_adjust_limit") else
               "trade, call coinfello_connect (it starts the upgrade) and send its "
               "user_message to the human exactly as written.")
        )
    return summary


def wallet() -> dict:
    """The automation wallet's funding details: address + scannable QR.

    The address is the one the session is bound to — the same automations
    wallet the CoinFello web app's "Add funds" flow sends to, and the one
    ``get_balances`` reads.
    """
    state = load_state()
    address = (state.get("wallet_address") or "").strip()
    if not signed_in(state) or not address:
        raise NotSignedIn("sign in to see the wallet address")
    return {
        "ok": True,
        "address": address,
        "qr_svg": qr_svg_data_uri(address),
        "portfolio_url": app_url("/portfolio"),
    }


def portfolio() -> dict:
    """Balances grouped by network, shaped like the CoinFello Portfolio view."""
    balances = call("get_balances", {})
    if not isinstance(balances, dict):
        raise RuntimeError(f"unexpected get_balances reply: {_text(balances)}")
    model = shape_portfolio(balances)
    model["ok"] = True
    model["portfolio_url"] = app_url("/portfolio")
    model["strategies_url"] = app_url("/strategies")
    model["running_url"] = app_url("/portfolio/running")
    access = _access_summary(load_state())
    model["access"] = access["access"]
    model["can_trade"] = access["can_trade"]
    model["can_send"] = access["can_trade"] and supports("prepare_send") and supports("execute_intent")
    model["can_swap"] = access["can_trade"] and supports("create_embed_token")
    # Earn is offered on read-only sessions too: browsing yields needs no
    # trading access, and the server decides whether to mint (see embed_token).
    model["earn_supported"] = embeds_earn()
    model["earn_url"] = app_url("/earn")
    model["can_view_portfolio"] = supports_portfolio_embed()
    return model


# -- amounts -------------------------------------------------------------------
# The server takes a plain decimal with a leading digit ("0.001", not ".001").
# Every amount the pane or the agent sends goes through normalize_amount
# first; desktop/plugin.js normalizeAmount is the pane's copy of the same
# rules (tests/amount_cases.json holds the two to one table).

_AMOUNT_RE = re.compile(r"([0-9]*)(?:\.([0-9]*))?")
AMOUNT_HINT = "Enter an amount like 0.001"
AMOUNT_ZERO = "Enter an amount greater than 0"


def normalize_amount(value: Any) -> str:
    """``" .001 "`` -> ``"0.001"``, ``"1."`` -> ``"1"``, ``"007.50"`` -> ``"7.5"``.

    String operations only, so no digit is lost to float rounding. Raises
    ValueError with a plain message for anything else: a sign, an exponent,
    a second dot, letters, or zero.
    """
    text = str(value if value is not None else "").strip()
    match = _AMOUNT_RE.fullmatch(text)
    if not match or not (match.group(1) or match.group(2)):
        raise ValueError(AMOUNT_HINT)
    whole = match.group(1).lstrip("0") or "0"
    fraction = (match.group(2) or "").rstrip("0")
    if whole == "0" and not fraction:
        raise ValueError(AMOUNT_ZERO)
    return f"{whole}.{fraction}" if fraction else whole


def activity(before: str | None = None) -> dict:
    """One page of the wallet's history for the pane's Activity tab.

    The first page (no ``before``) also carries the Hyperliquid fills, which
    the server reads by time window rather than by cursor; older pages are
    transactions only.
    """
    if not supports("get_activity"):
        return {
            "ok": False,
            "unsupported": True,
            "error": "This CoinFello server does not share activity yet.",
            "activity_url": app_url("/portfolio/activity"),
        }
    payload: dict = {}
    if before:
        payload["before"] = before
    raw = call("get_activity", payload, timeout=45.0)
    if not isinstance(raw, dict):
        raise RuntimeError(f"unexpected get_activity reply: {_text(raw)}")
    # Name the venue under aggregator-routed swaps/bridges (never the
    # aggregator itself). Best effort and cached; a slow chain read only
    # leaves that row without a venue until the next refresh.
    bridge_tool = (lambda tx: call("get_transfer_status", {"tx_hash": tx}, timeout=15.0)) if supports(
        "get_transfer_status") else None
    venues = coinfello_venues.resolve(venue_jobs(raw), bridge_tool)
    model = shape_activity(raw, include_fills=not before, venues=venues)
    model["activity_url"] = app_url("/portfolio/activity")
    return model


# -- user-confirmed actions ---------------------------------------------------
# The pane calls these directly. Agent tools reach them only through
# coinfello_trades, behind Hermes' human-approval gate.

def prepare_send(chain_id: Any, token: str, amount: str, recipient: str) -> dict:
    """Validate and price a send; returns a summary + single-use intent id.

    Executes nothing: the pane shows the summary, and only the human's
    confirmation calls ``execute_intent``.
    """
    if not supports("prepare_send"):
        raise RuntimeError("Sending from Hermes needs a CoinFello server update.")
    try:
        chain = int(str(chain_id))
    except ValueError as exc:
        raise ValueError("chain_id must be a number") from exc
    amount = normalize_amount(amount)
    recipient = str(recipient or "").strip()
    if not recipient:
        raise ValueError("recipient is required")
    result = trading_call(
        "prepare_send",
        {"chain_id": chain, "token": str(token), "amount": amount, "recipient": recipient},
    )
    if not isinstance(result, dict) or not result.get("intentId"):
        raise RuntimeError(_text(result))
    return {
        "ok": True,
        "intent_id": result["intentId"],
        "expires_in_seconds": result.get("expiresInSeconds"),
        "summary": result.get("summary") or {},
    }


def execute_intent(intent_id: str) -> dict:
    """Run a prepared intent once. Its arguments were fixed at prepare time."""
    intent_id = str(intent_id or "").strip()
    if not intent_id:
        raise ValueError("intent_id is required")
    try:
        result = trading_call("execute_intent", {"intent_id": intent_id}, timeout=180.0)
    except ToolError as exc:
        # The server's own words (expired, already used, price moved, ...).
        text = str(exc)
        try:
            detail = json.loads(text)
        except ValueError:
            return {"ok": False, "error": text}
        if isinstance(detail, dict):
            return {
                "ok": False,
                "error": detail.get("error") or "The transaction did not go through.",
                "price_moved": bool(detail.get("priceMoved")),
                # The approved bridge no longer offers the route: nothing was
                # sent; prepare (and confirm) again, like a moved price.
                "route_changed": bool(detail.get("routeChanged")),
                # Broadcast but unconfirmed: it may have gone through. The
                # pane must not offer a retry, only a way to check it.
                "outcome_unknown": bool(detail.get("outcomeUnknown")),
                "transaction_hash": detail.get("transactionHash"),
                "explorer_url": explorer_url(detail.get("transactionHash")),
            }
        return {"ok": False, "error": text}
    if not isinstance(result, dict):
        raise RuntimeError(_text(result))
    return {
        "ok": bool(result.get("success")),
        "kind": result.get("kind"),
        "transaction_hash": result.get("transactionHash"),
        "explorer_url": explorer_url(result.get("transactionHash")),
        "error": result.get("error"),
    }


def explorer_url(transaction_hash: Any) -> str | None:
    """Blockscan resolves a hash on whichever chain it lives on."""
    if not isinstance(transaction_hash, str) or not transaction_hash.startswith("0x"):
        return None
    return f"https://blockscan.com/tx/{transaction_hash}"


#: The embedded views the pane hosts: scope -> its path on the app.
EMBED_PATHS = {"swap": "/embed/swap", "earn": "/embed/earn", "portfolio": "/embed/portfolio"}
EMBED_SCOPES = tuple(EMBED_PATHS)
EARN_NEEDS_UPDATE = "Earn in Hermes needs a CoinFello server update."
PORTFOLIO_NEEDS_UPDATE = "The in-app portfolio needs a CoinFello server update."


def embeds_earn() -> bool:
    """True when the server mints Earn embed tokens: ``create_embed_token``
    declares ``scope`` and, if it lists the values, ``earn`` is one. Servers
    before the Earn embed (production until it ships) have no ``scope``."""
    if not accepts_param("create_embed_token", "scope"):
        return False
    values = param_enum("create_embed_token", "scope")
    return values is None or "earn" in values


def supports_portfolio_embed() -> bool:
    """coinfello-web's read-only /embed/portfolio (scope 'portfolio')."""
    return supports("create_embed_token") and accepts_value("create_embed_token", "scope", "portfolio")


def embed_token(scope: str = "swap") -> dict:
    """A short-lived, scope-limited token for CoinFello's embedded views.

    Minted from the session server-side so the 30-day session token never
    reaches the renderer; the embed gets this 15-minute token, good only for
    its own view (``swap``, ``earn`` or ``portfolio``).

    Swap moves funds: refused up front on a session known to be read-only,
    and ``scope`` is sent only to a server whose schema declares it. Earn is
    always asked of the server, which may mint one for browsing. The
    portfolio view only reads, so it is minted with a plain call and only
    from a server whose ``scope`` enum lists it.
    """
    if scope not in EMBED_PATHS:
        raise ValueError(f"unknown embed scope {scope!r}: one of {', '.join(EMBED_PATHS)}")
    if scope == "portfolio":
        if not supports_portfolio_embed():
            raise RuntimeError(PORTFOLIO_NEEDS_UPDATE)
        result = call("create_embed_token", {"scope": scope}, timeout=20.0)
    else:
        if not supports("create_embed_token"):
            raise RuntimeError(
                "Swapping from Hermes needs a CoinFello server update." if scope == "swap" else EARN_NEEDS_UPDATE
            )
        if scope == "earn" and not embeds_earn():
            raise RuntimeError(EARN_NEEDS_UPDATE)
        payload = {"scope": scope} if accepts_param("create_embed_token", "scope") else {}
        result = trading_call("create_embed_token", payload, timeout=20.0, refuse_locally=scope == "swap")
    if not isinstance(result, dict) or not result.get("embed_token"):
        raise RuntimeError(_text(result))
    return {
        "ok": True,
        "token": result["embed_token"],
        "expires_at": result.get("expires_at"),
        "embed_url": result.get("embed_url") or app_url(EMBED_PATHS[scope]),
    }


# -- daily limit: lower here, raise with the human's browser approval ---------
#
# The agent holds the same session token this backend does, so anything the
# token can do the agent can do. The server therefore lets the token only
# LOWER the limit (set_daily_limit); a raise, or read-only -> trading, is a
# change the human approves on CoinFello in their own browser
# (start_limit_change), and the session keeps its token either way.

def can_adjust_limit() -> bool:
    return supports("set_daily_limit") and supports("start_limit_change")


def _parse_limit(limit_usd: Any) -> float | None:
    """None means read only; otherwise a positive dollar amount (cents)."""
    if limit_usd is None or (isinstance(limit_usd, str) and limit_usd.strip().lower() in ("", "read_only", "none")):
        return None
    try:
        value = round(float(str(limit_usd).replace("$", "").replace(",", "").strip()), 2)
    except ValueError as exc:
        raise ValueError("the limit is a dollar amount, e.g. 500, or read_only") from exc
    if not value > 0:
        raise ValueError("the daily limit must be more than $0 (or read_only)")
    return value


def _current_limit(state: dict) -> float | None:
    """The session's limit: None for read-only, a number when trading."""
    if state.get("access") == "trade":
        return float(state.get("daily_limit_usd") or 0)
    return None


def _store_access(result: dict) -> dict:
    access = _access_fields(result)
    if access:
        save_state(access)
    return access


def _limit_text(limit: float | None) -> str:
    return "read only" if limit is None else f"${limit:,.2f}".replace(".00", "") + " a day"


def change_daily_limit(limit_usd: Any) -> dict:
    """Set the daily limit. Lowering (or read-only) applies at once; a raise
    returns an approval link for the human, and the session is unchanged
    until they approve it."""
    if not can_adjust_limit():
        raise RuntimeError(
            "This CoinFello server cannot change a session's limit yet; sign in "
            "again to pick a different one (coinfello_connect)."
        )
    new = _parse_limit(limit_usd)
    state = load_state()
    current = _current_limit(state)
    lowering = new is None or (current is not None and new <= current)
    if lowering:
        try:
            result = call("set_daily_limit", {"limit_usd": new}, timeout=20.0)
        except ToolError as exc:
            if "raise_needs_approval" not in str(exc):
                raise
            lowering = False  # our cached limit was stale: the server decides
        else:
            if not isinstance(result, dict):
                raise RuntimeError(_text(result))
            _store_access(result)
            # The server cancels any pending raise when a session lowers its
            # limit (so an old approval link cannot undo the lowering); forget
            # ours too, or the pane would keep waiting on a dead link.
            cancel_limit_change()
            out = {"ok": True, "status": "changed", **_access_summary(load_state())}
            for key in ("spent_today_usd", "remaining_today_usd"):
                if result.get(key) is not None:
                    out[key] = result[key]
            out["user_message"] = f"Done: your agent's limit is now {_limit_text(new)}. No new sign-in needed."
            return out

    result = call("start_limit_change", {"limit_usd": new}, timeout=20.0)
    if not isinstance(result, dict) or not result.get("approval_url"):
        raise RuntimeError(_text(result))
    save_state(
        {
            "pending_limit_change_id": result.get("change_id") or "",
            "pending_limit_change_url": result["approval_url"],
            "pending_limit_requested": new,
        }
    )
    return {
        "ok": True,
        "status": "approval_required",
        "approval_url": result["approval_url"],
        "change_id": result.get("change_id"),
        "requested": result.get("requested"),
        "expires_in_seconds": result.get("expires_in_seconds"),
        "user_message": (
            f"To raise your agent's limit to {_limit_text(new)}, open "
            f"{result['approval_url']} in your regular browser and approve it "
            "(sign in to CoinFello first if it asks). You keep the same "
            "session: no new sign-in or code. The link expires in 10 minutes."
        ),
        "next": (
            "Send user_message to the human exactly as written. Do not open the "
            "link yourself. Then call coinfello_limit_status every 5-10 seconds."
        ),
    }


def poll_limit_change() -> dict:
    """Finish a pending raise once the human has approved it in the browser."""
    state = load_state()
    change_id = state.get("pending_limit_change_id") or ""
    if not change_id:
        return {"ok": True, "status": "none", **_access_summary(state)}
    result = call("get_limit_change", {"change_id": change_id}, timeout=20.0)
    if not isinstance(result, dict):
        raise RuntimeError(_text(result))
    status = result.get("status")
    if status == "pending":
        return {"ok": True, "status": "pending"}
    cancel_limit_change()
    if status == "approved":
        _store_access(result)
        summary = _access_summary(load_state())
        return {
            "ok": True,
            "status": "approved",
            **summary,
            "user_message": f"Approved: your agent can now trade up to {_limit_text(_current_limit(load_state()))}.",
        }
    return {"ok": True, "status": status or "expired", **_access_summary(load_state())}


def cancel_limit_change() -> dict:
    save_state(
        {"pending_limit_change_id": "", "pending_limit_change_url": "", "pending_limit_requested": None}
    )
    return {"ok": True}
