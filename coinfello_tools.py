"""Agent-facing Hermes tools for CoinFello (registered by ``__init__``).

Thin adapters: schema + handler per tool, with the real work in
``coinfello_core``. Handlers never raise — they render every failure as a
``tool_error`` string, the plugin contract.
"""

from __future__ import annotations

from typing import Any, Callable

from tools.registry import tool_error, tool_result

try:  # package import inside Hermes; plain import in tests
    from . import coinfello_cards as cards
    from . import coinfello_core as core
    from . import coinfello_trades as trades
except ImportError:  # pragma: no cover
    import coinfello_cards as cards  # type: ignore[no-redef]
    import coinfello_core as core  # type: ignore[no-redef]
    import coinfello_trades as trades  # type: ignore[no-redef]

Handler = Callable[[dict], Any]


def _schema(name: str, description: str, properties: dict, required: tuple = ()) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(required),
        },
    }


_STRING = {"type": "string"}
_INT = {"type": "integer"}
_NUMBER = {"type": "number"}
_CHAIN_IDS = {
    "type": "array",
    "items": {"type": "integer"},
    "description": "Chain IDs to limit the read to (e.g. [8453] for Base); omit for every supported chain",
}
_TOKEN = lambda key: {  # noqa: E731
    "type": "string",
    "description": f"{key.capitalize()}: token symbol (e.g. \"USDC\") or contract address",
}


def _run(call: Callable[[], Any]) -> str:
    try:
        return tool_result(call())
    except core.NotSignedIn as exc:
        return tool_error(f"Not signed in to CoinFello. {exc}")
    except core.NeedsTradingAccess as exc:
        return tool_error(str(exc))
    except core.ToolError as exc:
        return tool_error(f"CoinFello: {exc}")
    except core.MCPError as exc:
        return tool_error(f"CoinFello MCP error: {exc}")
    except (ValueError, RuntimeError) as exc:
        return tool_error(str(exc))
    except Exception as exc:  # plugin contract: never raise out
        return tool_error(f"CoinFello tool failed: {type(exc).__name__}: {exc}")


def _wrap(handler: Handler) -> Handler:
    def safe(args: dict) -> str:
        return _run(lambda: handler(args or {}))

    return safe


def _wrap_with_session(handler: Callable[..., Any]) -> Callable[..., str]:
    """Like ``_wrap``, taking the calling session's id from Hermes (which
    passes the context keywords a handler's signature names)."""
    def safe(args: dict, session_id: str = "", **_context: Any) -> str:
        return _run(lambda: handler(args or {}, session_id=str(session_id or "")))

    return safe


# -- handlers ----------------------------------------------------------------

def _status(args: dict) -> dict:
    return core.status()


def _connect(args: dict) -> Any:
    return core.connect(str(args.get("email") or ""))


def _disconnect(args: dict) -> Any:
    return core.disconnect()


def _set_daily_limit(args: dict) -> Any:
    if "limit_usd" not in args:
        raise ValueError("limit_usd is required: a dollar amount, or null for read only")
    return core.change_daily_limit(args.get("limit_usd"))


def _limit_status(args: dict) -> Any:
    return core.poll_limit_change()


def _chat(args: dict) -> Any:
    payload = {"message": str(args.get("message") or "").strip()}
    if not payload["message"]:
        raise ValueError("message is required")
    if args.get("chat_id"):
        payload["chat_id"] = str(args["chat_id"]).strip()
    # Fello stages fund-moving actions for coinfello_execute instead of
    # refusing them; an older server never advertised the flag.
    if core.accepts_param("fello_chat", "stage_actions"):
        payload["stage_actions"] = True
    return trades.remember_staged(core.call("fello_chat", payload, timeout=180.0))


def _job_status(args: dict) -> Any:
    job_id = str(args.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id is required")
    return trades.remember_staged(core.call("fello_job_status", {"job_id": job_id}))


def _read(tool_name: str):
    def handler(args: dict) -> Any:
        return core.call(tool_name, args)

    return handler


def _quote(args: dict) -> Any:
    payload = {
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
    return core.call("get_quote", payload)


def _prepare_swap(args: dict) -> Any:
    return trades.prepare_swap(args)


def _prepare_send(args: dict) -> Any:
    return trades.prepare_send(args)


def _execute(args: dict) -> Any:
    return trades.execute(str(args.get("intent_id") or ""))


def _show_card(args: dict, *, session_id: str = "") -> Any:
    arguments = args.get("arguments")
    if arguments is not None and not isinstance(arguments, dict):
        raise ValueError("arguments is an object of the card's own arguments, e.g. {\"token\": \"USDC\"}")
    # Models often put the card's arguments beside ``card`` instead of inside
    # ``arguments``; take those too, letting ``arguments`` win a clash.
    stray = {key: value for key, value in args.items() if key not in ("card", "arguments")}
    return cards.show_card(args.get("card"), {**stray, **(arguments or {})}, session_id=session_id)


def _transfer_status(args: dict) -> Any:
    return trades.transfer_status(str(args.get("tx_hash") or ""))


def _prices(args: dict) -> Any:
    tokens = args.get("tokens")
    if not isinstance(tokens, list) or not tokens:
        raise ValueError("tokens is a non-empty list of {chain_id, token}")
    cleaned = [
        {"chain_id": int(item.get("chain_id") or 0), "token": str(item.get("token") or "").strip()}
        for item in tokens
        if isinstance(item, dict)
    ]
    if not cleaned or any(not item["chain_id"] or not item["token"] for item in cleaned):
        raise ValueError("every token needs a chain_id and a token symbol or address")
    return core.call("get_prices", {"tokens": cleaned})


# -- tool table --------------------------------------------------------------

_COINFELLO_TOOLS: tuple[tuple[str, dict, Handler], ...] = (
    (
        "coinfello_status",
        _schema(
            "coinfello_status",
            "Show the CoinFello connection state: whether a session is signed in "
            "and as whom, its access (read_only, or trade with daily_limit_usd, "
            "spent_today_usd and remaining_today_usd), the automation wallet "
            "address (the address to send funds to, on any EVM network), and "
            "how to sign in when not connected. Check access before preparing a trade: "
            "a read_only session is refused, and `next` says how to upgrade.",
            {},
        ),
        _status,
    ),
    (
        "coinfello_connect",
        _schema(
            "coinfello_connect",
            "Connect CoinFello. Sign-in is Hermes's own OAuth: the human runs "
            "`hermes auth add coinfello:coinfello` once in their own terminal "
            "(it opens CoinFello in their browser, where they choose read only "
            "or a daily trading limit). Returns the current sign-in if there is "
            "one, else user_message with the steps: SEND IT TO THE HUMAN EXACTLY "
            "AS WRITTEN. You cannot run the command yourself; call "
            "coinfello_status once they say they're done. To let a read-only "
            "session trade, use coinfello_set_daily_limit instead.",
            {},
        ),
        _connect,
    ),
    (
        "coinfello_set_daily_limit",
        _schema(
            "coinfello_set_daily_limit",
            "Change how much the agent may trade per day, or make the session "
            "read-only (limit_usd null). Same session, no new sign-in. Lowering "
            "applies at once. Raising (including read-only -> trading) only "
            "returns an approval link: the human approves it on CoinFello in "
            "their own browser, so the agent can never raise its own limit. "
            "Only call this with an amount the human asked for. Send the "
            "returned user_message to the human exactly as written; for a raise, "
            "then call coinfello_limit_status every 5-10 seconds.",
            {
                "limit_usd": {
                    "type": ["number", "null"],
                    "description": "New daily limit in USD (any positive amount), or null for read only",
                },
            },
            ("limit_usd",),
        ),
        _set_daily_limit,
    ),
    (
        "coinfello_limit_status",
        _schema(
            "coinfello_limit_status",
            "Check on a daily-limit raise the human is approving in their "
            "browser: pending, approved (with the new limit), denied or expired.",
            {},
        ),
        _limit_status,
    ),
    (
        "coinfello_disconnect",
        _schema(
            "coinfello_disconnect",
            "Sign out of CoinFello: CoinFello revokes this Hermes sign-in at once. "
            "The wallet itself is untouched. Send the returned user_message: it "
            "names the command that also removes the sign-in from Hermes.",
            {},
        ),
        _disconnect,
    ),
    (
        "coinfello_chat",
        _schema(
            "coinfello_chat",
            "Send a message to Fello, CoinFello's DeFi agent, acting for the signed-in "
            "account: research, planning, and the actions the other coinfello_* "
            "tools do not cover (staking and yield, Hyperliquid perps, Polymarket, "
            "LP positions, hedges, pausing or cancelling automations). Hermes shows "
            "the human each message for approval before it is sent. Fello does not "
            "run fund-moving actions here: it STAGES them, and the reply lists them "
            "in staged_actions (intent_id, summary, effect, usd, expires_at). "
            "Nothing staged has run: show the human each summary and call "
            "coinfello_execute with its intent_id only for the ones they agree to; "
            "a spend with usd null will be refused. For a plain swap, bridge or "
            "token send prefer coinfello_prepare_swap / coinfello_prepare_send. "
            "Never use this to \"execute\" a quote, and never start a follow-up "
            "trade (e.g. to repair a bad result) without the human asking for it. "
            "Returns Fello's reply, a chat_id (pass it back to continue the "
            "conversation, e.g. to tell Fello what an executed action did) and "
            "staged_actions. A turn can take minutes: status \"running\" means "
            "poll coinfello_job_status with the job_id.",
            {
                "message": {**_STRING, "description": "What you want Fello to do or answer"},
                "chat_id": {**_STRING, "description": "chat_id from a previous reply, to continue that conversation"},
            },
            ("message",),
        ),
        _chat,
    ),
    (
        "coinfello_job_status",
        _schema(
            "coinfello_job_status",
            "Poll a coinfello_chat turn that returned status \"running\". Returns "
            "running (call again in 20-30 seconds), done with Fello's reply, "
            "chat_id and staged_actions exactly as coinfello_chat would (nothing "
            "staged has run: show the human each summary, then coinfello_execute "
            "the ones they agree to), or error.",
            {"job_id": {**_STRING, "description": "job_id from the running reply"}},
            ("job_id",),
        ),
        _job_status,
    ),
    (
        "coinfello_balances",
        _schema(
            "coinfello_balances",
            "Spendable token balances of the signed-in CoinFello automation wallet, "
            "sorted by USD value, with a totalValueUsd. DeFi positions are separate: "
            "use coinfello_positions.",
            {"chain_ids": _CHAIN_IDS},
        ),
        _read("get_balances"),
    ),
    (
        "coinfello_positions",
        _schema(
            "coinfello_positions",
            "Every position of the CoinFello automation wallet in three sections: "
            "defi (LP, lending, staking), hyperliquid (perps, spot, vaults, resting "
            "orders) and polymarket. One source being down does not fail the others.",
            {},
        ),
        _read("get_positions"),
    ),
    (
        "coinfello_lp_positions",
        _schema(
            "coinfello_lp_positions",
            "Liquidity-pool positions of the CoinFello automation wallet with their "
            "price ranges and unclaimed fees, sorted by USD value.",
            {},
        ),
        _read("get_lp_positions"),
    ),
    (
        "coinfello_open_orders",
        _schema(
            "coinfello_open_orders",
            "Resting Hyperliquid orders (TP/SL and limits) of the CoinFello "
            "automation wallet.",
            {},
        ),
        _read("get_open_orders"),
    ),
    (
        "coinfello_activity",
        _schema(
            "coinfello_activity",
            "Recent activity of the CoinFello automation wallet, newest first: "
            "on-chain transactions (use to confirm what actually happened after a "
            "trade) and Hyperliquid fills.",
            {
                "before": {**_STRING, "description": "nextCursor from a previous call, for older rows"},
                "chain_ids": _CHAIN_IDS,
                "fills_since_hours": {**_INT, "description": "How far back to read fills, in hours (default 168)"},
            },
        ),
        _read("get_activity"),
    ),
    (
        "coinfello_quote",
        _schema(
            "coinfello_quote",
            "Quote a swap (same chain) or bridge (different chains) from the "
            "CoinFello automation wallet, for comparing options. "
            "EXECUTES NOTHING and cannot be executed by reference: to trade, use "
            "coinfello_prepare_swap with the same arguments.",
            {
                "from_chain_id": {**_INT, "description": "Source chain ID"},
                "from_token": _TOKEN("from"),
                "to_chain_id": {**_INT, "description": "Destination chain ID; omit for a same-chain swap"},
                "to_token": _TOKEN("to"),
                "amount": {**_STRING, "description": "Amount in whole tokens, e.g. \"1.5\""},
                "slippage": {**_NUMBER, "description": "Slippage as a fraction (0.005 = 0.5%, the default)"},
            },
            ("from_chain_id", "from_token", "to_token", "amount"),
        ),
        _quote,
    ),
    (
        "coinfello_prepare_swap",
        _schema(
            "coinfello_prepare_swap",
            "Step 1 of a swap (same chain) or bridge (different chains) from the "
            "CoinFello automation wallet: quotes it and stores it as "
            "a single-use intent valid for about two minutes. EXECUTES NOTHING. "
            "Returns intent_id, the summary (amount in, minimum out, bridge, gas "
            "and fees) and a one-line description. Refused up front when the "
            "wallet lacks the source chain's gas token. Check coinfello_balances "
            "(no chain filter) first to find the chain the token is on. Then show "
            "the human the description and call coinfello_execute promptly: "
            "Hermes asks the human to approve that exact summary.",
            {
                "from_chain_id": {**_INT, "description": "Source chain ID (where the token is held)"},
                "from_token": _TOKEN("from"),
                "to_chain_id": {**_INT, "description": "Destination chain ID; omit for a same-chain swap"},
                "to_token": _TOKEN("to"),
                "amount": {**_STRING, "description": "Amount of from_token in whole tokens, e.g. \"1.5\""},
                "slippage": {**_NUMBER, "description": "Slippage as a fraction (0.005 = 0.5%, the default)"},
            },
            ("from_chain_id", "from_token", "to_token", "amount"),
        ),
        _prepare_swap,
    ),
    (
        "coinfello_prepare_send",
        _schema(
            "coinfello_prepare_send",
            "Step 1 of a token send from the CoinFello automation wallet: validates "
            "recipient, token, amount (against the balance) and gas, and stores it "
            "as a single-use intent valid for about two minutes. EXECUTES NOTHING. "
            "Show the human the description, then call coinfello_execute: Hermes "
            "asks them to approve it.",
            {
                "chain_id": {**_INT, "description": "Chain ID to send on"},
                "token": {**_STRING, "description": "Token contract address, or 0x0000000000000000000000000000000000000000 for the chain's gas token"},
                "amount": {**_STRING, "description": "Amount in whole tokens, e.g. \"25.5\""},
                "recipient": {**_STRING, "description": "Recipient 0x address, exactly as the human gave it"},
            },
            ("chain_id", "token", "amount", "recipient"),
        ),
        _prepare_send,
    ),
    (
        "coinfello_execute",
        _schema(
            "coinfello_execute",
            "Step 2: executes a prepared swap, bridge or send, or an action Fello "
            "staged in a coinfello_chat / coinfello_job_status reply, ON-CHAIN "
            "exactly as prepared or staged. Hermes first shows the human the "
            "server's summary and runs it only if they approve; a denial means "
            "stop, not retry. Each intent runs once; prepared ones expire after "
            "two minutes, staged ones at expires_at. price_moved or route_changed "
            "means nothing was sent: prepare again. A successful bridge confirms "
            "only the source chain: follow up with coinfello_transfer_status. A "
            "staged action returns kind \"action\" with tool, transaction_hashes, "
            "outcome_unknown (may have gone through: never retry), "
            "needs_permission, error and next: follow next (its fello_chat is "
            "coinfello_chat here, on the same chat_id).",
            {"intent_id": {**_STRING, "description": (
                "intent_id from coinfello_prepare_swap, coinfello_prepare_send or a "
                "staged_actions entry"
            )}},
            ("intent_id",),
        ),
        _execute,
    ),
    (
        "coinfello_transfer_status",
        _schema(
            "coinfello_transfer_status",
            "What a swap or bridge actually delivered, by its source transaction "
            "hash. outcome is pending, completed, wrong_token (it "
            "finished but a different token arrived, e.g. WETH instead of POL), "
            "refunded (nothing arrived; the source token came back) or failed. "
            "Use this after every bridge instead of polling balances, which cannot "
            "tell settling from refunded. Report wrong_token and refunded plainly; "
            "never repair them with another trade unless the human asks.",
            {"tx_hash": {**_STRING, "description": "Source-chain transaction hash"}},
            ("tx_hash",),
        ),
        _transfer_status,
    ),
    (
        "coinfello_yields",
        _schema(
            "coinfello_yields",
            "Yield opportunities for a token (staking, lending, vaults, LP pools), "
            "highest rate first. Rows marked outlier are unusual, not normal returns.",
            {
                "token": {**_STRING, "description": "Token symbol to deposit, e.g. \"USDC\" or \"ETH\""},
                "chain_ids": _CHAIN_IDS,
                "limit": {**_INT, "description": "How many to return (default 10, max 50)"},
            },
            ("token",),
        ),
        _read("get_yields"),
    ),
    (
        "coinfello_prices",
        _schema(
            "coinfello_prices",
            "Current USD prices with 1h, 24h and 7d change, for up to 20 tokens at "
            "once. Each token answers separately, so an unknown one does not fail "
            "the rest.",
            {
                "tokens": {
                    "type": "array",
                    "description": "Up to 20 of {chain_id, token}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "chain_id": {**_INT, "description": "Chain ID, e.g. 1 or 8453"},
                            "token": {**_STRING, "description": "Token symbol or contract address"},
                        },
                        "required": ["chain_id", "token"],
                    },
                },
            },
            ("tokens",),
        ),
        _prices,
    ),
)

_SHOW_CARD = (
    "coinfello_show_card",
    _schema(
        "coinfello_show_card",
        "Show a CoinFello card to the human. On Hermes desktop it is drawn in "
        "the CoinFello pane beside the chat (not inline), live: Refresh, "
        "fresh quotes and Confirm work on the card, and anything that moves "
        "funds asks the human in the pane first. On other surfaces (Telegram, "
        "CLI) no card can be drawn and you get the full text. Read `note` in "
        "the result: it says which happened and how to reply. Use it after the "
        "matching read or prepare, when a visual helps: portfolio, status, "
        "yield ({\"token\": \"USDC\"}), lp_ranges, perp, automations, needs_you, "
        "fund; quote with {\"intent_id\"} from coinfello_prepare_swap / "
        "_prepare_send; error with {\"kind\" or \"message\", \"retry_tool\"}. "
        "To deposit into a yield, earn_deposit: on desktop it opens CoinFello's "
        "Earn view in the pane, where the human browses yields, picks one and "
        "deposits; optionally preselect {\"opportunity\": <yield id>} or "
        "{\"token\": \"USDC\", \"chain_id\": 8453}. "
        "Those objects go inside `arguments`, not beside `card`. "
        "Executes nothing itself.",
        {
            "card": {"type": "string", "enum": cards.card_names(), "description": "Which card"},
            "arguments": {
                "type": "object",
                "description": (
                    "The card's own arguments, nested here (omit for none). A whole "
                    "call: {\"card\": \"yield\", \"arguments\": {\"token\": \"USDC\", \"chain_ids\": [8453]}}. "
                    "Only the ones the server declares are sent."
                ),
            },
        },
        ("card",),
    ),
    _wrap_with_session(_show_card),
)

TOOLS = tuple((name, schema, _wrap(handler)) for name, schema, handler in _COINFELLO_TOOLS) + (_SHOW_CARD,)


def available() -> bool:
    """True whenever the plugin loads — the endpoint default is always set."""
    return True