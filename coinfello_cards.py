"""MCP App cards: CoinFello's ``show_*_card`` tools, drawn in the desktop pane.

The model calls ``coinfello_show_card``. The plugin calls the server's
``show_<card>_card`` with the stored session (never a token from the model),
keeps the raw CallToolResult as a card record, and on Hermes desktop tells
the pane (``plugin.coinfello.card.shown``), which mounts the card's HTML in a
sandboxed frame and relays the MCP Apps bridge. Every other surface
(Telegram, CLI, ...) gets the card's full text instead.

What a card may do is decided here and again in the pane (``desktop/plugin.js``
keeps the same tables): its own refresh tool, a few named reads and
``prepare_*`` quotes. Two tools need a human first: ``execute_intent`` (only
for an intent this card prepared, through the trading path) and
``cancel_automation`` (only an automation this card listed). The pane draws
the confirmation from the summary returned here, and only its Confirm button
calls ``card_execute``. Everything else, sign-out, Fello, sign-in, limits and
embed tokens included, is refused.
"""

from __future__ import annotations

import base64
import html as html_lib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, NamedTuple

try:  # package import inside Hermes; plain import in tests / the dashboard
    from . import coinfello_core as core
    from . import coinfello_trades as trades
except ImportError:  # pragma: no cover
    import coinfello_core as core  # type: ignore[no-redef]
    import coinfello_trades as trades  # type: ignore[no-redef]

PLUGIN_ID = "coinfello"
CARD_SHOWN_EVENT = "card.shown"
CARD_URI_PREFIX = "ui://coinfello/"

#: A card record lives a day; the pane lists what is still fresh.
CARD_TTL_SECONDS = 24 * 60 * 60
#: Card HTML is static per deployment; re-read it every ten minutes.
HTML_TTL_SECONDS = 10 * 60
#: A confirmation the pane drew must be answered within this window.
CONFIRM_TTL_SECONDS = 120
#: Relayed calls per card per minute (the pane enforces the same).
CALLS_PER_MINUTE = 30
#: Records kept on disk; the oldest go first.
MAX_CARDS = 50


class Card(NamedTuple):
    tool: str
    uri: str
    title: str
    relay: frozenset = frozenset()
    confirm: frozenset = frozenset()


_MONEY = frozenset({"execute_intent"})

#: The cards the model may show. Keys are ``coinfello_show_card``'s ``card``.
#: ``show_sign_in_card`` is left out on purpose: the pane has its own sign-in.
CARDS: dict[str, Card] = {
    "portfolio": Card("show_portfolio_card", "ui://coinfello/portfolio-card.html", "Portfolio"),
    "status": Card("show_status_card", "ui://coinfello/status-card.html", "Status"),
    "quote": Card("show_quote_card", "ui://coinfello/quote-card.html", "Quote",
                  frozenset({"prepare_swap", "prepare_send"}), _MONEY),
    "automations": Card("show_automations_card", "ui://coinfello/automations-card.html", "Automations",
                        frozenset({"pause_automation"}), frozenset({"cancel_automation"})),
    "needs_you": Card("show_needs_you_card", "ui://coinfello/needs-you-card.html", "Needs you"),
    "error": Card("show_error_card", "ui://coinfello/error-card.html", "Something went wrong"),
    "fund": Card("show_fund_card", "ui://coinfello/fund-card.html", "Fund your wallet"),
    "yield": Card("show_yield_card", "ui://coinfello/yield-card.html", "Yields"),
    "lp_ranges": Card("show_lp_ranges_card", "ui://coinfello/lp-ranges-card.html", "LP ranges"),
    "perp": Card("show_perp_card", "ui://coinfello/perp-card.html", "Perps"),
    "send": Card("show_send_card", "ui://coinfello/send-card.html", "Send",
                 frozenset({"prepare_send"}), _MONEY),
    "dca": Card("show_dca_card", "ui://coinfello/dca-card.html", "Recurring buy",
                frozenset({"prepare_dca"}), _MONEY),
    "earn_deposit": Card("show_earn_deposit_card", "ui://coinfello/earn-deposit-card.html", "Earn",
                         frozenset({"prepare_earn_deposit"}), _MONEY),
    "spend_limit": Card("show_spend_limit_card", "ui://coinfello/spend-limit-card.html", "Spend limit",
                        frozenset({"prepare_spend_limit"}), _MONEY),
}

#: Every card may ask who is signed in.
ALWAYS_RELAYED = frozenset({"whoami"})

#: What the error card's Retry may call, mirroring coinfello-web's
#: ``RETRYABLE_TOOLS`` (error_card.ts): reads and quotes, never a trade.
RETRYABLE_TOOLS = frozenset({
    "get_activity", "get_balances", "get_deposit_options", "get_gas_price",
    "get_lp_positions", "get_needs_attention", "get_open_orders", "get_positions",
    "get_prices", "get_quote", "get_transfer_status", "get_yields",
    "prepare_send", "prepare_swap", "whoami",
})

#: Refused from every card, whatever a table above says (``privy_*`` too).
NEVER_RELAYED = frozenset({
    "sign_out", "fello_chat", "fello_job_status", "start_browser_sign_in",
    "renew_session", "create_embed_token", "set_daily_limit", "start_limit_change",
    "get_limit_change", "sign_in_card_status", "show_sign_in_card",
})

#: Credential-like keys, compared lowercase with ``_`` and ``-`` removed,
#: dropped from card arguments and results at any depth. Bare ``token`` stays:
#: it is a coin symbol argument (get_yields, prepare_send).
_SECRET_KEYS = frozenset({
    "sessiontoken", "embedtoken", "accesstoken", "refreshtoken", "idtoken",
    "authtoken", "authorization", "bearer", "apikey", "secret", "clientsecret",
    "credentials", "mnemonic", "seed", "seedphrase", "password", "privatekey",
    "cookie",
})
#: Keys that would set a prototype in the card's JavaScript.
_UNSAFE_KEYS = frozenset({"__proto__", "constructor", "prototype"})
_MAX_DEPTH = 24

_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ORIGIN_RE = re.compile(r"^https://[A-Za-z0-9.-]+(:\d{1,5})?$")
# The CSP must be the first thing the document's <head> holds, so only a
# document that opens with it (doctype and <html> allowed) is rendered.
_HEAD_RE = re.compile(r"^\s*(?:<!doctype[^>]*>\s*)?(?:<html\b[^>]*>\s*)?<head\b[^>]*>", re.I)
_HTML_TAG_RE = re.compile(r"<html\b[^>]*>", re.I)
_THEME_ATTR_RE = re.compile(r"\sdata-theme\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)

PANE_NOTE = (
    "The card is on screen in the CoinFello pane beside this chat (Hermes "
    "desktop), not inline in the chat. It shows every row, so do not repeat "
    "them as a list or table: write a short framing of what the figures mean "
    "and what this result leaves out, using only figures in `text`. A Confirm "
    "on the card asks the human in the pane and runs there; do not also call "
    "coinfello_execute for it."
)
NO_CARD_NOTE = (
    "No card can be shown on this surface ({surface}): `text` is the whole "
    "answer, so include its items."
)


class CardRefused(ValueError):
    """The card asked for something it may not do (or no longer may)."""


_lock = threading.RLock()
_cards: dict[str, dict] = {}
_calls: dict[str, list[float]] = {}
_confirms: dict[str, dict] = {}
_html: dict[tuple, tuple[float, dict]] = {}
_surface_reader: Callable[[], str] | None = None


# -- host wiring ----------------------------------------------------------------

def bind_host(ctx: Any) -> None:
    """Keep the plugin context's ``session_surface`` (Hermes >= 0.22.3)."""
    global _surface_reader
    reader = getattr(ctx, "session_surface", None)
    _surface_reader = reader if callable(reader) else None


def session_surface() -> str:
    """``desktop``, ``cli``, ``telegram``, ... for the running turn; "" if unknown."""
    if _surface_reader is None:
        return ""
    try:
        surface = _surface_reader()
    except Exception:
        return ""
    return surface if isinstance(surface, str) else ""


def _announce(card_id: str) -> bool:
    """Tell the desktop half a card is ready. A no-op on Hermes without the
    plugin event bridge (before 0.21.6), or with no desktop attached."""
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event
    except Exception:
        return False
    try:
        broadcast_plugin_event(PLUGIN_ID, CARD_SHOWN_EVENT, {"id": card_id})
    except Exception:
        return False
    return True


# -- secrets + arguments --------------------------------------------------------

def _is_secret(key: str) -> bool:
    return key.lower().replace("_", "").replace("-", "") in _SECRET_KEYS


def strip_secrets(value: Any, depth: int = 0) -> Any:
    """``value`` without credential-like keys at any depth."""
    if depth > _MAX_DEPTH:
        return None
    if isinstance(value, dict):
        return {
            key: strip_secrets(item, depth + 1)
            for key, item in value.items()
            if isinstance(key, str) and not _is_secret(key) and key not in _UNSAFE_KEYS
        }
    if isinstance(value, list):
        return [strip_secrets(item, depth + 1) for item in value]
    return value


def tool_arguments(tool: str, arguments: Any) -> dict:
    """Only the arguments the server's schema for ``tool`` declares, minus
    secrets: an argument an older server has not advertised is never sent."""
    if not isinstance(arguments, dict):
        return {}
    declared = core.tool_params(tool)
    return {key: value for key, value in strip_secrets(arguments).items() if key in declared}


# -- card records -----------------------------------------------------------------

def cards_dir() -> Path:
    """``<hermes home>/coinfello/cards`` (per profile when Hermes says so)."""
    try:
        from hermes_constants import get_hermes_home

        home = Path(get_hermes_home())
    except Exception:
        home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    return home / "coinfello" / "cards"


def _expired(record: dict) -> bool:
    return time.time() - float(record.get("created_at") or 0) > CARD_TTL_SECONDS


def _write(record: dict) -> None:
    directory = cards_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        path = directory / f"{record['id']}.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(record))
        os.chmod(temp, 0o600)
        temp.replace(path)
    except OSError:
        pass  # memory still holds it; the disk copy only survives restarts


def _delete(card_id: str) -> None:
    with _lock:
        _cards.pop(card_id, None)
        _calls.pop(card_id, None)
    try:
        (cards_dir() / f"{card_id}.json").unlink()
    except OSError:
        pass


def _load_disk() -> None:
    try:
        paths = list(cards_dir().glob("*.json"))
    except OSError:
        return
    for path in paths:
        card_id = path.stem
        if not _ID_RE.match(card_id) or card_id in _cards:
            continue
        try:
            record = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("id") == card_id:
            _cards[card_id] = record


def _prune() -> None:
    with _lock:
        _load_disk()
        for card_id in [k for k, v in _cards.items() if _expired(v)]:
            _delete(card_id)
        extra = sorted(_cards.values(), key=lambda r: r.get("created_at") or 0)[:-MAX_CARDS]
        for record in extra:
            _delete(record["id"])


def save_card(record: dict) -> dict:
    with _lock:
        _cards[record["id"]] = record
        _write(record)
    return record


def get_card(card_id: str) -> dict:
    """A live card record, or CardRefused (unknown, malformed or expired)."""
    card_id = str(card_id or "")
    if not _ID_RE.match(card_id):
        raise CardRefused("Unknown card.")
    with _lock:
        record = _cards.get(card_id)
        if record is None:
            _load_disk()
            record = _cards.get(card_id)
    if record is None:
        raise CardRefused("Unknown card.")
    if _expired(record):
        _delete(card_id)
        raise CardRefused("This card expired. Ask for it again.")
    return record


def list_cards() -> list[dict]:
    """Live cards, newest first, without their payloads."""
    _prune()
    with _lock:
        records = sorted(_cards.values(), key=lambda r: r.get("created_at") or 0, reverse=True)
    return [
        {
            "id": record["id"],
            "card": record.get("card"),
            "title": record.get("title"),
            "uri": record.get("uri"),
            "created_at": record.get("created_at"),
            "session_id": record.get("session_id") or "",
        }
        for record in records
    ]


def dismiss_card(card_id: str) -> dict:
    get_card(card_id)
    _delete(card_id)
    return {"ok": True}


def _kind(record: dict) -> Card | None:
    for card in CARDS.values():
        if card.uri == record.get("uri"):
            return card
    return None


def _structured(result: Any) -> dict:
    data = (result or {}).get("structuredContent") if isinstance(result, dict) else None
    return data if isinstance(data, dict) else {}


def _payload(result: dict) -> dict:
    """structuredContent, else the JSON text (prepare_* answer as text)."""
    data = _structured(result)
    if data:
        return data
    try:
        parsed = json.loads(core.result_text(result))
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _card_intent(result: dict) -> str:
    intent = _structured(result).get("intentId")
    return intent if isinstance(intent, str) else ""


# The intents a card owns live IN its record, with the server's summary:
# the dashboard API (which serves the pane) is a separate module from the
# agent tools, and with turn isolation a separate process, so the trades
# cache the tools fill is not visible to it.

def _own_intent(record: dict, intent: str, summary: dict | None, seconds: float) -> None:
    """Record ``intent`` as this card's. ``summary`` None: the card names it,
    but Hermes holds no server summary for it, so it can never be confirmed."""
    with _lock:
        record.setdefault("intents", {})[intent] = {
            "summary": summary,
            "expires_at": time.time() + max(0.0, float(seconds)),
        }


def _own_card_intent(record: dict, result: dict) -> None:
    """The intent a quote/money card shows: ours only if this Hermes prepared
    it (coinfello_prepare_*, which cached the server's summary)."""
    intent = _card_intent(result)
    if intent:
        _own_intent(record, intent, trades.recall_intent(intent), trades.intent_seconds_left(intent))


# -- showing a card ---------------------------------------------------------------

def _fallback_text(result: dict) -> str:
    """The card's text without the server's first-line "Model note", which
    assumes the card is drawn at the tool call (here it is in the pane)."""
    lines = core.result_text(result).split("\n")
    if lines and lines[0].startswith("Model note:"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def card_names() -> list[str]:
    return list(CARDS)


def show_card(card: Any, arguments: Any = None, *, session_id: str = "", surface: str | None = None) -> dict:
    """Call ``show_<card>_card``; on desktop, store it for the pane."""
    name = str(card or "").strip().lower().replace("-", "_")
    kind = CARDS.get(name)
    if kind is None:
        raise ValueError(f"unknown card {card!r}: one of {', '.join(CARDS)}")
    if not core.supports(kind.tool):
        raise RuntimeError(
            f"This CoinFello server has no {name} card yet ({kind.tool}). Use the "
            "matching coinfello_* read instead."
        )
    declared = core.card_resource_uri(kind.tool)
    if declared != kind.uri:
        raise RuntimeError(
            f"{kind.tool} renders {declared or 'no card'}, not {kind.uri}; this "
            "plugin only draws the CoinFello cards it knows."
        )
    args = tool_arguments(kind.tool, arguments)
    result = strip_secrets(core.call_result(kind.tool, args))
    text = _fallback_text(result)
    if result.get("isError"):
        raise core.ToolError(text or f"{kind.tool} failed without detail")

    surface = session_surface() if surface is None else surface
    if surface != "desktop":
        return {
            "ok": True,
            "card": name,
            "shown": False,
            "text": text,
            "note": NO_CARD_NOTE.format(surface=surface or "unknown"),
        }
    record = save_card({
        "id": secrets.token_hex(16),
        "card": name,
        "title": kind.title,
        "uri": kind.uri,
        "tool": kind.tool,
        "args": args,
        "result": result,
        "session_id": str(session_id or ""),
        "intents": {},
        "created_at": time.time(),
    })
    _own_card_intent(record, result)
    save_card(record)
    _prune()
    _announce(record["id"])
    return {
        "ok": True,
        "card": name,
        "card_id": record["id"],
        "shown": "coinfello_pane",
        "text": text,
        "note": PANE_NOTE,
    }


# -- the card document ------------------------------------------------------------

def card_csp(resource_meta: Any) -> str:
    """The frame's Content-Security-Policy, from the resource's ``_meta.ui.csp``.

    Only ``resourceDomains`` (https origins) is honored, for styles and fonts.
    ``connectDomains`` and ``frameDomains`` are ignored: a card reaches the
    server only through the host bridge, and never frames anything.
    """
    meta = resource_meta if isinstance(resource_meta, dict) else {}
    ui = meta.get("ui") if isinstance(meta.get("ui"), dict) else {}
    csp = ui.get("csp") if isinstance(ui.get("csp"), dict) else {}
    domains = [
        domain for domain in (csp.get("resourceDomains") or [])
        if isinstance(domain, str) and _ORIGIN_RE.match(domain)
    ]
    sources = " ".join(dict.fromkeys(domains))
    return "; ".join([
        "default-src 'none'",
        "script-src 'unsafe-inline'",
        f"style-src 'unsafe-inline' {sources}".strip(),
        f"font-src {sources}" if sources else "font-src 'none'",
        "img-src data:",
        "connect-src 'none'",
        "frame-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    ])


def prepare_html(document: str, csp: str, theme: str = "") -> str:
    """The card's HTML with the CSP as the first element of <head>, and the
    host theme on <html> (so the first paint already matches)."""
    head = _HEAD_RE.match(document or "")
    if head is None:
        raise core.MCPError("the card document does not open with <head>; not rendering it")
    policy = f'<meta http-equiv="Content-Security-Policy" content="{html_lib.escape(csp, quote=True)}">'
    document = document[: head.end()] + policy + document[head.end():]
    if theme in ("light", "dark"):
        document = _HTML_TAG_RE.sub(
            lambda tag: _THEME_ATTR_RE.sub("", tag.group(0))[:-1] + f' data-theme="{theme}">',
            document,
            count=1,
        )
    return document


def _resource(uri: str) -> dict:
    key = (core.mcp_url(), uri)
    with _lock:
        cached = _html.get(key)
    if cached and time.monotonic() - cached[0] < HTML_TTL_SECONDS:
        return cached[1]
    resource = core.read_card_resource(uri)
    with _lock:
        _html[key] = (time.monotonic(), resource)
    return resource


def card_document(card_id: str, theme: str = "") -> dict:
    """Everything the pane needs to mount a card: a ready ``data:`` document,
    the tool input and the raw tool result, and what it may relay."""
    record = get_card(card_id)
    kind = _kind(record)
    if kind is None:
        raise CardRefused("This plugin does not draw that card.")
    resource = _resource(record["uri"])
    document = prepare_html(resource["text"], card_csp(resource.get("_meta")), theme)
    ui = (resource.get("_meta") or {}).get("ui") or {}
    return {
        "ok": True,
        "id": record["id"],
        "card": record.get("card"),
        "title": record.get("title"),
        "uri": record["uri"],
        "src": "data:text/html;base64," + base64.b64encode(document.encode("utf-8")).decode("ascii"),
        "tool_input": {"arguments": record.get("args") or {}},
        "tool_result": record.get("result") or {},
        "relay": sorted(kind.relay | ALWAYS_RELAYED | {kind.tool}),
        "confirm": sorted(kind.confirm),
        "prefers_border": bool(ui.get("prefersBorder")) if isinstance(ui, dict) else False,
        "created_at": record.get("created_at"),
    }


# -- the bridge: relayed calls ----------------------------------------------------

def relay_decision(record: dict, tool: str) -> str:
    """``relay``, ``confirm`` (needs the human first) or ``deny``."""
    tool = str(tool or "")
    kind = _kind(record)
    if kind is None or tool in NEVER_RELAYED or tool.startswith("privy_"):
        return "deny"
    if tool in kind.confirm:
        return "confirm"
    if tool == kind.tool or tool in kind.relay or tool in ALWAYS_RELAYED:
        return "relay"
    if kind.tool == "show_error_card" and tool in RETRYABLE_TOOLS \
            and _structured(record.get("result")).get("retryTool") == tool:
        return "relay"
    return "deny"


def _rate_check(card_id: str) -> None:
    now = time.monotonic()
    with _lock:
        recent = [t for t in _calls.get(card_id, []) if now - t < 60]
        if len(recent) >= CALLS_PER_MINUTE:
            _calls[card_id] = recent
            raise CardRefused("Too many requests from this card. Wait a minute.")
        recent.append(now)
        _calls[card_id] = recent


def _own_prepared(record: dict, result: dict) -> None:
    """A quote this card asked for: its intent is now the card's, with the
    SERVER's summary cached for the confirmation (as coinfello_prepare_* does)."""
    if result.get("isError"):
        return
    payload = _payload(result)
    intent = payload.get("intentId")
    if not isinstance(intent, str) or not intent:
        return
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    try:
        seconds = float(payload.get("expiresInSeconds")) - 10.0
    except (TypeError, ValueError):
        seconds = float(trades.INTENT_TTL_FALLBACK_SECONDS)
    _own_intent(record, intent, summary, min(seconds, float(trades.INTENT_TTL_FALLBACK_SECONDS)))


def card_call(card_id: str, tool: str, arguments: Any = None) -> dict:
    """One ``tools/call`` from a card. A confirm-gated tool is NOT run: the
    answer is the confirmation for the pane to show."""
    record = get_card(card_id)
    tool = str(tool or "").strip()
    decision = relay_decision(record, tool)
    if decision == "deny":
        raise CardRefused(f"{tool or 'That tool'} is not available from this card in Hermes.")
    _rate_check(record["id"])
    arguments = strip_secrets(arguments) if isinstance(arguments, dict) else {}
    if decision == "confirm":
        return {"ok": True, "confirm": _confirmation(record, tool, arguments)}

    args = tool_arguments(tool, arguments)
    if tool.startswith("prepare_"):
        result = core.trading_call_result(tool, args)
    else:
        result = core.call_result(tool, args)
    result = strip_secrets(result)
    if tool.startswith("prepare_"):
        _own_prepared(record, result)
    kind = _kind(record)
    if kind is not None and tool == kind.tool and not result.get("isError"):
        record["result"] = result
        record["args"] = args
        _own_card_intent(record, result)
    save_card(record)
    return {"ok": True, "result": result}


def _label(key: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])([A-Z])", r" \1", key).replace("_", " ")
    return spaced[:1].upper() + spaced[1:].lower()


def summary_rows(summary: dict) -> list[list[str]]:
    """The summary's plain fields as label/value rows (nested parts are in
    the description)."""
    rows = []
    for key, value in summary.items():
        if key == "kind" or isinstance(value, (dict, list)) or value in (None, ""):
            continue
        rows.append([_label(key), str(value)])
    return rows[:12]


def describe_summary(summary: dict) -> str:
    if summary.get("kind") in ("send", "swap", "bridge"):
        return trades.describe(summary)
    kind = str(summary.get("kind") or "action").replace("_", " ")
    return f"Run this {kind} from your automations wallet, exactly as prepared."


def _automation(record: dict, trigger_id: str) -> dict | None:
    for row in _structured(record.get("result")).get("rows") or []:
        if isinstance(row, dict) and row.get("id") == trigger_id:
            return row
    return None


def _owned_intent(record: dict, intent: str) -> dict:
    """This card's live, confirmable intent, or CardRefused."""
    owned = (record.get("intents") or {}).get(intent)
    if not intent or owned is None:
        raise CardRefused("This card did not prepare that trade. Nothing was sent.")
    if not isinstance(owned.get("summary"), dict):
        raise CardRefused("That quote was not prepared in Hermes. Get a fresh one on the card; nothing was sent.")
    if float(owned.get("expires_at") or 0) <= time.time():
        raise CardRefused("That quote expired. Get a fresh one on the card; nothing was sent.")
    return owned


def _confirmation(record: dict, tool: str, arguments: dict) -> dict:
    if tool == "execute_intent":
        intent = str(arguments.get("intent_id") or "").strip()
        owned = _owned_intent(record, intent)
        confirm = {
            "title": "Confirm on-chain",
            "description": describe_summary(owned["summary"]),
            "rows": summary_rows(owned["summary"]),
            "expires_in_seconds": max(1, int(owned["expires_at"] - time.time())),
            "arguments": {"intent_id": intent},
        }
    else:  # cancel_automation
        trigger = str(arguments.get("trigger_id") or "").strip()
        row = _automation(record, trigger)
        if row is None:
            raise CardRefused("This card did not list that automation.")
        confirm = {
            "title": "Cancel automation",
            "description": (
                f"Cancel \"{row.get('name') or trigger}\". It stops for good; "
                "it cannot be resumed from Hermes or the card."
            ),
            "rows": [[label, str(row[key])] for label, key in (("Automation", "name"), ("What it does", "summary"))
                     if row.get(key)],
            "expires_in_seconds": CONFIRM_TTL_SECONDS,
            "arguments": {"trigger_id": trigger},
        }
    confirm_id = secrets.token_urlsafe(16)
    with _lock:
        now = time.monotonic()
        for key in [k for k, v in _confirms.items() if v["expires"] < now]:
            del _confirms[key]
        _confirms[confirm_id] = {
            "card_id": record["id"], "tool": tool, "arguments": confirm["arguments"],
            "expires": now + CONFIRM_TTL_SECONDS,
        }
    return {"confirm_id": confirm_id, "tool": tool, **{k: v for k, v in confirm.items() if k != "arguments"}}


def card_execute(card_id: str, confirm_id: str) -> dict:
    """Run a confirmation the human just accepted in the pane, once."""
    with _lock:
        pending = _confirms.pop(str(confirm_id or ""), None)
    if pending is None or pending["card_id"] != card_id or pending["expires"] < time.monotonic():
        raise CardRefused("This confirmation expired. Nothing was sent.")
    record = get_card(card_id)
    tool, arguments = pending["tool"], pending["arguments"]
    if relay_decision(record, tool) != "confirm":
        raise CardRefused(f"{tool} is not available from this card in Hermes.")
    if tool == "execute_intent":
        intent = arguments["intent_id"]
        _owned_intent(record, intent)
        # Single use, like coinfello_execute: gone before the call goes out.
        with _lock:
            record["intents"].pop(intent, None)
        save_card(record)
        trades.forget_intent(intent)
        result = core.trading_call_result("execute_intent", arguments, timeout=180.0)
    else:
        if _automation(record, arguments["trigger_id"]) is None:
            raise CardRefused("This card did not list that automation.")
        result = core.call_result(tool, arguments)
    return {"ok": True, "tool": tool, "result": strip_secrets(result)}


def reset_for_tests() -> None:
    with _lock:
        _cards.clear()
        _calls.clear()
        _confirms.clear()
        _html.clear()
