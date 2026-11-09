"""Portfolio shaping for the desktop pane, mirroring the CoinFello web app.

The pane must show the same numbers the CoinFello Portfolio view shows, so
every rule here is a port of a named web-app function (coinfello-web,
``apps/web/src``), kept deliberately small and covered by tests:

- grouping by network        -> ``components/AutomationPage/automationWalletBalance.ts``
                                 ``selectFundedNetworkBalances``
- portfolio 24h change       -> ``lib/portfolio/valuation.ts`` ``calculate24hChange``
                                 and ``app/portfolio/portfolioTotals.ts``
- balance / USD formatting   -> ``components/Portfolio/TokenRow.tsx``
- token icon fallback        -> ``components/Portfolio/TokenIcon.tsx``

The data itself comes from the MCP ``get_balances`` contract; this module
only shapes it. It reads optional fields defensively (``chainName``,
``logoUrl``) so it works against servers that predate them.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

METAMASK_ICON_URL = "https://static.cx.metamask.io/api/v1/tokenIcons/{chain}/{address}.png"

#: Fallback network names for servers whose ``get_balances`` predates the
#: ``chainName`` field. A snapshot of coinfello-web's ``CHAIN_NAMES``
#: (``lib/default_chains.ts``, from ``@hyperplay/chains`` metadata), which is
#: what the Portfolio view's network filter shows. The server's ``chainName``
#: always wins when present, so this only fills the gap until it deploys.
CHAIN_NAMES: dict[int, str] = {
    1: "Ethereum Mainnet",
    10: "OP Mainnet",
    56: "BNB Smart Chain Mainnet",
    130: "Unichain",
    137: "Polygon Mainnet",
    143: "Monad",
    4663: "Robinhood Chain",
    5000: "Mantle",
    8453: "Base",
    42161: "Arbitrum One",
    43114: "Avalanche C-Chain",
    57073: "Ink",
    59144: "Linea",
    84532: "Base Sepolia Testnet",
    534352: "Scroll",
    747474: "katana",
    11155111: "Ethereum Sepolia",
}


def chain_name(token: dict) -> str:
    """Server-provided name, else the web app's name, else ``Chain <id>``."""
    named = token.get("chainName")
    if isinstance(named, str) and named.strip() and not named.startswith("Chain "):
        return named
    chain_id = token.get("chainId")
    try:
        return CHAIN_NAMES.get(int(str(chain_id)), f"Chain {chain_id}")
    except ValueError:
        return f"Chain {chain_id}"


# -- formatting (TokenRow.tsx) -------------------------------------------------

def format_balance(balance: Any) -> str:
    """``new BigNumber(b).toFormat(4).replace(/(\\.\\d{2})0+$/, '$1')``."""
    try:
        value = Decimal(str(balance))
    except (InvalidOperation, ValueError):
        return str(balance)
    text = f"{value.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP):,.4f}"
    whole, _, frac = text.partition(".")
    frac = frac.rstrip("0")
    return f"{whole}.{frac.ljust(2, '0')}"


def format_usd(value: float | None) -> str:
    """en-US currency, narrow symbol, exactly two decimals; em dash when unknown."""
    if value is None:
        return "—"
    amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def format_change(pct: float | None) -> str | None:
    """``+1.23%`` / ``-1.23%``, or None when there is no 24h figure."""
    if pct is None:
        return None
    return f"{'+' if pct >= 0 else '-'}{abs(pct):.2f}%"


# -- valuation (valuation.ts, portfolioTotals.ts) ----------------------------

def change_24h_pct(tokens: list[dict]) -> float:
    """Value-weighted 24h change, as a percentage of the PREVIOUS total.

    Port of ``calculate24hChange``: priced tokens only; changes at or below
    -99% are skipped (their previous value is near zero and would swing the
    figure wildly), as is any token whose previous value is under a cent.
    """
    total_change = 0.0
    total_previous = 0.0
    for token in tokens:
        value = token.get("valueUsd")
        if token.get("priceUsd") is None or not value:
            continue
        pct = token.get("change24hPct")
        if pct is not None and pct > -99:
            previous = value / (1 + pct / 100)
            if previous >= 0.01:
                total_change += value - previous
                total_previous += previous
            else:
                total_previous += value
        else:
            total_previous += value
    return (total_change / total_previous) * 100 if total_previous > 0 else 0.0


def change_24h_amount(total: float, pct: float) -> float:
    """The dollar move behind ``pct``, recovered by discounting (portfolioTotals.ts)."""
    growth = 1 + pct / 100
    previous = total / growth if growth > 0 else 0.0
    return total - previous


# -- grouping (automationWalletBalance.ts) -----------------------------------

def _icon_fallback(chain_id: Any, address: Any) -> str | None:
    if not chain_id or not address:
        return None
    return METAMASK_ICON_URL.format(chain=chain_id, address=str(address).lower())


def group_by_network(tokens: list[dict]) -> list[dict]:
    """One entry per network the wallet holds value on, largest first.

    Port of ``selectFundedNetworkBalances``, over every network the balances
    cover rather than only automatable ones: the pane shows the whole wallet,
    as the Portfolio view does. Tokens without a positive USD value are left
    out (unpriced spam tokens would otherwise crowd the list); the caller
    reports how many were hidden.
    """
    by_chain: dict[Any, dict] = {}
    for token in tokens:
        value = token.get("valueUsd")
        if not value or value <= 0:
            continue
        chain_id = token.get("chainId")
        network = by_chain.setdefault(
            chain_id,
            {
                "chain_id": chain_id,
                "chain_name": chain_name(token),
                "subtotal_usd": 0.0,
                "tokens": [],
            },
        )
        network["subtotal_usd"] += value
        network["tokens"].append(token)

    networks = []
    for network in by_chain.values():
        network["tokens"].sort(key=lambda t: t.get("valueUsd") or 0, reverse=True)
        network["subtotal_text"] = format_usd(network["subtotal_usd"])
        network["tokens"] = [_token_row(t) for t in network["tokens"]]
        networks.append(network)
    networks.sort(key=lambda n: n["subtotal_usd"], reverse=True)
    return networks


def _token_row(token: dict) -> dict:
    pct = token.get("change24hPct")
    return {
        "symbol": token.get("symbol") or "?",
        "name": token.get("name") or "",
        "address": token.get("address") or "",
        "chain_id": token.get("chainId"),
        "balance": str(token.get("balance", "0")),
        "balance_text": format_balance(token.get("balance", "0")),
        "value_text": format_usd(token.get("valueUsd")),
        "change_text": format_change(pct),
        "change_positive": pct is None or pct >= 0,
        "logo_url": token.get("logoUrl") or None,
        "fallback_logo_url": _icon_fallback(token.get("chainId"), token.get("address")),
    }


def shape_portfolio(balances: dict) -> dict:
    """``get_balances`` JSON -> the pane's render model."""
    tokens = balances.get("tokens") or []
    total = float(balances.get("totalValueUsd") or 0)
    pct = change_24h_pct(tokens)
    amount = change_24h_amount(total, pct)
    hidden = sum(1 for t in tokens if not (t.get("valueUsd") or 0) > 0)
    return {
        "address": balances.get("address") or "",
        "total_usd": total,
        "total_text": format_usd(total),
        "change_24h_pct": pct,
        "change_24h_text": f"{format_usd(amount)} ({format_change(pct)})",
        "change_positive": pct >= 0,
        "networks": group_by_network(tokens),
        "hidden_count": hidden,
        "truncated": bool(balances.get("truncated")),
    }


# -- funding QR ---------------------------------------------------------------

def qr_svg_data_uri(address: str) -> str | None:
    """An SVG data URI of the address QR (dark on light: scanners need contrast
    whatever the app theme), or None when segno is not installed.

    Uses ``svg_data_uri``, a STANDALONE SVG document, not ``svg_inline``: the
    inline variant omits the SVG namespace (it is meant to sit in HTML), and
    an ``<img>`` refuses to render a namespace-less SVG (broken-image icon).
    """
    try:
        import segno
    except ImportError:
        return None
    return segno.make(address, error="m").svg_data_uri(
        scale=5, border=2, dark="#000000", light="#ffffff"
    )
