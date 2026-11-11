"""hermes-coinfello — CoinFello wallet + Fello DeFi agent tools for Hermes Agent.

Signs in with Hermes's own OAuth (`hermes auth add coinfello:coinfello`; the
plugin never holds a token) and exposes the automation wallet to the agent: fast reads
(balances, positions, prices, yields, quotes) and Fello, CoinFello's DeFi
agent, which stages on-chain actions for the human to approve.

Wiring goes only through the public plugin API (``ctx.register_tool`` and
``ctx.register_hook``). The ``pre_tool_call`` hook sends every tool call that
can move funds (``coinfello_execute``, ``coinfello_chat``) through Hermes'
human-approval gate, so a model cannot trade without a person approving it.
"""

from __future__ import annotations

try:
    from . import coinfello_cards as _cards
    from . import coinfello_models as _models
    from . import coinfello_tools as _t
    from . import coinfello_trades as _trades
except ImportError:  # pragma: no cover
    # Imported without a parent package (e.g. pytest walking the repo root).
    # Hermes itself always loads this file as the ``coinfello`` package.
    _cards = None
    _models = None
    _t = None
    _trades = None


TOOLSET = "coinfello"


def register(ctx) -> None:
    """Plugin entry point — called by the Hermes plugin loader."""
    if _t is None:
        raise RuntimeError(
            "coinfello: loaded outside its package; install as "
            "~/.hermes/plugins/coinfello/"
        )
    # coinfello_show_card asks which client the turn runs in (desktop draws
    # the card in the pane; other surfaces get its text).
    _cards.bind_host(ctx)
    for name, schema, handler in _t.TOOLS:
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=handler,
            check_fn=_t.available,
            emoji="🪙",
        )
    ctx.register_hook("pre_tool_call", _require_human_approval)
    # Which model each chat runs on, so CoinFello can warn about models it
    # does not recommend for onchain actions (coinfello_models). Observes
    # only: it never injects context or blocks a turn.
    ctx.register_hook("pre_llm_call", _track_model)


def _track_model(session_id: str = "", model: str = "", **_: object) -> None:
    try:
        _models.remember(session_id, model)
        _t.note_model(model)
    except Exception:  # an observer must never break a turn
        pass
    return None


def _require_human_approval(
    tool_name: str = "", args: dict | None = None, session_id: str = "", **_: object
):
    """Escalate fund-moving calls to the human (see coinfello_trades)."""
    try:
        directive = _trades.approval_directive(tool_name, args)
        if directive and directive.get("action") == "approve":
            # Shown to the human in the approval prompt itself, every time,
            # whatever the agent relays.
            warning = _models.approval_warning(session_id)
            if warning:
                directive = {**directive, "message": f"{directive['message']}\n\n{warning}"}
        return directive
    except Exception:  # fail closed: never let a hook bug wave a trade through
        if tool_name in ("coinfello_execute", "coinfello_chat"):
            return {
                "action": "block",
                "message": f"{tool_name} blocked: the CoinFello approval check failed.",
            }
        return None


__all__ = ["register"]