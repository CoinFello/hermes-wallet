"""Agent trades: prepare -> human approval -> execute -> verify delivery.

The agent can prepare a swap, bridge or send (``prepare_swap`` /
``prepare_send`` on the server: validated, priced, stored as a single-use
intent for two minutes; nothing moves). Executing one goes through Hermes'
human-approval gate: the plugin's ``pre_tool_call`` hook asks the human to
approve ``coinfello_execute`` with the SERVER's summary of that intent, cached
here when it was prepared, never text the model wrote. An intent this process
did not prepare is refused outright.

``coinfello_chat`` is gated the same way, showing the exact message: Fello
can act on-chain from any message without asking again, so a human sees each
one before it is sent.

After a bridge, ``transfer_status`` says what actually arrived (LI.FI's
status, folded into one ``outcome``): a bridge can finish refunded, or
deliver a different token than quoted.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

try:  # package import inside Hermes; plain import in tests
    from . import coinfello_core as core
except ImportError:  # pragma: no cover
    import coinfello_core as core  # type: ignore[no-redef]

#: Server-side intents expire after 120 s; keep ours a little shorter so the
#: approval prompt never shows something the server will refuse as expired.
INTENT_TTL_FALLBACK_SECONDS = 110
LIFI_STATUS_URL = "https://li.quest/v1/status"

_intents: dict[str, dict[str, Any]] = {}
_intents_lock = threading.Lock()


# -- the intent cache (what the approval prompt shows) -----------------------

def remember_intent(intent_id: str, summary: dict, expires_in: Any) -> None:
    try:
        ttl = max(1.0, float(expires_in) - 10.0)
    except (TypeError, ValueError):
        ttl = float(INTENT_TTL_FALLBACK_SECONDS)
    now = time.monotonic()
    with _intents_lock:
        for key in [k for k, v in _intents.items() if v["expires"] < now]:
            del _intents[key]
        _intents[intent_id] = {"summary": summary, "expires": now + ttl}


def recall_intent(intent_id: str) -> dict | None:
    """The cached summary for a live intent, or None (unknown or expired)."""
    with _intents_lock:
        entry = _intents.get(intent_id)
    if not entry or entry["expires"] < time.monotonic():
        return None
    return entry["summary"]


def intent_seconds_left(intent_id: str) -> int:
    """Seconds until a cached intent stops being executable (0 when gone)."""
    with _intents_lock:
        entry = _intents.get(intent_id)
    if not entry:
        return 0
    return max(0, int(entry["expires"] - time.monotonic()))


def forget_intent(intent_id: str) -> None:
    with _intents_lock:
        _intents.pop(intent_id, None)


# -- human-readable summaries -----------------------------------------------

def _usd(value: Any) -> str | None:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return None


def describe(summary: dict) -> str:
    """One plain sentence for the approval prompt, from the server summary."""
    kind = summary.get("kind")
    if kind == "send":
        token = (summary.get("token") or {}).get("symbol") or "?"
        value = _usd(summary.get("valueUsd"))
        worth = f" (~{value})" if value else ""
        return (
            f"Send {summary.get('amount')} {token}{worth} on "
            f"{summary.get('chainName') or summary.get('chainId')} to "
            f"{summary.get('recipient')}. Irreversible."
        )
    src = summary.get("from") or {}
    dst = summary.get("to") or {}
    least = dst.get("minimumAmount") or dst.get("amount")
    costs = ", ".join(
        part
        for part in (
            f"gas ~{_usd(summary.get('gasUsd'))}" if _usd(summary.get("gasUsd")) else "",
            f"fees ~{_usd(summary.get('feesUsd'))}" if _usd(summary.get("feesUsd")) else "",
        )
        if part
    )
    if kind == "bridge":
        bridges = summary.get("bridges") or []
        via = f" via {', '.join(bridges)}" if bridges else ""
        text = (
            f"Bridge {src.get('amount')} {src.get('symbol')} on "
            f"{summary.get('fromChainName')} to at least {least} {dst.get('symbol')} "
            f"on {summary.get('toChainName')}{via} (expected {dst.get('amount')}"
        )
    else:
        text = (
            f"Swap {src.get('amount')} {src.get('symbol')} for at least {least} "
            f"{dst.get('symbol')} on {summary.get('fromChainName')} "
            f"(expected {dst.get('amount')}"
        )
    return text + (f"; {costs})." if costs else ").")


# -- prepare / execute --------------------------------------------------------

def _prepared(result: Any) -> dict:
    if not isinstance(result, dict) or not result.get("intentId"):
        raise RuntimeError(core._text(result))
    summary = result.get("summary") or {}
    remember_intent(result["intentId"], summary, result.get("expiresInSeconds"))
    return {
        "ok": True,
        "intent_id": result["intentId"],
        "expires_in_seconds": result.get("expiresInSeconds"),
        "summary": summary,
        "description": describe(summary),
    }


def prepare_swap(args: dict) -> dict:
    if not core.supports("prepare_swap"):
        raise RuntimeError(
            "This CoinFello server cannot prepare trades yet (no prepare_swap). "
            "Ask the human to use CoinFello directly; do not route the trade "
            "through coinfello_chat instead without telling them."
        )
    payload: dict[str, Any] = {
        "from_chain_id": int(args.get("from_chain_id") or 0),
        "from_token": str(args.get("from_token") or "").strip(),
        "to_token": str(args.get("to_token") or "").strip(),
    }
    if not payload["from_chain_id"]:
        raise ValueError("from_chain_id is required")
    if not payload["from_token"] or not payload["to_token"]:
        raise ValueError("from_token and to_token are required")
    payload["amount"] = core.normalize_amount(args.get("amount"))
    if args.get("to_chain_id"):
        payload["to_chain_id"] = int(args["to_chain_id"])
    if args.get("slippage") is not None:
        payload["slippage"] = float(args["slippage"])
    return _prepared(core.trading_call("prepare_swap", payload))


def prepare_send(args: dict) -> dict:
    prepared = core.prepare_send(
        args.get("chain_id"), str(args.get("token") or ""),
        str(args.get("amount") or ""), str(args.get("recipient") or ""),
    )
    summary = prepared.get("summary") or {}
    remember_intent(prepared["intent_id"], summary, prepared.get("expires_in_seconds"))
    return {**prepared, "description": describe(summary)}


def execute(intent_id: str) -> dict:
    """Run an intent the human just approved (the hook made sure of that)."""
    intent_id = str(intent_id or "").strip()
    summary = recall_intent(intent_id)
    if summary is None:
        # The hook refuses this before we get here; belt and braces.
        raise ValueError("Unknown or expired intent: prepare it again.")
    forget_intent(intent_id)
    result = core.execute_intent(intent_id)
    result["summary"] = describe(summary)
    if result.get("ok") and summary.get("kind") == "bridge" and result.get("transaction_hash"):
        result["next"] = (
            "Only the source chain is confirmed. Call coinfello_transfer_status "
            "with transaction_hash in a minute or two to see what arrived; a "
            "bridge can be refunded or deliver a different token."
        )
    if result.get("price_moved") or result.get("route_changed"):
        result["next"] = (
            "Nothing was sent. Prepare it again and show the human the new "
            "summary; do not execute without their approval."
        )
    return result


# -- the approval hook --------------------------------------------------------

def approval_directive(tool_name: str, args: dict | None) -> dict | None:
    """``pre_tool_call`` directive for the tools that move funds."""
    args = args if isinstance(args, dict) else {}
    if tool_name == "coinfello_execute":
        intent_id = str(args.get("intent_id") or "").strip()
        summary = recall_intent(intent_id)
        if summary is None:
            return {
                "action": "block",
                "message": (
                    "coinfello_execute refused: that intent_id was not prepared "
                    "in this session, or it expired (intents last two minutes). "
                    "Call coinfello_prepare_swap / coinfello_prepare_send again, "
                    "show the human the summary, then execute the new intent_id."
                ),
            }
        return {
            "action": "approve",
            "message": "CoinFello, ON-CHAIN from your automation wallet: " + describe(summary),
            # One grain per intent: an [a]lways answer can never cover another
            # trade, and an intent only runs once anyway.
            "rule_key": f"coinfello_execute:{intent_id}",
        }
    if tool_name == "coinfello_chat":
        message = str(args.get("message") or "").strip()
        if not message:
            return None  # the handler rejects it
        shown = message if len(message) <= 500 else message[:500] + "…"
        digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:12]
        return {
            "action": "approve",
            "message": (
                "Send this to Fello, CoinFello's agent, which can act ON-CHAIN "
                f"from your automation wallet without asking again: \"{shown}\""
            ),
            "rule_key": f"coinfello_chat:{digest}",
        }
    return None


# -- delivery status ----------------------------------------------------------

def outcome_of(status: str | None, substatus: str | None) -> str:
    if status == "FAILED":
        return "failed"
    if status != "DONE":
        return "pending"
    if substatus == "REFUNDED":
        return "refunded"
    if substatus == "PARTIAL":
        return "wrong_token"
    return "completed"


_NEXT = {
    "pending": "Still settling or not indexed yet; ask again in 30-60 seconds.",
    "completed": "Done: the requested token arrived.",
    "wrong_token": (
        "Finished, but a different token arrived than requested (see "
        "received). Tell the human plainly; any follow-up trade needs a new "
        "prepare and their approval."
    ),
    "refunded": (
        "Did not happen: the source token was refunded minus fees. Tell the "
        "human; retrying needs a new prepare and their approval."
    ),
    "failed": "Failed. Tell the human; check explorer_link before retrying.",
}


def _units(amount: Any, decimals: Any) -> str | None:
    if not isinstance(amount, str) or not amount.isdigit() or not isinstance(decimals, int):
        return None
    if decimals == 0:
        return str(int(amount))
    whole = amount.rjust(decimals + 1, "0")
    integer, fraction = whole[:-decimals], whole[-decimals:].rstrip("0")
    return f"{int(integer)}.{fraction}" if fraction else str(int(integer))


def _leg(leg: Any) -> dict | None:
    if not isinstance(leg, dict):
        return None
    token = leg.get("token") or {}
    return {
        "chain_id": leg.get("chainId") or token.get("chainId"),
        "symbol": token.get("symbol"),
        "address": token.get("address"),
        "amount": _units(leg.get("amount"), token.get("decimals")),
        "tx_hash": leg.get("txHash"),
    }


def _open(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 (fixed host)


def _lifi_status(tx_hash: str) -> dict:
    """Direct LI.FI read, for servers without get_transfer_status."""
    request = urllib.request.Request(
        f"{LIFI_STATUS_URL}?txHash={tx_hash}",
        # LI.FI's edge answers 403 to Python's default User-Agent.
        headers={"accept": "application/json", "user-agent": "hermes-coinfello-plugin/0.1"},
    )
    try:
        with _open(request, 15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"tx_hash": tx_hash, "status": "NOT_FOUND", "outcome": "pending",
                    "delivered_requested_token": None, "next": _NEXT["pending"]}
        raise RuntimeError(f"LI.FI status read failed: HTTP {exc.code}") from exc
    wallet = (core.load_state().get("wallet_address") or "").lower()
    if wallet and str(data.get("fromAddress") or "").lower() not in ("", wallet):
        raise ValueError("That transfer was not sent from this CoinFello automation wallet.")
    outcome = outcome_of(data.get("status"), data.get("substatus"))
    requested = ((data.get("quote") or {}).get("action") or {}).get("toToken") or {}
    received = _leg(data.get("receiving")) if outcome != "pending" else None
    delivered: bool | None = {"completed": True, "pending": None}.get(outcome, False)
    if delivered and requested.get("address") and received and received.get("address") \
            and requested["address"].lower() != str(received["address"]).lower():
        delivered = False
    return {
        "tx_hash": tx_hash,
        "status": data.get("status"),
        "substatus": data.get("substatus"),
        "message": data.get("substatusMessage"),
        "outcome": outcome,
        "delivered_requested_token": delivered,
        "tool": data.get("tool"),
        "sending": _leg(data.get("sending")),
        "requested": {"chain_id": requested.get("chainId"), "symbol": requested.get("symbol"),
                      "address": requested.get("address")} if requested else None,
        "received": received,
        "explorer_link": data.get("lifiExplorerLink"),
        "next": _NEXT[outcome],
        "source": "li.fi (direct; this CoinFello server has no get_transfer_status)",
    }


def transfer_status(tx_hash: str) -> Any:
    tx_hash = str(tx_hash or "").strip()
    if not (tx_hash.startswith("0x") and len(tx_hash) == 66):
        raise ValueError("tx_hash must be a 0x-prefixed 32-byte transaction hash")
    if core.supports("get_transfer_status"):
        return core.call("get_transfer_status", {"tx_hash": tx_hash})
    if not core.signed_in():
        raise core.NotSignedIn("Connect CoinFello first.")
    return _lifi_status(tx_hash)
