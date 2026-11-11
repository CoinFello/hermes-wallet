"""The plugin warns, never blocks, when a chat runs on a model CoinFello does
not recommend for onchain actions (flagships only: Opus 5+, GPT-6 Astra,
Grok 4.6+, Gemini 3 Pro+, Claude Fable / Mythos)."""

import json
import sys
import types

import pytest

import coinfello_models as models


@pytest.fixture(autouse=True)
def _clean():
    models.reset()
    yield
    models.reset()


@pytest.mark.parametrize("model", [
    "claude-opus-5-5", "anthropic/claude-opus-5.5", "claude-opus-5", "claude-opus-6",
    "claude-opus-5-20260601", "claude-fable-5-2", "claude-mythos-5-2",
    "gpt-6-astra", "openai/gpt-6-astra", "gpt-6-astra-900k", "gpt-6.1-astra", "gpt-7-astra",
    "grok-4.6", "x-ai/grok-4.6:nitro", "grok-5",
    "gemini-3-pro", "gemini-3.1-pro", "google/gemini-3.1-pro-preview",
])
def test_flagships_get_no_warning(model):
    assert models.is_supported(model)
    assert models.notice(model) is None


@pytest.mark.parametrize("model", [
    "glm-5.2", "z-ai/glm-5.3", "kimi-k3", "deepseek-v4-pro", "qwen3.5-plus",
    "claude-opus-4-8", "claude-sonnet-5", "claude-haiku-5",
    "gpt-6-luna", "gpt-6-sol", "gpt-5.5", "gpt-5.4-mini",
    "grok-4.5", "grok-4", "gemini-3-flash", "gemini-2.5-pro",
])
def test_other_models_get_a_warning(model):
    assert not models.is_supported(model)
    text = models.notice(model)
    assert model in text and "/model" in text and "keep going" in text


def test_unknown_model_says_nothing():
    assert models.is_supported("")
    assert models.session_notice("never-seen") is None
    assert models.approval_warning("never-seen") is None


def test_result_notice_once_per_chat_and_tracks_model_changes():
    models.remember("s1", "glm-5.2")
    assert "glm-5.2" in models.first_notice("s1")
    assert models.first_notice("s1") is None  # once per chat
    models.remember("s2", "claude-opus-5-5")
    assert models.first_notice("s2") is None
    # The approval prompt warns every time, and follows /model switches.
    assert "glm-5.2" in models.approval_warning("s1")
    models.remember("s1", "claude-opus-5-5")
    assert models.approval_warning("s1") is None


@pytest.fixture
def plugin(monkeypatch):
    registry = types.ModuleType("tools.registry")
    registry.tool_error = lambda message: json.dumps({"error": message})
    registry.tool_result = lambda payload: json.dumps(payload)
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.registry", registry)
    monkeypatch.delitem(sys.modules, "coinfello_tools", raising=False)
    import coinfello_tools as tools
    return tools


def test_tool_results_carry_the_notice_on_the_first_call_only(plugin, monkeypatch):
    monkeypatch.setattr(plugin.core, "save_state", lambda patch: patch)
    models.remember("chat-1", "glm-5.2")
    handler = plugin._wrap(lambda args: {"ok": True})
    first = json.loads(handler({}, session_id="chat-1"))
    assert first["ok"] and "glm-5.2" in first["model_notice"]
    second = json.loads(handler({}, session_id="chat-1"))
    assert "model_notice" not in second


def test_flagship_chats_see_no_notice(plugin):
    models.remember("chat-2", "claude-opus-5-5")
    handler = plugin._wrap(lambda args: {"ok": True})
    assert "model_notice" not in json.loads(handler({}, session_id="chat-2"))


def test_approval_prompt_carries_the_warning(monkeypatch):
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    registry = types.ModuleType("tools.registry")
    registry.tool_error = lambda message: json.dumps({"error": message})
    registry.tool_result = lambda payload: json.dumps(payload)
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.registry", registry)
    for name in [n for n in sys.modules if n == "cf_models_pkg" or n.startswith("cf_models_pkg.")]:
        monkeypatch.delitem(sys.modules, name)
    spec = importlib.util.spec_from_file_location(
        "cf_models_pkg", root / "__init__.py", submodule_search_locations=[str(root)])
    pkg = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "cf_models_pkg", pkg)
    spec.loader.exec_module(pkg)

    monkeypatch.setattr(pkg._trades, "approval_directive",
                        lambda tool, args: {"action": "approve", "message": "Swap 1 ETH.", "rule_key": "k"})
    monkeypatch.setattr(pkg._t, "note_model", lambda model: None)
    pkg._track_model(session_id="chat-3", model="kimi-k3")
    directive = pkg._require_human_approval("coinfello_execute", {"intent_id": "x"}, session_id="chat-3")
    assert directive["message"].startswith("Swap 1 ETH.")
    assert "kimi-k3" in directive["message"] and "Warning" in directive["message"]

    pkg._track_model(session_id="chat-4", model="gpt-6-astra")
    clean = pkg._require_human_approval("coinfello_execute", {"intent_id": "x"}, session_id="chat-4")
    assert clean["message"] == "Swap 1 ETH."
