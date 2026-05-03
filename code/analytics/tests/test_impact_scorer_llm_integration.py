"""Integration tests: services.news.scoring.impact_scorer <-> shared.llm.

Verifies the impact scorer no longer maintains its own backend dispatcher and
instead delegates to the shared LLM client.
"""

import os
from unittest import mock

import pytest

import shared.llm as shared_llm
from services.news.scoring import impact_scorer


# ── shared.llm wiring ──────────────────────────────────────────────────────

def test_chat_is_shared_llm_chat():
    assert impact_scorer._chat is shared_llm.chat


def test_llm_error_is_shared_error_class():
    assert impact_scorer.LLMError is shared_llm.LLMError


def test_no_local_backend_dispatcher_remains():
    """The old per-backend client imports were deleted."""
    assert not hasattr(impact_scorer, "_anthropic_chat")
    assert not hasattr(impact_scorer, "_do_agent_chat")
    assert not hasattr(impact_scorer, "_ollama_chat")
    assert not hasattr(impact_scorer, "_llm_error_class")


# ── set_news_impact_backend behaviour ──────────────────────────────────────

@pytest.fixture
def restore_backend(monkeypatch):
    """Snapshot env + globals; restore after each test that mutates them."""
    original_env = os.environ.get("NEWS_IMPACT_BACKEND")
    original_backend = impact_scorer._BACKEND
    yield
    if original_env is None:
        os.environ.pop("NEWS_IMPACT_BACKEND", None)
    else:
        os.environ["NEWS_IMPACT_BACKEND"] = original_env
    impact_scorer._BACKEND = original_backend
    impact_scorer._sync_concurrency_from_backend()


def test_set_backend_updates_env_var(restore_backend):
    impact_scorer.set_news_impact_backend("anthropic")
    assert os.environ["NEWS_IMPACT_BACKEND"] == "anthropic"
    assert impact_scorer._BACKEND == "anthropic"


def test_set_backend_rejects_unknown_value(restore_backend):
    with pytest.raises(ValueError):
        impact_scorer.set_news_impact_backend("gpt")


def test_set_backend_normalises_case_and_whitespace(restore_backend):
    impact_scorer.set_news_impact_backend("  Ollama  ")
    assert impact_scorer._BACKEND == "ollama"


def test_set_backend_resets_concurrency_for_anthropic(restore_backend):
    impact_scorer.set_news_impact_backend("anthropic")
    # Anthropic default is 8 (or OLLAMA_CONCURRENCY fallback).
    assert impact_scorer._CONCURRENCY >= 1
    assert impact_scorer._sem is None


def test_set_backend_resets_concurrency_for_ollama(restore_backend):
    os.environ.pop("OLLAMA_CONCURRENCY", None)
    impact_scorer.set_news_impact_backend("ollama")
    assert impact_scorer._CONCURRENCY == 1
    assert impact_scorer._sem is None


# ── Concurrency env-var overrides per backend ──────────────────────────────

def test_concurrency_picks_up_anthropic_env(monkeypatch, restore_backend):
    monkeypatch.setenv("ANTHROPIC_CONCURRENCY", "12")
    impact_scorer.set_news_impact_backend("anthropic")
    assert impact_scorer._CONCURRENCY == 12


def test_concurrency_picks_up_do_agent_env(monkeypatch, restore_backend):
    monkeypatch.setenv("DO_GENAI_AGENT_CONCURRENCY", "6")
    impact_scorer.set_news_impact_backend("do_agent")
    assert impact_scorer._CONCURRENCY == 6


# ── _default_model honours backend ─────────────────────────────────────────

def test_default_model_anthropic(restore_backend, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_IMPACT_MODEL", raising=False)
    impact_scorer.set_news_impact_backend("anthropic")
    assert impact_scorer._default_model() == "claude-haiku-4-5-20251001"


def test_default_model_ollama(restore_backend, monkeypatch):
    monkeypatch.delenv("OLLAMA_IMPACT_MODEL", raising=False)
    impact_scorer.set_news_impact_backend("ollama")
    assert impact_scorer._default_model() == "devstral"


def test_default_model_respects_env_override(restore_backend, monkeypatch):
    monkeypatch.setenv("OLLAMA_IMPACT_MODEL", "custom-llm")
    impact_scorer.set_news_impact_backend("ollama")
    assert impact_scorer._default_model() == "custom-llm"


# ── Public API surface preserved ───────────────────────────────────────────

def test_public_api_still_importable():
    """Other services still import these symbols — make sure they exist."""
    from services.news.scoring.impact_scorer import (  # noqa: F401
        score_article,
        aggregate_heads,
        top_dimensions,
        extract_tickers,
        HeadOutput,
        set_news_impact_backend,
    )
