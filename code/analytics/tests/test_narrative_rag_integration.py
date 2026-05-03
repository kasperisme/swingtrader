"""Integration tests: services.news.narrative <-> services.rag wiring.

Verifies the narrative generator's adapter helpers delegate to RAG correctly
and reshape return data into the dataclasses the rest of the module expects.
"""

from datetime import datetime, timezone
from unittest import mock

import pytest

from services.news.narrative import narrative_generator as ng
from services.rag.graph import RelationshipEdge as RagRelationshipEdge


# ── shared types come from RAG ─────────────────────────────────────────────

def test_relationship_edge_class_is_from_rag():
    assert ng.RelationshipEdge is RagRelationshipEdge


# ── _fetch_open_positions adapter ──────────────────────────────────────────

def test_fetch_open_positions_converts_dicts_to_dataclasses():
    fake = [
        {"ticker": "AAPL", "net_qty": 100, "side": "long", "avg_cost": 150.5},
        {"ticker": "TSLA", "net_qty": -50, "side": "short", "avg_cost": 200.0},
    ]
    with mock.patch.object(ng, "_rag_get_user_positions", return_value=fake) as m:
        out = ng._fetch_open_positions(conn=None, user_id="u1")

    m.assert_called_once_with("u1")
    assert len(out) == 2
    assert out[0].ticker == "AAPL"
    assert out[0].net_qty == 100.0
    assert out[0].avg_cost == 150.5
    assert out[1].net_qty == -50.0


def test_fetch_open_positions_handles_none_avg_cost():
    fake = [{"ticker": "AAPL", "net_qty": 5, "side": "long", "avg_cost": None}]
    with mock.patch.object(ng, "_rag_get_user_positions", return_value=fake):
        out = ng._fetch_open_positions(conn=None, user_id="u1")
    assert out[0].avg_cost is None


# ── _fetch_active_screen_tickers adapter ───────────────────────────────────

def test_fetch_active_screen_tickers_delegates_to_rag():
    with mock.patch.object(ng, "_rag_get_user_screening_notes", return_value=["AAPL", "MSFT"]) as m:
        out = ng._fetch_active_screen_tickers(conn=None, user_id="u1")
    m.assert_called_once_with("u1")
    assert out == ["AAPL", "MSFT"]


# ── _fetch_ticker_news adapter ─────────────────────────────────────────────

def test_fetch_ticker_news_returns_empty_for_empty_input():
    out = ng._fetch_ticker_news(conn=None, tickers=[], lookback_hours=24)
    assert out == {}


def test_fetch_ticker_news_returns_empty_when_only_blanks():
    out = ng._fetch_ticker_news(conn=None, tickers=["", "  "], lookback_hours=24)
    assert out == {}


def test_fetch_ticker_news_normalises_tickers_and_passes_to_rag():
    with mock.patch.object(ng, "_rag_get_ticker_news", return_value=[]) as m:
        ng._fetch_ticker_news(conn=None, tickers=["aapl", "MSFT"], lookback_hours=12)

    args, kwargs = m.call_args
    assert set(args[0]) == {"AAPL", "MSFT"}
    assert kwargs["hours"] == 12


def test_fetch_ticker_news_reshapes_flat_list_into_per_ticker_dict():
    flat = [
        {
            "ticker": "AAPL", "article_id": 1, "title": "T1", "url": "u1",
            "published_at": "2026-04-30T10:00:00+00:00",
            "sentiment_score": 0.8, "sentiment_reason": "good", "relationships": [],
        },
        {
            "ticker": "AAPL", "article_id": 2, "title": "T2", "url": "u2",
            "published_at": "2026-04-30T11:00:00+00:00",
            "sentiment_score": -0.2, "sentiment_reason": "", "relationships": [{"x": 1}],
        },
        {
            "ticker": "MSFT", "article_id": 3, "title": "T3", "url": "u3",
            "published_at": "2026-04-30T12:00:00+00:00",
            "sentiment_score": 0.4, "sentiment_reason": "ok", "relationships": [],
        },
    ]
    with mock.patch.object(ng, "_rag_get_ticker_news", return_value=flat):
        out = ng._fetch_ticker_news(conn=None, tickers=["AAPL", "MSFT"], lookback_hours=24)

    assert set(out.keys()) == {"AAPL", "MSFT"}
    assert len(out["AAPL"]) == 2
    assert len(out["MSFT"]) == 1
    item = out["AAPL"][0]
    assert isinstance(item, ng.TickerNewsItem)
    assert item.article_id == 1
    assert item.sentiment_score == 0.8
    assert isinstance(item.published_at, datetime)


def test_fetch_ticker_news_drops_rows_for_unrequested_tickers():
    flat = [
        {"ticker": "GOOG", "article_id": 9, "title": "x", "url": "y",
         "published_at": None, "sentiment_score": 0, "sentiment_reason": "", "relationships": []},
    ]
    with mock.patch.object(ng, "_rag_get_ticker_news", return_value=flat):
        out = ng._fetch_ticker_news(conn=None, tickers=["AAPL"], lookback_hours=24)
    assert out == {"AAPL": []}


def test_fetch_ticker_news_handles_invalid_published_at_gracefully():
    flat = [
        {"ticker": "AAPL", "article_id": 1, "title": "T", "url": "u",
         "published_at": "not-a-date", "sentiment_score": 0.0,
         "sentiment_reason": "", "relationships": []},
    ]
    with mock.patch.object(ng, "_rag_get_ticker_news", return_value=flat):
        out = ng._fetch_ticker_news(conn=None, tickers=["AAPL"], lookback_hours=24)
    assert out["AAPL"][0].published_at is None


# ── _fetch_relationship_edges wrapper ──────────────────────────────────────

def test_fetch_relationship_edges_passes_threshold_constants():
    sentinel = [RagRelationshipEdge("A", "B", "partner", 0.5, 1)]
    with mock.patch.object(ng, "_rag_fetch_relationship_edges", return_value=sentinel) as m:
        out = ng._fetch_relationship_edges(conn=None, lookback_days=30)

    _, kwargs = m.call_args
    assert kwargs["lookback_days"] == 30
    assert kwargs["min_strength"] == ng._REL_MIN_STRENGTH
    assert kwargs["min_mentions"] == ng._REL_MIN_MENTIONS
    assert out is sentinel


# ── BFS wrappers pass-through ──────────────────────────────────────────────

def test_expand_related_tickers_delegates_to_rag():
    sentinel = ({"MSFT": 0.9}, {"MSFT": ["AAPL -partner-> MSFT"]})
    with mock.patch.object(ng, "_rag_expand_related_tickers", return_value=sentinel) as m:
        out = ng._expand_related_tickers(["AAPL"], [], hops=2, decay=0.5, min_score=0.3, max_tickers=5)
    m.assert_called_once_with(["AAPL"], [], 2, 0.5, 0.3, 5)
    assert out is sentinel


def test_build_neighborhood_from_seed_delegates_to_rag():
    sentinel = ({"AAPL"}, [], {"AAPL": 0}, {})
    with mock.patch.object(ng, "_rag_build_neighborhood_from_seed", return_value=sentinel) as m:
        out = ng._build_neighborhood_from_seed("AAPL", [], hops=2, limit_nodes=50, limit_edges=120)
    m.assert_called_once_with("AAPL", [], 2, 50, 120)
    assert out is sentinel
