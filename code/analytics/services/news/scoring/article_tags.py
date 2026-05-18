"""
Search tags for news articles — taxonomy, normalization, and denormalized sync.

The ARTICLE_TAGS LLM head picks theme/event slugs from ``TAG_TAXONOMY``.
``build_search_tags`` merges those with tickers from TICKER_SENTIMENT so search
does not need a separate ticker-extraction pass for filtering.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.news.scoring.impact_scorer import HeadOutput

# Controlled vocabulary — lowercase slugs, stable for GIN search and LLM picks.
TAG_TAXONOMY: tuple[str, ...] = (
    "fed",
    "rates",
    "inflation",
    "employment",
    "recession",
    "gdp",
    "fiscal",
    "banking",
    "credit",
    "earnings",
    "guidance",
    "revenue",
    "profit_warning",
    "m_and_a",
    "ipo",
    "buyback",
    "dividend",
    "default",
    "regulation",
    "antitrust",
    "trade",
    "tariffs",
    "geopolitics",
    "china",
    "europe",
    "middle_east",
    "energy",
    "oil",
    "gas",
    "utilities",
    "tech",
    "ai",
    "semiconductors",
    "crypto",
    "healthcare",
    "pharma",
    "defense",
    "aerospace",
    "autos",
    "retail",
    "housing",
    "consumer",
    "industrials",
    "materials",
    "supply_chain",
    "layoffs",
    "strike",
    "legal",
    "cyber",
    "climate",
)

_TAXONOMY_SET = frozenset(TAG_TAXONOMY)
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


def normalize_tag_slug(raw: str) -> str:
    """Normalize free text to a lowercase slug (max 48 chars)."""
    s = re.sub(r"[^a-z0-9]+", "_", str(raw or "").lower().strip())
    return s.strip("_")[:48]


def filter_taxonomy_tags(slugs: list[str]) -> list[str]:
    """Keep only slugs in ``TAG_TAXONOMY``, deduped, sorted."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in slugs:
        slug = normalize_tag_slug(raw)
        if not slug or slug not in _TAXONOMY_SET or slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
    return sorted(out)


def build_search_tags(heads: list["HeadOutput"]) -> list[str]:
    """
    Denormalized tag list for ``news_articles.search_tags``.

    - ARTICLE_TAGS head → taxonomy slugs (scores_json keys)
    - TICKER_SENTIMENT → uppercase tickers (cheap, no extra LLM)
    """
    tags: set[str] = set()
    for head in heads:
        if head.cluster == "ARTICLE_TAGS":
            for key, val in (head.scores or {}).items():
                slug = normalize_tag_slug(key)
                if slug and slug in _TAXONOMY_SET and float(val) > 0:
                    tags.add(slug)
        elif head.cluster == "TICKER_SENTIMENT":
            for key, val in (head.scores or {}).items():
                ticker = str(key).upper().strip()
                if ticker and abs(float(val)) >= 0.05:
                    tags.add(ticker)
    return sorted(tags)


def taxonomy_prompt_block() -> str:
    """Compact comma-separated list for the LLM user prompt."""
    return ", ".join(TAG_TAXONOMY)
