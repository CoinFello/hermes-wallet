"""The pane's portfolio model must match the CoinFello web Portfolio view.

Each test pins a rule ported from a named coinfello-web function (see
coinfello_portfolio's module docstring), so a web-side change to that rule
shows up here as a deliberate, reviewable diff.
"""

from __future__ import annotations

import base64

import pytest

import coinfello_portfolio as p


# -- TokenRow.tsx formatters --------------------------------------------------

@pytest.mark.parametrize(
    ("balance", "expected"),
    [
        ("1", "1.00"),
        ("1234.5", "1,234.50"),
        ("0.123456", "0.1235"),  # 4 dp, rounded half-up like BigNumber
        ("0.1200", "0.12"),      # trailing zeros trimmed past 2 dp
        ("0.00001", "0.00"),
        ("1000000", "1,000,000.00"),
    ],
)
def test_format_balance_matches_token_row(balance, expected):
    assert p.format_balance(balance) == expected


def test_format_usd():
    assert p.format_usd(1234.5) == "$1,234.50"
    assert p.format_usd(0.005) == "$0.01"
    assert p.format_usd(-12.345) == "-$12.35"
    assert p.format_usd(None) == "—"


def test_format_change():
    assert p.format_change(2.346) == "+2.35%"
    assert p.format_change(-1.5) == "-1.50%"
    assert p.format_change(0) == "+0.00%"
    assert p.format_change(None) is None


# -- valuation.ts calculate24hChange -----------------------------------------

def test_change_is_value_weighted_against_previous_total():
    tokens = [
        {"priceUsd": 1, "valueUsd": 110.0, "change24hPct": 10.0},  # was 100
        {"priceUsd": 1, "valueUsd": 90.0, "change24hPct": -10.0},  # was 100
    ]
    # (+10 - 10) / 200 previous = 0%
    assert p.change_24h_pct(tokens) == pytest.approx(0.0, abs=1e-9)


def test_change_skips_unpriced_and_extreme_moves():
    tokens = [
        {"priceUsd": 1, "valueUsd": 110.0, "change24hPct": 10.0},
        {"priceUsd": None, "valueUsd": 500.0, "change24hPct": 50.0},  # unpriced
        {"priceUsd": 1, "valueUsd": 5.0, "change24hPct": -99.5},       # extreme: value only
    ]
    # change 10 over previous 100 + 5
    assert p.change_24h_pct(tokens) == pytest.approx(10 / 105 * 100)


def test_change_amount_discounts_rather_than_multiplies():
    # portfolioTotals.ts: a $1,000 book up 10% moved +$90.91, not +$100.
    assert p.change_24h_amount(1000.0, 10.0) == pytest.approx(90.909, abs=1e-3)


# -- automationWalletBalance.ts selectFundedNetworkBalances ------------------

BALANCES = {
    "address": "0xWALLET",
    "totalValueUsd": 3510.0,
    "truncated": False,
    "tokens": [
        {"chainId": 8453, "chainName": "Base", "address": "0xUSDC", "symbol": "USDC",
         "balance": "500", "priceUsd": 1, "valueUsd": 500.0, "change24hPct": 0.01,
         "logoUrl": "https://logos.example/usdc.png"},
        {"chainId": 1, "chainName": "Ethereum", "address": "0xETH", "symbol": "ETH",
         "balance": "1", "priceUsd": 3000, "valueUsd": 3000.0, "change24hPct": -2.0,
         "logoUrl": None},
        {"chainId": 8453, "chainName": "Base", "address": "0xAERO", "symbol": "AERO",
         "balance": "10", "priceUsd": 1, "valueUsd": 10.0, "change24hPct": 5.0},
        {"chainId": 8453, "chainName": "Base", "address": "0xSPAM", "symbol": "SPAM",
         "balance": "1000000", "priceUsd": None, "valueUsd": None, "change24hPct": None},
    ],
}


def test_groups_per_network_largest_first_with_subtotals():
    model = p.shape_portfolio(BALANCES)
    networks = model["networks"]
    assert [n["chain_name"] for n in networks] == ["Ethereum", "Base"]
    base = networks[1]
    assert base["subtotal_text"] == "$510.00"
    assert [t["symbol"] for t in base["tokens"]] == ["USDC", "AERO"]  # by value


def test_unpriced_tokens_are_hidden_and_counted():
    model = p.shape_portfolio(BALANCES)
    symbols = [t["symbol"] for n in model["networks"] for t in n["tokens"]]
    assert "SPAM" not in symbols
    assert model["hidden_count"] == 1


def test_same_token_on_two_networks_stays_two_rows():
    balances = {
        "totalValueUsd": 30.0,
        "tokens": [
            {"chainId": 8453, "chainName": "Base", "symbol": "USDC", "balance": "10",
             "priceUsd": 1, "valueUsd": 10.0},
            {"chainId": 42161, "chainName": "Arbitrum", "symbol": "USDC", "balance": "20",
             "priceUsd": 1, "valueUsd": 20.0},
        ],
    }
    networks = p.shape_portfolio(balances)["networks"]
    assert [(n["chain_name"], n["tokens"][0]["balance_text"]) for n in networks] == [
        ("Arbitrum", "20.00"),
        ("Base", "10.00"),
    ]


def test_token_icons_fall_back_like_token_icon_tsx():
    networks = p.shape_portfolio(BALANCES)["networks"]
    eth = networks[0]["tokens"][0]
    assert eth["logo_url"] is None
    assert eth["fallback_logo_url"] == (
        "https://static.cx.metamask.io/api/v1/tokenIcons/1/0xeth.png"
    )
    usdc = networks[1]["tokens"][0]
    assert usdc["logo_url"] == "https://logos.example/usdc.png"


def test_older_servers_without_chain_names_get_the_web_apps_names():
    # Older servers: no chainName in get_balances.
    balances = {
        "totalValueUsd": 15.0,
        "tokens": [
            {"chainId": 1, "symbol": "ETH", "balance": "0.003", "priceUsd": 3000, "valueUsd": 10.0},
            {"chainId": 8453, "symbol": "USDC", "balance": "5", "priceUsd": 1, "valueUsd": 5.0},
        ],
    }
    names = [n["chain_name"] for n in p.shape_portfolio(balances)["networks"]]
    assert names == ["Ethereum Mainnet", "Base"]


def test_server_chain_name_wins_over_the_fallback():
    token = {"chainId": 1, "chainName": "Ethereum (renamed upstream)"}
    assert p.chain_name(token) == "Ethereum (renamed upstream)"


def test_unknown_chains_still_render():
    assert p.chain_name({"chainId": 999999}) == "Chain 999999"
    # A server echoing its own "Chain <id>" fallback does not mask a known name.
    assert p.chain_name({"chainId": 1, "chainName": "Chain 1"}) == "Ethereum Mainnet"


def test_totals_and_header_change():
    model = p.shape_portfolio(BALANCES)
    assert model["total_text"] == "$3,510.00"
    assert model["change_positive"] is False
    assert model["change_24h_text"].startswith("-$")


# -- funding QR ---------------------------------------------------------------

def test_qr_is_a_standalone_svg_an_img_can_render():
    """An <img> only renders an SVG document that declares the SVG namespace.

    Parsed the way an image decoder sees it: the root must be a namespaced
    {http://www.w3.org/2000/svg}svg element (the inline variant's bare <svg>
    renders as a broken image).
    """
    pytest.importorskip("segno")
    import xml.etree.ElementTree as ET
    from urllib.parse import unquote

    address = "0x1234567890abcdef1234567890abcdef12345678"
    uri = p.qr_svg_data_uri(address)
    assert uri is not None and uri.startswith("data:image/svg+xml")
    header, _, payload = uri.partition(",")
    document = base64.b64decode(payload).decode() if ";base64" in header else unquote(payload)
    root = ET.fromstring(document)
    assert root.tag == "{http://www.w3.org/2000/svg}svg", root.tag
    assert "#000" in document  # dark modules on a light ground


def test_qr_degrades_without_segno(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_segno(name, *args, **kwargs):
        if name == "segno":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_segno)
    assert p.qr_svg_data_uri("0xabc") is None
