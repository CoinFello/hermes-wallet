"""Which agent models CoinFello recommends for onchain actions.

Fello plans and CoinFello's server checks every trade, but the Hermes agent
still decides what to ask for, reads the staged summaries and relays them.
Smaller or older models get amounts, chains and multi-step plans wrong more
often, so the plugin warns (never blocks) when the session runs on a model
outside the flagship tier below.

The model name comes from Hermes's ``pre_llm_call`` hook (one call per turn,
with the session id and the model the turn runs on). Names arrive in many
spellings: ``anthropic/claude-opus-5.5``, ``claude-opus-5-5``,
``x-ai/grok-4.6:nitro``, ``gpt-6-astra-900k``. They are normalised before
matching.
"""

from __future__ import annotations

import re
import threading
from typing import Any

#: Flagship models: a family pattern and the lowest version that counts.
#: Edit this list when a new flagship ships; anything not listed is warned
#: about, never blocked.
SUPPORTED: tuple[tuple[str, re.Pattern[str], tuple[int, ...]], ...] = (
    # Anthropic: Opus 5 and later, and the Fable / Mythos lines.
    ("Claude Opus 5+", re.compile(r"^claude-opus-(\d+)(?:[.-](\d+))?"), (5,)),
    ("Claude Fable", re.compile(r"^claude-fable(?:-(\d+))?"), ()),
    ("Claude Mythos", re.compile(r"^claude-mythos(?:-(\d+))?"), ()),
    # OpenAI: the Astra tier of GPT-6 and later.
    ("GPT-6 Astra", re.compile(r"^gpt-(\d+)(?:\.(\d+))?-astra"), (6,)),
    # xAI: Grok 4.6 (the latest) and later.
    ("Grok 4.6+", re.compile(r"^grok-(\d+)(?:\.(\d+))?(?:$|[-:])"), (4, 6)),
    # Google: Gemini 3 Pro and later.
    ("Gemini 3 Pro+", re.compile(r"^gemini-(\d+)(?:\.(\d+))?-pro"), (3,)),
)

SUPPORTED_NAMES = ", ".join(name for name, _, _ in SUPPORTED)

_lock = threading.Lock()
_session_models: dict[str, str] = {}
_warned_sessions: set[str] = set()
_MAX_SESSIONS = 512


def normalise(model: Any) -> str:
    """``x-ai/grok-4.6:nitro`` -> ``grok-4.6``; ``claude-opus-5.5`` stays."""
    name = str(model or "").strip().lower()
    name = name.rsplit("/", 1)[-1]  # vendor prefix
    name = name.split(":", 1)[0]  # router suffix (:nitro, :free, ...)
    name = name.split("@", 1)[0]  # pinned revision
    return name


def _version(match: re.Match[str]) -> tuple[int, ...]:
    return tuple(int(group) for group in match.groups() if group is not None)


def is_supported(model: Any) -> bool:
    name = normalise(model)
    if not name:
        return True  # unknown: say nothing rather than warn wrongly
    for _, pattern, floor in SUPPORTED:
        match = pattern.match(name)
        if match and _version(match) >= floor:
            return True
    return False


def notice(model: Any) -> str | None:
    """The warning for ``model``, or None when it is a recommended one."""
    if is_supported(model):
        return None
    name = str(model).strip()
    return (
        f"This chat runs on {name}, which isn't one of the models CoinFello "
        "recommends for onchain actions. Smaller models get amounts, chains "
        "and multi-step plans wrong more often. You can keep going, but read "
        "every approval carefully, or switch to a flagship model "
        f"({SUPPORTED_NAMES}) with /model."
    )


# -- per-session tracking (fed by the pre_llm_call hook) ---------------------

def remember(session_id: Any, model: Any) -> None:
    session = str(session_id or "").strip()
    name = str(model or "").strip()
    if not session or not name:
        return
    with _lock:
        if len(_session_models) >= _MAX_SESSIONS and session not in _session_models:
            _session_models.pop(next(iter(_session_models)))
        _session_models[session] = name


def model_for(session_id: Any) -> str | None:
    with _lock:
        return _session_models.get(str(session_id or "").strip())


def session_notice(session_id: Any) -> str | None:
    """The warning for the session's current model, every time it applies."""
    model = model_for(session_id)
    return notice(model) if model else None


def approval_warning(session_id: Any) -> str | None:
    """One line for an approval prompt when the session's model is not one
    CoinFello recommends."""
    model = model_for(session_id)
    if not model or is_supported(model):
        return None
    return (
        f"Warning: this chat runs on {model}, which isn't a model CoinFello "
        "recommends for onchain actions. Check every detail above before you "
        "approve."
    )


def first_notice(session_id: Any) -> str | None:
    """The warning once per session (for tool results the agent relays)."""
    text = session_notice(session_id)
    if not text:
        return None
    session = str(session_id or "").strip()
    with _lock:
        if session in _warned_sessions:
            return None
        if len(_warned_sessions) >= _MAX_SESSIONS:
            _warned_sessions.clear()
        _warned_sessions.add(session)
    return text


def reset() -> None:
    """Tests only."""
    with _lock:
        _session_models.clear()
        _warned_sessions.clear()
