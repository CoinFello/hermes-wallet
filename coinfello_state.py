"""Configuration and credential state for the CoinFello plugin.

The MCP session token is a secret that can move funds, so it lives under
``providers.coinfello`` in the profile's ``auth.json`` (where the core auth
store keeps provider credentials), written under the auth-store lock. Outside
a Hermes process (tests, bare checkouts) it falls back to a 0600 JSON file
next to this module so the code stays runnable and testable.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MCP_URL = "https://app.coinfello.com/api/mcp"
ENV_URL_VAR = "COINFELLO_MCP_URL"
PROVIDER = "coinfello"
FALLBACK_FILE = Path(__file__).resolve().parent / ".coinfello-state.json"


def _env_file_value(name: str) -> str:
    """Honor the profile's ``.env`` the way Hermes does, when it is available."""
    try:
        from hermes_cli.config import get_env_value

        return get_env_value(name) or ""
    except Exception:
        return ""


def mcp_url() -> str:
    """The streamable-HTTP endpoint: env var (process or .env) over the default."""
    for source in (os.environ.get(ENV_URL_VAR), _env_file_value(ENV_URL_VAR)):
        raw = (source or "").strip()
        if raw:
            return raw.rstrip("/")
    return DEFAULT_MCP_URL


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auth_helpers():
    """The Hermes auth-store operations, or None outside a Hermes process."""
    try:
        from hermes_cli.auth import (
            _auth_store_lock,
            _load_auth_store,
            _load_provider_state,
            _save_auth_store,
            _store_provider_state,
        )

        return _auth_store_lock, _load_auth_store, _load_provider_state, _save_auth_store, _store_provider_state
    except Exception:
        return None


def load_state() -> dict:
    """The stored session state (``session_token``, ``wallet_address``, ...)."""
    helpers = _auth_helpers()
    if helpers is not None:
        _auth_store_lock, _load_auth_store, _load_provider_state, _save_auth_store, _store_provider_state = helpers
        try:
            with _auth_store_lock():
                store = _load_auth_store()
                state = _load_provider_state(store, PROVIDER)
            return dict(state) if isinstance(state, dict) else {}
        except Exception:
            return {}
    try:
        return json.loads(FALLBACK_FILE.read_text())
    except Exception:
        return {}


def save_state(patch: dict) -> dict:
    """Merge ``patch`` into the stored state and return the merged result."""
    helpers = _auth_helpers()
    if helpers is not None:
        _auth_store_lock, _load_auth_store, _load_provider_state, _save_auth_store, _store_provider_state = helpers
        try:
            with _auth_store_lock():
                store = _load_auth_store()
                state = dict(_load_provider_state(store, PROVIDER) or {})
                state.update(patch)
                state["saved_at"] = _now_iso()
                _store_provider_state(store, PROVIDER, state, set_active=False)
                _save_auth_store(store)
            return state
        except Exception:
            pass  # fall through to the file below
    state = {}
    try:
        state = json.loads(FALLBACK_FILE.read_text())
    except Exception:
        pass
    state.update(patch)
    state["saved_at"] = _now_iso()
    FALLBACK_FILE.write_text(json.dumps(state, indent=2))
    try:
        os.chmod(FALLBACK_FILE, 0o600)
    except OSError:
        pass
    return state


def clear_state() -> dict:
    """Forget the session entirely (token, wallet, pending approval)."""
    return save_state(
        {
            "session_token": "",
            "wallet_address": "",
            "expires_at": "",
            "email": "",
            "pending_approval_id": "",
        }
    )


def signed_in(state: dict | None = None) -> bool:
    state = state if state is not None else load_state()
    return bool((state.get("session_token") or "").strip())