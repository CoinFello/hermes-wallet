"""Activity shaping for the desktop pane, mirroring the CoinFello web app.

The pane's Activity tab must say what the CoinFello activity feed says, so the
wording here is a port of coinfello-web (``apps/web/src``), kept small and
covered by tests:

- the sentence      -> ``components/ActivityFeed/sentence.ts`` ``sentenceMessage``
- the result column -> ``components/ActivityFeed/result.ts`` ``resultMessage``
- amounts           -> ``lib/format-utils.ts`` ``formatTokenAmount`` /
                       ``formatUsdValue`` / ``truncateAddress``
- English text      -> ``i18n/messages/en.json`` ``activityFeed.*``

The data comes from the MCP ``get_activity`` contract
(``lib/mcp/read_tools.ts`` ``readActivity``): two independently read sections,
``transactions`` and ``hyperliquidFills``, each ``{data}`` or ``{error}``.
Every field is read defensively; an unknown shape degrades to a plain row
rather than an exception.

One deliberate difference from the web feed: an aggregator (LI.FI and the
like, see ``coinfello_venues``) is never named. Swaps and bridges name the
venue underneath when it is known (``venues``), and otherwise no venue.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

try:
    from .coinfello_portfolio import CHAIN_NAMES
    from .coinfello_venues import is_aggregator
except ImportError:  # loaded standalone (dashboard importer, pytest)
    from coinfello_portfolio import CHAIN_NAMES
    from coinfello_venues import is_aggregator

UNLIMITED_AMOUNT = "unlimited"
UNKNOWN_TOKEN = "Unknown"  # transactions.unknownToken

EXPLORER_TX_URL = "https://blockscan.com/tx/{hash}"
HYPERLIQUID_TX_URL = "https://app.hyperliquid.xyz/explorer/tx/{hash}"


# -- format-utils.ts -----------------------------------------------------------

def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _grouped(number: Decimal, min_dp: int, max_dp: int) -> str:
    """``toLocaleString('en-US', {min/maxFractionDigits})`` for a Decimal."""
    quantized = number.quantize(Decimal(1).scaleb(-max_dp), rounding=ROUND_HALF_UP)
    text = f"{abs(quantized):,.{max_dp}f}"
    whole, _, frac = text.partition(".")
    frac = frac.rstrip("0").ljust(min_dp, "0")
    sign = "-" if quantized < 0 else ""
    return f"{sign}{whole}.{frac}" if frac else f"{sign}{whole}"


def format_token_amount(amount: Any, symbol: str) -> str:
    """``formatTokenAmount``: 0 -> ``0.00 X``; tiny -> ``<0.001 X``; 2-6 dp."""
    number = _decimal(amount)
    if number is None or number == 0:
        return f"0.00 {symbol}"
    if number < Decimal("0.001"):
        return f"<0.001 {symbol}"
    return f"{_grouped(number, 2, 6)} {symbol}"


def format_usd_value(value: Any) -> str | None:
    """``formatUsdValue``: ``< $0.01`` below a cent, else ``$1,234.50``."""
    number = _decimal(value)
    if number is None:
        return None
    if number < Decimal("0.01"):
        return "< $0.01"
    return f"${_grouped(number, 2, 2)}"


def truncate_address(address: str, start: int = 6, end: int = 4) -> str:
    if len(address) <= start + end:
        return address
    return f"{address[:start]}...{address[-end:]}"


def chain_name(chain_id: Any) -> str | None:
    """``getChainName``: the web app's name, else ``Chain <id>``."""
    if chain_id is None:
        return None
    try:
        return CHAIN_NAMES.get(int(str(chain_id)), f"Chain {chain_id}")
    except ValueError:
        return f"Chain {chain_id}"


# -- sentence.ts -----------------------------------------------------------------

def _is_address_like(value: str) -> bool:
    if not value.startswith("0x"):
        return False
    body = value[2:]
    if "..." in body:
        head, _, tail = body.partition("...")
        return bool(head) and bool(tail) and all(c in "0123456789abcdefABCDEF" for c in head + tail)
    return len(body) == 40 and all(c in "0123456789abcdefABCDEF" for c in body)


def _symbol(leg: dict | None) -> str:
    symbol = (leg or {}).get("symbol")
    return symbol if isinstance(symbol, str) and symbol and not _is_address_like(symbol) else UNKNOWN_TOKEN


def leg_text(leg: dict | None) -> str:
    """``legText``: ``0.05 ETH``, or the bare symbol when the amount is unknown."""
    symbol = _symbol(leg)
    amount = (leg or {}).get("amount")
    if not amount or amount == UNLIMITED_AMOUNT:
        return symbol
    return format_token_amount(amount, symbol)


def _legs_text(legs: list[dict | None]) -> str:
    present = [leg_text(leg) for leg in legs if isinstance(leg, dict)]
    if not present:
        return UNKNOWN_TOKEN
    if len(present) == 1:
        return present[0]
    return ", ".join(present[:-1]) + (", and " if len(present) > 2 else " and ") + present[-1]


def _who(address: Any, wallet: str | None) -> str | None:
    """A counterparty or wallet. The pane has no account names, so the
    session's own wallet is "this wallet" and anything else is truncated."""
    if not isinstance(address, str) or not address:
        return None
    if wallet and address.lower() == wallet.lower():
        return "this wallet"
    return truncate_address(address)


def _verb(attempted: bool, done: str, tried: str) -> str:
    return tried if attempted else done


_NO_SUMMARY = {"failed": "Did not finish", "done": "Ran the automation"}


def venue_key(entry: dict) -> str:
    return f"{entry.get('chainId')}:{str(entry.get('txHash') or '').lower()}"


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def sentence_text(entry: dict, wallet: str | None = None, venues: list[str] | None = None) -> str:
    """``sentenceMessage`` rendered with the en catalog's templates.

    ``venues``: the liquidity venues/bridge resolved for this transaction.
    """
    what = _as_dict(entry.get("what"))
    status = _as_str(entry.get("status"))
    if what.get("kind") == "run":
        headline = what.get("headline")
        if isinstance(headline, str) and headline.strip():
            return headline.strip()
        return _NO_SUMMARY.get(status, "In progress")
    if what.get("kind") != "transaction":
        return "Activity on this wallet."

    attempted = what.get("attempted") is True
    label = what.get("protocol") if isinstance(what.get("protocol"), str) and what.get("protocol") else None
    routed = is_aggregator(label)  # never shown: name what is underneath, or nothing
    protocol = None if routed else label
    src = _as_dict(what.get("from")) or None
    dst = _as_dict(what.get("to")) or None
    counterparty = what.get("counterparty")
    verb = what.get("verb")

    if verb == "swapped":
        text = f"{_verb(attempted, 'Swapped', 'Tried to swap')} {leg_text(src)}"
        if dst:
            text += f" for {leg_text(dst)}"
        shown = _join(venues) if venues else protocol
        if shown:
            text += f" on {shown}"
    elif verb == "bridged":
        text = f"{_verb(attempted, 'Bridged', 'Tried to bridge')} {leg_text(src or dst)}"
        if src:
            text += f" from {chain_name(src.get('chainId'))}"
        if dst:
            text += f" to {chain_name(dst.get('chainId'))}"
        via = _join(venues) if venues else protocol
        if via:
            text += f" via {via}"
    elif verb == "sent":
        text = f"{_verb(attempted, 'Sent', 'Tried to send')} {leg_text(src or dst)}"
        who = _who(counterparty, wallet)
        if who:
            text += f" to {who}"
    elif verb == "received":
        text = f"Received {leg_text(dst or src)}"
        who = _who(counterparty, wallet)
        if who:
            text += f" from {who}"
    elif verb == "moved":
        text = f"{_verb(attempted, 'Moved', 'Tried to move')} {leg_text(src or dst)}"
        source, target = _who(entry.get("wallet"), wallet), _who(counterparty, wallet)
        if source:
            text += f" from {source}"
        if target:
            text += f" to {target}"
    elif verb == "staked":
        text = f"{_verb(attempted, 'Deposited', 'Tried to deposit')} {leg_text(src or dst)}"
        if protocol:
            text += f" into {protocol}"
    elif verb == "unstaked":
        text = f"{_verb(attempted, 'Withdrew', 'Tried to withdraw')} {leg_text(dst or src)}"
        if protocol:
            text += f" from {protocol}"
    elif verb in ("lp_deposit", "lp_withdraw"):
        adding = verb == "lp_deposit"
        text = (
            f"{_verb(attempted, 'Added' if adding else 'Removed', 'Tried to add' if adding else 'Tried to remove')} "
            f"{_legs_text([src, dst])} {'to' if adding else 'from'} a pool"
        )
        if protocol:
            text += f" on {protocol}"
    elif verb == "approved":
        leg = _as_dict(src or dst)
        # An aggregator's spender contract is "a swap contract", not its
        # address (which names the aggregator one click away).
        spender = protocol or ("a swap contract" if routed else _who(counterparty, wallet)) or "an app"
        amount = leg.get("amount")
        allowance = f"any amount of {_symbol(leg)}" if amount == UNLIMITED_AMOUNT else f"up to {leg_text(leg)}"
        text = f"{_verb(attempted, 'Allowed', 'Tried to allow')} {spender} to spend {allowance}"
    elif verb == "executed":
        text = f"{_verb(attempted, 'Called', 'Tried to call')} a contract"
        if protocol:
            text += f" on {protocol}"
    else:
        text = "Transaction on this wallet"
    text += "."

    more = what.get("moreCount")
    if isinstance(more, int) and not isinstance(more, bool) and more > 0:
        text += f" (+{more} more step{'' if more == 1 else 's'})"
    return text


# -- result.ts -------------------------------------------------------------------

_FAILURES = {"reverted": "reverted", "did_not_finish": "did not finish", "reported": "failed"}
_PLAIN_RESULTS = {"no_move": "no move", "acted": "done", "running": "running", "unknown": "not recorded"}


def result_of(result: Any, status: Any) -> dict:
    """``resultMessage``: text, tone, and a sign only on a settled in/out."""
    result = _as_dict(result)
    kind = _as_str(result.get("kind"))
    if kind == "amount":
        leg = _as_dict(result.get("leg"))
        amount = format_usd_value(leg.get("amountUsd")) if leg.get("amountUsd") else None
        amount = amount or leg_text(leg)
        sign = None
        if status == "done" and result.get("flow") == "in":
            sign = "+"
        if status == "done" and result.get("flow") == "out":
            sign = "-"
        return {"text": f"{sign or ''}{amount}", "tone": "positive" if sign == "+" else "default"}
    if kind == "failed":
        code = _as_str(_as_dict(result.get("reason")).get("code"))
        return {"text": _FAILURES.get(code, "failed"), "tone": "error"}
    return {"text": _PLAIN_RESULTS.get(kind, ""), "tone": "default"}


# -- rows --------------------------------------------------------------------------

_ACTORS = {"fello": "Fello", "you": "You", "incoming": "Incoming"}
_STATUS_LABELS = {"failed": "Failed", "running": "Running now", "pending": "Pending"}


def _tx_url(tx_hash: Any) -> str | None:
    if isinstance(tx_hash, str) and len(tx_hash) == 66 and tx_hash.startswith("0x"):
        return EXPLORER_TX_URL.format(hash=tx_hash)
    return None


_VERBS = frozenset({"swapped", "bridged", "sent", "received", "moved", "staked", "unstaked",
                    "lp_deposit", "lp_withdraw", "approved", "executed"})


def _row_verb(entry: dict) -> str | None:
    what = _as_dict(entry.get("what"))
    if what.get("kind") == "run":
        return "run"
    verb = what.get("verb")
    return verb if verb in _VERBS else None


def transaction_row(entry: dict, wallet: str | None = None, venues: dict | None = None) -> dict:
    status = _as_str(entry.get("status"))
    if status not in ("done", "failed", "running", "pending"):
        status = "done"
    actor = _as_str(entry.get("actor"))
    if actor not in _ACTORS:
        actor = "you"
    source = _ACTORS[actor]
    automation = entry.get("automation")
    if actor == "fello" and isinstance(automation, str) and automation.strip():
        source = f"Fello · {automation.strip()}"
    tx_hash = entry.get("txHash")
    return {
        "key": f"tx:{entry.get('chainId')}:{tx_hash}" if tx_hash else f"run:{entry.get('at')}:{sentence_text(entry, wallet)}",
        "kind": "transaction",
        "at": entry.get("at"),
        "status": status,
        "status_label": _STATUS_LABELS.get(status),
        "actor": actor,
        # What happened, for the row's icon: a transaction verb, or "run".
        "verb": _row_verb(entry),
        "source": source,
        "sentence": sentence_text(entry, wallet, (venues or {}).get(venue_key(entry))),
        "result": result_of(entry.get("result"), status),
        "chain_id": entry.get("chainId"),
        "chain_name": chain_name(entry.get("chainId")),
        "tx_url": _tx_url(tx_hash),
    }


def fill_row(fill: dict) -> dict:
    """A Hyperliquid fill: "Open Long 0.5 ETH at $3,120.40", PnL when it closed."""
    coin = fill.get("coin") if isinstance(fill.get("coin"), str) and fill.get("coin") else "?"
    direction = fill.get("direction") if isinstance(fill.get("direction"), str) and fill.get("direction") else (
        "Buy" if fill.get("side") == "buy" else "Sell"
    )
    size = _decimal(fill.get("size"))
    price = format_usd_value(fill.get("price"))
    text = f"{direction} {_grouped(size, 0, 6) if size is not None else ''} {coin}".replace("  ", " ")
    if price:
        text += f" at {price}"
    text += "."
    if fill.get("liquidation") is True:
        text = f"Liquidated: {text}"

    pnl = _decimal(fill.get("closedPnl"))
    if pnl is not None and pnl != 0:
        shown = format_usd_value(abs(pnl)) or ""
        result = {"text": f"{'+' if pnl > 0 else '-'}{shown}", "tone": "positive" if pnl > 0 else "negative"}
    else:
        notional = None
        price_d = _decimal(fill.get("price"))
        if price_d is not None and size is not None:
            notional = format_usd_value(price_d * size)
        result = {"text": notional or "", "tone": "default"}

    tx_hash = fill.get("txHash")
    return {
        "key": f"fill:{fill.get('orderId')}:{fill.get('at')}:{tx_hash}",
        "kind": "fill",
        "at": fill.get("at"),
        "status": "done",
        "status_label": None,
        "actor": "hyperliquid",
        "verb": "fill",
        "source": "Hyperliquid",
        "sentence": text,
        "result": result,
        "chain_id": None,
        "chain_name": None,
        "tx_url": HYPERLIQUID_TX_URL.format(hash=tx_hash)
        if isinstance(tx_hash, str) and tx_hash.startswith("0x") and tx_hash.strip("0x")
        else None,
    }


def _section(raw: Any) -> tuple[dict | None, str | None]:
    """``{data}`` -> (data, None); ``{error}`` -> (None, error)."""
    if not isinstance(raw, dict):
        return None, None
    if isinstance(raw.get("error"), str):
        return None, raw["error"]
    data = raw.get("data")
    return (data, None) if isinstance(data, dict) else (None, None)


def venue_jobs(raw: dict) -> list[dict]:
    """Settled swaps/bridges whose label is an aggregator (or missing): the
    transactions worth asking ``coinfello_venues`` about."""
    transactions, _ = _section(raw.get("transactions"))
    jobs = []
    for entry in (transactions or {}).get("entries") or []:
        if not isinstance(entry, dict) or entry.get("status") != "done":
            continue
        what = _as_dict(entry.get("what"))
        label = what.get("protocol")
        if what.get("kind") != "transaction" or not (label is None or is_aggregator(label)):
            continue
        tx_hash, chain_id = entry.get("txHash"), entry.get("chainId")
        if what.get("verb") in ("swapped", "bridged") and isinstance(tx_hash, str) and chain_id is not None:
            jobs.append({"kind": "swap" if what.get("verb") == "swapped" else "bridge",
                         "chain_id": chain_id, "tx_hash": tx_hash})
    return jobs


def shape_activity(raw: dict, *, include_fills: bool = True, venues: dict | None = None) -> dict:
    """One page of the pane's Activity tab from a ``get_activity`` reply."""
    wallet = raw.get("address") if isinstance(raw.get("address"), str) else None
    transactions, tx_error = _section(raw.get("transactions"))
    entries = (transactions or {}).get("entries")
    rows = [transaction_row(e, wallet, venues) for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    next_cursor = (transactions or {}).get("nextCursor")

    fills: list[dict] = []
    fills_error = None
    if include_fills:
        fill_data, fills_error = _section(raw.get("hyperliquidFills"))
        raw_fills = (fill_data or {}).get("fills")
        if isinstance(raw_fills, list):
            fills = [fill_row(f) for f in raw_fills if isinstance(f, dict)]

    return {
        "ok": True,
        "rows": rows,
        "fills": fills,
        "next_cursor": next_cursor if isinstance(next_cursor, str) and next_cursor else None,
        "incomplete": bool((transactions or {}).get("incomplete")),
        "error": tx_error,
        "fills_error": fills_error,
    }
