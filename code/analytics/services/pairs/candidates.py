"""
Candidate pair discovery off the relationship graph.

A "candidate" is any order-normalized pair (ticker_a < ticker_b) that appears
in the canonicalized graph via swingtrader.ticker_pair_candidates_v. We only
ever calibrate pairs that already share a news-verified economic link — that is
the moat over a blind universe scan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from shared.db import get_supabase_client

log = logging.getLogger(__name__)

_SCHEMA = "swingtrader"
_BLOCKED_NODE_LABELS = {"N/A", ""}


@dataclass
class CandidatePair:
    ticker_a: str
    ticker_b: str
    article_count: int
    mention_count: int
    rel_types: list[str]


def fetch_candidate_pairs(
    min_article_count: int = 2,
    min_strength: float = 0.0,
    limit: int = 5000,
) -> list[CandidatePair]:
    """Load order-normalized candidate pairs from ticker_pair_candidates_v.

    Filters mirror the relationship-graph defaults: only pairs with enough
    article evidence (and optional minimum peak strength) are worth a price fit.
    """
    client = get_supabase_client()
    res = (
        client.schema(_SCHEMA)
        .table("ticker_pair_candidates_v")
        .select(
            "ticker_a, ticker_b, article_count, mention_count, "
            "strength_max_any, rel_types"
        )
        .gte("article_count", min_article_count)
        .gte("strength_max_any", min_strength)
        .order("article_count", desc=True)
        .limit(limit)
        .execute()
    )
    out: list[CandidatePair] = []
    for row in res.data or []:
        a = str(row.get("ticker_a") or "").upper().strip()
        b = str(row.get("ticker_b") or "").upper().strip()
        if a in _BLOCKED_NODE_LABELS or b in _BLOCKED_NODE_LABELS or a == b:
            continue
        rel_types = row.get("rel_types") or []
        if not isinstance(rel_types, list):
            rel_types = [str(rel_types)]
        out.append(
            CandidatePair(
                ticker_a=a,
                ticker_b=b,
                article_count=int(row.get("article_count") or 0),
                mention_count=int(row.get("mention_count") or 0),
                rel_types=[str(r) for r in rel_types],
            )
        )
    return out
