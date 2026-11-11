"""Configuration and local (non-secret) state for the CoinFello plugin.

The plugin holds no credential. CoinFello sign-in is the ``coinfello`` entry
under ``oauth:`` in ``plugin.yaml``: the human runs
``hermes auth add coinfello:coinfello`` once, Hermes stores and refreshes the
grant, and every request goes through Hermes's ``credentialed_provider_request``,
which attaches the bearer itself (see ``coinfello_mcp``).

What is kept here is what the pane shows between requests: whether the last
request found a sign-in, the wallet address, the access level and a pending
limit change. It lives in Hermes's per-plugin state store
(``plugin-data/coinfello/state.json``). Outside a Hermes process (tests, bare
checkouts) it falls back to a JSON file next to this module.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

#: CoinFello's MCP endpoint. Fixed: the OAuth bearer may only be sent to the
#: hosts plugin.yaml declares, so the endpoint is not configurable.
DEFAULT_MCP_URL = "https://app.coinfello.com/api/mcp"
#: The plugin name and its ``oauth:`` entry id: ``hermes auth add coinfello:coinfello``.
PLUGIN_NAME = "coinfello"
OAUTH_ID = "coinfello"
#: The variable Hermes reads the OAuth client id from (declared in plugin.yaml).
CLIENT_ID_ENV = "COINFELLO_OAUTH_CLIENT_ID"
#: CoinFello's public client id for this plugin; not a secret (PKCE protects the code).
CLIENT_ID = "coinfello-hermes"
SIGN_IN_COMMAND = f"hermes auth add {PLUGIN_NAME}:{OAUTH_ID}"
SIGN_OUT_COMMAND = f"hermes auth logout {PLUGIN_NAME}:{OAUTH_ID}"

_STATE_KEY = "session"
FALLBACK_FILE = Path(__file__).resolve().parent / ".coinfello-state.json"


def mcp_url() -> str:
    return DEFAULT_MCP_URL


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plugin_state():
    """Hermes's state store for this plugin, or None outside a Hermes process."""
    try:
        from hermes_cli.plugins_state import PluginState

        return PluginState(PLUGIN_NAME)
    except Exception:
        return None


def _read_fallback() -> dict:
    try:
        data = json.loads(FALLBACK_FILE.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_state() -> dict:
    """The cached state (``signed_in``, ``wallet_address``, ``access``, ...)."""
    store = _plugin_state()
    if store is not None:
        try:
            value = store.get(_STATE_KEY, {})
            return dict(value) if isinstance(value, dict) else {}
        except Exception:
            return {}
    return _read_fallback()


def save_state(patch: dict) -> dict:
    """Merge ``patch`` into the cached state and return the merged result."""
    state = load_state()
    state.update(patch)
    state["saved_at"] = _now_iso()
    store = _plugin_state()
    if store is not None:
        try:
            store.set(_STATE_KEY, state)
            return state
        except Exception:
            pass  # fall through to the file below
    FALLBACK_FILE.write_text(json.dumps(state, indent=2))
    return state


def clear_state() -> dict:
    """Forget the cached session (wallet, access, anything pending).

    Keeps a non-secret hint of the account (wallet address), shown on the pane
    so the human signs in to the same account next time.
    """
    state = load_state()
    hint_wallet = state.get("wallet_address") or state.get("last_wallet_address") or ""
    hint_email = state.get("signed_in_as") or state.get("last_signed_in_as") or ""
    return save_state(
        {
            "signed_in": False,
            "wallet_address": "",
            "expires_at": "",
            "signed_in_as": "",
            "access": None,
            "daily_limit_usd": None,
            "pending_limit_change_id": "",
            "pending_limit_change_url": "",
            "pending_limit_requested": None,
            "last_wallet_address": hint_wallet,
            "last_signed_in_as": hint_email,
        }
    )


def forget_account_hint() -> dict:
    """'Use a different account': forget the remembered account."""
    return save_state({"last_wallet_address": "", "last_signed_in_as": ""})


def signed_in(state: dict | None = None) -> bool:
    """Whether the last request to CoinFello went through with Hermes's sign-in.

    A cache, not a credential: every request asks Hermes, and a request that
    finds no sign-in flips it back (``coinfello_core.call``).
    """
    state = state if state is not None else load_state()
    return bool(state.get("signed_in"))
