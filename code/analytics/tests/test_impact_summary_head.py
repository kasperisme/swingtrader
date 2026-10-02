"""Unit tests for the IMPACT_SUMMARY head (runs last, reads priced-in)."""

import asyncio
import json
from datetime import date

import pytest

from services.news.scoring import impact_scorer, impact_summary
from services.news.scoring.impact_scorer import (
    ALL_HEAD_CLUSTERS,
    HeadOutput,
    SPECIAL_HEAD_CLUSTERS,
    aggregate_heads,
    normalize_head_clusters,
    score_article,
)


def _head(cluster, scores=None, reasoning=None, meta=None, error=None):
    return HeadOutput(
        cluster=cluster, scores=scores or {}, reasoning=reasoning or {},
        confidence=0.9, model="m", latency_ms=1, raw_response="",
        error=error, meta=meta or {},
    )


NVDA_ROW = {
    "id": 42, "ticker": "NVDA", "as_of": "2026-09-20", "price": 180.0,
    "n_targets": 40, "target_low": 120.0, "target_high": 260.0, "target_median": 210.0,
    "implied_revenue_cagr": 0.22,
    "summary_json": {
        "position": "Price sits below the median target.",
        "pays_for": ["Data-center revenue compounding through FY2028"],
        "declines": ["Sovereign AI demand at scale"],
        "crux": "Does hyperscaler capex hold into 2027?",
    },
    "drivers_json": [{"driver": "hyperscaler capex"}],
}


def test_registered_last_and_special():
    assert ALL_HEAD_CLUSTERS[-1] == "IMPACT_SUMMARY"
    assert "IMPACT_SUMMARY" in SPECIAL_HEAD_CLUSTERS
    assert normalize_head_clusters(["summary"]) == ["IMPACT_SUMMARY"]


def test_affected_tickers_ranks_by_sentiment_and_drops_mentions():
    heads = [_head("TICKER_SENTIMENT", {"AMD": -0.3, "NVDA": 0.8, "INTC": 0.05})]
    assert impact_summary.affected_tickers(heads) == ["NVDA", "AMD"]


def test_affected_tickers_falls_back_to_relationships():
    heads = [
        _head("TICKER_SENTIMENT"),
        _head("TICKER_RELATIONSHIPS", {"TSM__NVDA__supplier": 0.9}),
    ]
    assert impact_summary.affected_tickers(heads) == ["TSM", "NVDA"]


def test_format_priced_in_hides_split_corrupted_targets():
    split = dict(NVDA_ROW, target_median=2100.0)
    assert "analyst targets" in impact_summary.format_priced_in("NVDA", NVDA_ROW)
    text = impact_summary.format_priced_in("NVDA", split)
    assert "analyst targets" not in text
    assert "PAYS FOR" in text  # the narrative survives


def test_parse_response_keeps_only_given_tickers():
    raw = json.dumps({
        "summary": "Mostly priced in.",
        "tickers": [
            {"ticker": "nvda", "relation": "confirms", "assumption": "DC compounding",
             "impact": 0.1, "read": "Already paid for."},
            {"ticker": "AAPL", "relation": "challenges", "impact": -0.9, "read": "x"},
            {"ticker": "AMD", "relation": "bogus", "impact": 5, "read": "y"},
        ],
        "confidence": 0.7,
    })
    scores, reasoning, conf, meta = impact_summary.parse_response(
        raw, ["NVDA", "AMD"], {"NVDA": NVDA_ROW}
    )
    assert scores == {"NVDA": 0.1, "AMD": 1.0}
    assert reasoning["_summary"] == "Mostly priced in."
    assert meta["NVDA"] == {
        "relation": "confirms", "assumption": "DC compounding",
        "priced_in_as_of": "2026-09-20", "priced_in_id": 42,
    }
    # No reconstruction for AMD: the parser, not the model, says so.
    assert meta["AMD"] == {"relation": "no_reconstruction"}
    assert conf == 0.7


def test_summary_excluded_from_aggregate():
    heads = [_head("IMPACT_SUMMARY", {"NVDA": 0.5})]
    assert aggregate_heads(heads) == {}


def test_score_article_runs_summary_after_other_heads(monkeypatch):
    order: list[str] = []
    seen_prompt: dict = {}

    async def fake_cluster_head(article_text, cluster, **kw):
        order.append(cluster)
        if cluster == "TICKER_SENTIMENT":
            return _head(cluster, {"nvidia": 0.8}, {"nvidia": "beat"})
        return _head(cluster)

    async def fake_chat(prompt, system, model, timeout):
        order.append("IMPACT_SUMMARY")
        seen_prompt["p"] = prompt
        return json.dumps({
            "summary": "Supports a declined assumption.",
            "tickers": [{"ticker": "NVDA", "relation": "challenges",
                         "assumption": "Sovereign AI", "impact": 0.4, "read": "r"}],
            "confidence": 0.8,
        }), 5

    loader_calls: list = []

    async def loader(tickers, as_of_max):
        loader_calls.append((tickers, as_of_max))
        return {"NVDA": NVDA_ROW}

    def normalize(hs):
        for h in hs:
            if h.cluster == "TICKER_SENTIMENT":
                h.scores = {"NVDA": h.scores.pop("nvidia")}

    monkeypatch.setattr(impact_scorer, "_run_cluster_head", fake_cluster_head)
    monkeypatch.setattr(impact_scorer, "_chat", fake_chat)

    heads = asyncio.run(score_article(
        "body", clusters=["TICKER_SENTIMENT", "STORY_KEY_POINTS", "IMPACT_SUMMARY"],
        published_at="2026-10-01T12:00:00Z",
        normalize_heads=normalize, priced_in_loader=loader,
    ))

    assert order[-1] == "IMPACT_SUMMARY"
    assert [h.cluster for h in heads][-1] == "IMPACT_SUMMARY"
    # Canonical ticker reached the lookup, bounded by the publication date.
    assert loader_calls == [(["NVDA"], date(2026, 10, 1))]
    assert "price DECLINES: Sovereign AI demand at scale" in seen_prompt["p"]
    summary = heads[-1]
    assert summary.scores == {"NVDA": 0.4}
    assert summary.meta["NVDA"]["relation"] == "challenges"


def test_summary_alone_uses_prior_heads(monkeypatch):
    async def fake_chat(prompt, system, model, timeout):
        assert "Ticker sentiment:" in prompt
        return json.dumps({"summary": "s", "tickers": [], "confidence": 0.5}), 1

    async def loader(tickers, as_of_max):
        return {}

    monkeypatch.setattr(impact_scorer, "_chat", fake_chat)
    prior = [_head("TICKER_SENTIMENT", {"NVDA": 0.6}, {"NVDA": "r"})]
    heads = asyncio.run(score_article(
        "body", clusters=["IMPACT_SUMMARY"], prior_heads=prior, priced_in_loader=loader,
    ))
    assert len(heads) == 1 and heads[0].reasoning == {"_summary": "s"}


def test_summary_skips_llm_when_every_head_failed(monkeypatch):
    async def boom(*a, **kw):
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr(impact_scorer, "_chat", boom)
    prior = [_head("TICKER_SENTIMENT", error="timeout")]
    heads = asyncio.run(score_article("body", clusters=["IMPACT_SUMMARY"], prior_heads=prior))
    assert heads[0].error and heads[0].scores == {}
