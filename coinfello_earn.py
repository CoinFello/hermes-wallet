"""The Earn view: CoinFello's real Earn UI (``/embed/earn``) in the desktop pane.

The pane hosts it like the swap embed (desktop/plugin.js, the embed-host
section): a sandboxed frame, a short-lived ``earn``-scoped token handed over
by postMessage, and the result reported back. This module is the backend
half: which preselects the frame URL may carry, how they are escaped, and
the "open Earn" request the model leaves for the pane.

The model reaches it through ``coinfello_show_card`` with ``card="earn_deposit"``
on Hermes desktop (coinfello_cards.show_card routes it here) rather than a
tool of its own: the model already reaches for that card to deposit, and one
entry point keeps the surface rules (desktop draws, other surfaces get text)
in one place. The request is a small file, not memory: the agent tools and
the dashboard API that serves the pane can run in different processes.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

try:  # package import inside Hermes; plain import in tests / the dashboard
    from . import coinfello_core as core
except ImportError:  # pragma: no cover
    import coinfello_core as core  # type: ignore[no-redef]

PLUGIN_ID = "coinfello"
EARN_OPEN_EVENT = "earn.open"
#: A request the pane has not picked up within this window is dropped: an
#: Earn view popping open long after the model asked would be a surprise.
REQUEST_TTL_SECONDS = 10 * 60

#: Model argument spellings for each preselect, first match wins.
_OPPORTUNITY_KEYS = ("opportunity", "opportunity_id", "yield_id", "yieldId", "earn_opportunity_id")
_TOKEN_KEYS = ("token", "symbol", "token_symbol")
_CHAIN_KEYS = ("chain_id", "chainId")
_MAX_OPPORTUNITY = 200
_MAX_TOKEN = 32

EARN_NOTE = (
    "CoinFello's Earn view is open in the CoinFello pane beside this chat "
    "(Hermes desktop): the human browses yields with filters, opens one and "
    "deposits there, confirming in the view itself. Tell them it is open{what}. "
    "Do not prepare or execute a deposit yourself for this, and do not list "
    "yields unless they ask."
)
EARN_FALLBACK_NOTE = (
    "This CoinFello server has no Earn view for Hermes yet, so the read-only "
    "yield card is in the pane instead. Deposits cannot be made from Hermes "
    "on this server: point the human to {url} to deposit."
)
EARN_DEPOSIT_ROWS_NOTE = (
    "This CoinFello server has no Earn view for Hermes yet, so the yield card "
    "is in the pane instead. Its Deposit button on a row opens the deposit "
    "for that yield on the same card, which still asks the human to confirm "
    "in the pane. A row without one (a liquidity pool, or a listing CoinFello "
    "cannot deposit into) deposits at {url}."
)

_lock = threading.RLock()


def _first(arguments: dict, keys: tuple) -> Any:
    for key in keys:
        value = arguments.get(key)
        if value not in (None, ""):
            return value
    return None


def _plain(value: Any, limit: int, label: str) -> str:
    text = str(value).strip()
    if not text:
        return ""
    if len(text) > limit or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError(f"{label} does not look like one: {text[:40]!r}")
    return text


def _chain(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, list):  # chain_ids from a yield card call
        value = value[0] if len(value) == 1 else None
        if value is None:
            return None
    if isinstance(value, bool):
        raise ValueError("chain_id must be a number, e.g. 8453 for Base")
    try:
        chain = int(str(value).strip())
    except ValueError as exc:
        raise ValueError("chain_id must be a number, e.g. 8453 for Base") from exc
    if chain <= 0:
        raise ValueError("chain_id must be a positive number, e.g. 8453 for Base")
    return chain


def preselect(arguments: Any) -> dict:
    """What the Earn view should open on, from the model's arguments.

    An opportunity (a yield id) opens that yield; otherwise a token symbol
    and/or chain filters the list. An opportunity wins: the contract is one
    or the other. Raises ValueError, in plain words, for a value that cannot
    be meant (a chain that is not a number, control characters, ...).
    """
    if not isinstance(arguments, dict):
        return {}
    opportunity = _first(arguments, _OPPORTUNITY_KEYS)
    if opportunity is not None:
        text = _plain(opportunity, _MAX_OPPORTUNITY, "opportunity")
        if text:
            return {"opportunity": text}
    chosen: dict = {}
    token = _first(arguments, _TOKEN_KEYS)
    if token is not None and (text := _plain(token, _MAX_TOKEN, "token")):
        chosen["token"] = text
    chain_value = _first(arguments, _CHAIN_KEYS)
    chain = _chain(arguments.get("chain_ids") if chain_value is None else chain_value)
    if chain is not None:
        chosen["chain_id"] = chain
    return chosen


def frame_query(chosen: dict) -> str:
    """The preselect part of the frame URL, escaped. The pane appends it
    after ``theme``: ``<app>/embed/earn?theme=dark&<this>``.

    ``opportunity=<id>`` or ``token=<SYMBOL>&chain_id=<n>``, in that order,
    every value percent-encoded (a space is %20, never +), so no value can
    end its parameter early or add another.
    """
    pairs = []
    if chosen.get("opportunity"):
        pairs.append(("opportunity", chosen["opportunity"]))
    else:
        if chosen.get("token"):
            pairs.append(("token", chosen["token"]))
        if chosen.get("chain_id"):
            pairs.append(("chain_id", str(int(chosen["chain_id"]))))
    return urlencode(pairs, quote_via=quote, safe="")


def describe(chosen: dict) -> str:
    if chosen.get("opportunity"):
        return f" on yield {chosen['opportunity']}"
    parts = []
    if chosen.get("token"):
        parts.append(chosen["token"])
    if chosen.get("chain_id"):
        parts.append(f"chain {chosen['chain_id']}")
    return f", filtered to {' on '.join(parts)}" if parts else ""


# -- the pane's "open Earn" request ---------------------------------------------

def store_path() -> Path:
    """``<hermes home>/coinfello/earn-request.json`` (per profile when Hermes says so)."""
    try:
        from hermes_constants import get_hermes_home

        home = Path(get_hermes_home())
    except Exception:
        home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    return home / "coinfello" / "earn-request.json"


def _announce(request_id: str) -> bool:
    """Tell the desktop half to open Earn now; it also polls, for Hermes
    builds without the plugin event bridge."""
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event
    except Exception:
        return False
    try:
        broadcast_plugin_event(PLUGIN_ID, EARN_OPEN_EVENT, {"id": request_id})
    except Exception:
        return False
    return True


def _write(record: dict | None) -> None:
    path = store_path()
    with _lock:
        try:
            if record is None:
                path.unlink(missing_ok=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(record))
            os.chmod(temp, 0o600)
            temp.replace(path)
        except OSError:
            pass


def _read() -> dict | None:
    with _lock:
        try:
            record = json.loads(store_path().read_text())
        except (OSError, ValueError):
            return None
    if not isinstance(record, dict) or not isinstance(record.get("id"), str):
        return None
    if time.time() - float(record.get("created_at") or 0) > REQUEST_TTL_SECONDS:
        _write(None)
        return None
    return record


def request_open(chosen: dict, *, session_id: str = "") -> dict:
    """Leave an "open Earn" request for the pane (the newest one wins)."""
    record = {
        "id": secrets.token_hex(16),
        "preselect": dict(chosen),
        "query": frame_query(chosen),
        "session_id": str(session_id or ""),
        "created_at": time.time(),
    }
    _write(record)
    _announce(record["id"])
    return record


def pending_request() -> dict | None:
    """The request the pane has not opened yet, if any (without the session id)."""
    record = _read()
    if record is None:
        return None
    return {key: record.get(key) for key in ("id", "preselect", "query", "created_at")}


def consume_request(request_id: str) -> dict:
    """The pane opened it: drop it, so it opens once."""
    record = _read()
    if record is not None and record.get("id") == str(request_id or ""):
        _write(None)
    return {"ok": True}


def open_from_model(arguments: Any, *, session_id: str = "") -> dict:
    """``coinfello_show_card(card="earn_deposit")`` on desktop, on a server
    with the Earn embed: open the pane's Earn view. Calls no CoinFello tool."""
    if not core.signed_in(core.load_state()):
        raise core.NotSignedIn("Sign in first (coinfello_connect); the Earn view needs a session.")
    chosen = preselect(arguments)
    record = request_open(chosen, session_id=session_id)
    return {
        "ok": True,
        "card": "earn_deposit",
        "shown": "coinfello_pane",
        "view": "earn",
        "request_id": record["id"],
        "preselect": chosen,
        "note": EARN_NOTE.format(what=describe(chosen)),
    }
