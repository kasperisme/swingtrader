"""Unit tests for STORY_KEY_POINTS head parsing."""

import json

import pytest

from services.news.scoring.article_tags import (
    build_search_tags,
    parse_article_tags,
    tag_prompt_guidance,
)
from services.news.scoring.impact_scorer import (
    EXPECTED_HEAD_COUNT,
    SPECIAL_HEAD_CLUSTERS,
    _parse_key_points_response,
    _parse_tags_response,
    aggregate_heads,
    HeadOutput,
    normalize_head_clusters,
)
from services.news.scoring.dimensions import CLUSTERS


def test_normalize_head_clusters_aliases():
    assert normalize_head_clusters(["key_points", "sentiment"]) == [
        "STORY_KEY_POINTS",
        "TICKER_SENTIMENT",
    ]
    assert normalize_head_clusters(["tags", "MACRO_SENSITIVITY"]) == [
        "ARTICLE_TAGS",
        "MACRO_SENSITIVITY",
    ]


def test_parse_tags_response_keeps_custom_slugs():
    raw = json.dumps({
        "tags": ["fed", "Rate Cut", "nvidia_supply", "fed"],
        "confidence": 0.8,
    })
    scores, reasoning, confidence = _parse_tags_response(raw)
    assert confidence == 0.8
    assert scores == {
        "fed": 1.0,
        "rate_cut": 1.0,
        "nvidia_supply": 1.0,
    }
    assert "rate_cut" in reasoning


def test_parse_article_tags_normalizes():
    assert parse_article_tags(["AI Chips", "ai_chips", ""]) == ["ai_chips"]


def test_tag_prompt_guidance_describes_refetch_search():
    text = tag_prompt_guidance()
    assert "refetch" in text.lower()
    assert "overlap" in text.lower()
    assert "tickers" in text.lower()


def test_build_search_tags_merges_tickers():
    heads = [
        HeadOutput(
            cluster="ARTICLE_TAGS",
            scores={"fed": 1.0, "rates": 1.0},
            reasoning={},
            confidence=0.9,
            model="t",
            latency_ms=1,
            raw_response="",
        ),
        HeadOutput(
            cluster="TICKER_SENTIMENT",
            scores={"AAPL": 0.5, "MSFT": 0.0},
            reasoning={},
            confidence=0.9,
            model="t",
            latency_ms=1,
            raw_response="",
        ),
    ]
    tags = build_search_tags(heads)
    assert "fed" in tags and "rates" in tags and "AAPL" in tags
    assert "MSFT" not in tags
    assert parse_article_tags(["oil", "opec_production"]) == ["oil", "opec_production"]


def test_expected_head_count():
    assert len(CLUSTERS) == 9
    assert "STORY_KEY_POINTS" in SPECIAL_HEAD_CLUSTERS
    assert "ARTICLE_TAGS" in SPECIAL_HEAD_CLUSTERS
    assert EXPECTED_HEAD_COUNT == len(CLUSTERS) + len(SPECIAL_HEAD_CLUSTERS)


def test_parse_key_points_response():
    raw = json.dumps({
        "key_points": [
            {
                "id": "kp_1",
                "point": "Fed raised rates 50bps.",
                "impact": 0.8,
                "rationale": "Surprise magnitude reprices duration risk.",
            },
            {
                "point": "Growth stocks sold off.",
                "impact": -0.4,
                "rationale": "Higher discount rates hurt long-duration earnings.",
            },
        ],
        "confidence": 0.9,
    })
    scores, reasoning, confidence = _parse_key_points_response(raw)
    assert confidence == pytest.approx(0.9)
    assert scores["kp_1"] == pytest.approx(0.8)
    assert scores["kp_2"] == pytest.approx(-0.4)
    assert "Fed raised rates" in reasoning["kp_1"]
    assert "Growth stocks" in reasoning["kp_2"]


def test_aggregate_heads_excludes_story_key_points():
    heads = [
        HeadOutput(
            cluster="MACRO_SENSITIVITY",
            scores={"interest_rate_sensitivity_duration": 0.5},
            reasoning={},
            confidence=0.8,
            model="test",
            latency_ms=1,
            raw_response="",
        ),
        HeadOutput(
            cluster="STORY_KEY_POINTS",
            scores={"kp_1": 0.9},
            reasoning={"kp_1": "Major policy shift"},
            confidence=0.85,
            model="test",
            latency_ms=1,
            raw_response="",
        ),
    ]
    impact = aggregate_heads(heads)
    assert "interest_rate_sensitivity_duration" in impact
    assert "kp_1" not in impact


# ── Rationale gate + novelty ─────────────────────────────────────────────────

from services.news.scoring.claim_rationale import (  # noqa: E402
    normalize_novelty,
    rationale_adds_information,
)
from services.news.scoring.impact_scorer import _parse_key_points_payload  # noqa: E402


@pytest.mark.parametrize(
    "point,rationale",
    [
        # Live rows, Duluth 2026-09-14 — every one a restatement.
        (
            "Quarterly revenue decreased by 7.8% in Q2.",
            "Recent top-line decline indicates ongoing operational struggle.",
        ),
        (
            "Duluth's sales have been declining consistently over the past four years.",
            "Long-term revenue contraction suggests systemic issues with growth and market demand.",
        ),
        (
            "Q2 profit was inflated by a one-time tariff refund of $16.3 million.",
            "Non-recurring gains mask the underlying weakness in core operational profitability.",
        ),
        # Repeating the claim's own number is not adding one.
        (
            "Revenue fell 7.8% in Q2.",
            "A 7.8% drop in Q2 shows sales weakness.",
        ),
    ],
)
def test_rationale_gate_rejects_restatement(point, rationale):
    assert not rationale_adds_information(point, rationale)


@pytest.mark.parametrize(
    "point,rationale",
    [
        # number
        (
            "Q2 profit was inflated by a one-time tariff refund of $16.3 million.",
            "Without the refund Q2 swings to a ~$4M operating loss.",
        ),
        # horizon
        (
            "Quarterly revenue decreased by 7.8%.",
            "The holiday quarter is the next test of whether demand has stabilised.",
        ),
        # consequence
        (
            "Sales have fallen for four straight years.",
            "Shrinking revenue caps the multiple the market will pay for the balance sheet.",
        ),
    ],
)
def test_rationale_gate_accepts_new_information(point, rationale):
    assert rationale_adds_information(point, rationale)


def test_normalize_novelty():
    assert normalize_novelty("new") == "new"
    assert normalize_novelty("Priced In") == "priced_in"
    assert normalize_novelty("priced-in") == "priced_in"
    assert normalize_novelty("maybe") is None
    assert normalize_novelty(None) is None


def test_parse_key_points_payload_meta_and_gate():
    raw = json.dumps({
        "key_points": [
            {
                "id": "kp_1",
                "point": "Quarterly revenue decreased by 7.8% in Q2.",
                "impact": -0.6,
                "novelty": "priced_in",
                "novelty_basis": "Q2 reported Sep 4; piece re-analyses it",
                "rationale": "Recent top-line decline indicates ongoing operational struggle.",
            },
            {
                "id": "kp_2",
                "point": "Q2 profit included a one-time $16.3M tariff refund.",
                "impact": -0.4,
                "novelty": "new",
                "rationale": "Strip it out and Q3 guidance has no cushion.",
            },
            {
                "id": "kp_3",
                "point": "Inventory is down 12% year over year.",
                "impact": 0.2,
                "novelty": "unclear",
                "rationale": "",
            },
        ],
        "confidence": 0.8,
    })
    parsed = _parse_key_points_payload(raw)
    # Restating rationale dropped, informative one kept.
    assert parsed.reasoning["kp_1"] == "Quarterly revenue decreased by 7.8% in Q2."
    assert parsed.reasoning["kp_2"].endswith("Q3 guidance has no cushion.")
    assert parsed.rationales_dropped == 1
    assert parsed.meta["kp_1"] == {
        "novelty": "priced_in",
        "novelty_basis": "Q2 reported Sep 4; piece re-analyses it",
    }
    assert parsed.meta["kp_2"] == {"novelty": "new"}
    # An unusable label is omitted, never guessed.
    assert "kp_3" not in parsed.meta
