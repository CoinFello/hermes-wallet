"""CoinFello plugin — dashboard backend routes.

Mounted at ``/api/plugins/coinfello/`` by the dashboard plugin system. This
is the HTTP surface the desktop pane talks to (``ctx.rest``); it delegates
everything to ``coinfello_core`` and never raises out to the client (the
plugin contract), folding every failure into ``{"ok": false, "error": ...}``.

Endpoints are plain functions with explicit signatures: FastAPI builds its
request parsing from the signature, so a generic ``*args, **kwargs`` wrapper
would turn those into required query parameters (HTTP 422 on every call).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# Loaded standalone by the dashboard importer (spec_from_file_location), so
# package-relative imports are unavailable: put the plugin directory on the
# path and import the service modules directly.
_PLUGIN_DIR = Path(__file__).resolve().parent.parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from fastapi import APIRouter  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import coinfello_cards as cards  # noqa: E402
import coinfello_core as core  # noqa: E402

router = APIRouter()


def _safe(action: Callable[[], Any]) -> Any:
    """Run ``action``; render any failure as ``{"ok": false, "error": ...}``."""
    try:
        return action()
    except core.NotSignedIn as exc:
        return {"ok": False, "error": f"Not signed in to CoinFello. {exc}"}
    except core.NeedsTradingAccess:
        return {
            "ok": False,
            "needs_trading_access": True,
            "error": "This session is read-only. Enable trading to send or swap.",
        }
    except (core.MCPError, ValueError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # plugin contract: never raise out
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


class VerifyBody(BaseModel):
    email: str
    code: str


class ApprovalBody(BaseModel):
    approval_id: Optional[str] = None


class ConnectBody(BaseModel):
    """``email`` only matters on servers without browser sign-in."""

    email: Optional[str] = None


@router.get("/status")
def status():
    return _safe(core.status)


@router.post("/connect")
def connect(body: ConnectBody):
    return _safe(lambda: core.connect(body.email or ""))


@router.post("/verify")
def verify(body: VerifyBody):
    return _safe(lambda: core.verify(body.email, body.code))


@router.post("/approval")
def approval(body: ApprovalBody):
    return _safe(lambda: core.poll_approval(body.approval_id))


@router.post("/cancel-sign-in")
def cancel_sign_in():
    return _safe(core.cancel_sign_in)


@router.post("/disconnect")
def disconnect():
    return _safe(lambda: core.disconnect(wait=False))


@router.get("/wallet")
def wallet():
    return _safe(core.wallet)


@router.get("/portfolio")
def portfolio():
    return _safe(core.portfolio)


class SendBody(BaseModel):
    chain_id: int
    token: str
    amount: str
    recipient: str


class IntentBody(BaseModel):
    intent_id: str


@router.post("/send/prepare")
def send_prepare(body: SendBody):
    return _safe(lambda: core.prepare_send(body.chain_id, body.token, body.amount, body.recipient))


@router.post("/intent/execute")
def intent_execute(body: IntentBody):
    return _safe(lambda: core.execute_intent(body.intent_id))


@router.post("/embed-token")
def embed_token():
    return _safe(lambda: core.embed_token("swap"))


class LimitBody(BaseModel):
    """``limit_usd`` None means read only."""

    limit_usd: Optional[float] = None


@router.post("/limit")
def limit(body: LimitBody):
    return _safe(lambda: core.change_daily_limit(body.limit_usd))


@router.post("/limit/poll")
def limit_poll():
    return _safe(core.poll_limit_change)


@router.post("/limit/cancel")
def limit_cancel():
    return _safe(core.cancel_limit_change)


@router.post("/forget-account")
def forget_account():
    """'Use a different account' on the sign-in screen."""

    def run():
        core.forget_account_hint()
        return {"ok": True}

    return _safe(run)


# -- MCP App cards (coinfello_show_card) -----------------------------------------
# The pane mounts each card in a sandboxed frame and relays its bridge here.
# coinfello_cards decides what a card may call; /call never runs a tool that
# moves funds, it returns the confirmation, and only /execute (the pane's
# Confirm button) runs it.


class CardCallBody(BaseModel):
    tool: str
    arguments: Optional[Dict[str, Any]] = None


class CardExecuteBody(BaseModel):
    confirm_id: str


@router.get("/cards")
def cards_list():
    return _safe(lambda: {"ok": True, "cards": cards.list_cards()})


@router.get("/cards/{card_id}")
def card_document(card_id: str, theme: Optional[str] = None):
    return _safe(lambda: cards.card_document(card_id, theme or ""))


@router.post("/cards/{card_id}/call")
def card_call(card_id: str, body: CardCallBody):
    return _safe(lambda: cards.card_call(card_id, body.tool, body.arguments or {}))


@router.post("/cards/{card_id}/execute")
def card_execute(card_id: str, body: CardExecuteBody):
    return _safe(lambda: cards.card_execute(card_id, body.confirm_id))


@router.post("/cards/{card_id}/dismiss")
def card_dismiss(card_id: str):
    return _safe(lambda: cards.dismiss_card(card_id))
