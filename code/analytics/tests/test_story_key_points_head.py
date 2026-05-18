"""Unit tests for STORY_KEY_POINTS head parsing."""

import json

import pytest

from services.news.scoring.impact_scorer import (
    EXPECTED_HEAD_COUNT,
    SPECIAL_HEAD_CLUSTERS,
    _parse_key_points_response,
    aggregate_heads,
    HeadOutput,
)
from services.news.scoring.dimensions import CLUSTERS


def test_expected_head_count():
    assert len(CLUSTERS) == 9
    assert "STORY_KEY_POINTS" in SPECIAL_HEAD_CLUSTERS
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
