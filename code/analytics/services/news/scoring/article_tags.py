"""
Search tags for news articles — normalization, prompt guidance, and denormalized sync.

The ARTICLE_TAGS LLM head invents short theme/event slugs (not a fixed allowlist).
``build_search_tags`` merges those with tickers from TICKER_SENTIMENT.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.news.scoring.impact_scorer import HeadOutput

# Examples only — the model may create other slugs following the same conventions.
TAG_PROMPT_EXAMPLES: tuple[str, ...] = (
    "fed",
    "rates",
    "inflation",
    "earnings",
    "guidance",
    "m_and_a",
    "ipo",
    "regulation",
    "trade",
    "tariffs",
    "geopolitics",
    "oil",
    "ai",
    "semiconductors",
    "banking",
    "layoffs",
)

_MAX_ARTICLE_TAGS = 12
_MIN_SLUG_LEN = 2


def normalize_tag_slug(raw: str) -> str:
    """Normalize free text to a lowercase slug (max 48 chars)."""
    s = re.sub(r"[^a-z0-9]+", "_", str(raw or "").lower().strip())
    return s.strip("_")[:48]


def parse_article_tags(raw_tags: list) -> list[str]:
    """
    Normalize LLM tag strings: slugify, dedupe, drop empties, cap count.

    No allowlist — any well-formed slug is kept.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_tags:
        slug = normalize_tag_slug(raw)
        if len(slug) < _MIN_SLUG_LEN or slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
        if len(out) >= _MAX_ARTICLE_TAGS:
            break
    return sorted(out)


def build_search_tags(heads: list["HeadOutput"]) -> list[str]:
    """
    Denormalized tag list for ``news_articles.search_tags``.

    - ARTICLE_TAGS head → theme/event slugs (scores_json keys)
    - TICKER_SENTIMENT → uppercase tickers (indexed separately)
    """
    tags: set[str] = set()
    for head in heads:
        if head.cluster == "ARTICLE_TAGS":
            for key, val in (head.scores or {}).items():
                slug = normalize_tag_slug(key)
                if slug and float(val) > 0:
                    tags.add(slug)
        elif head.cluster == "TICKER_SENTIMENT":
            for key, val in (head.scores or {}).items():
                ticker = str(key).upper().strip()
                if ticker and abs(float(val)) >= 0.05:
                    tags.add(ticker)
    return sorted(tags)


def tag_prompt_guidance() -> str:
    """Direction + examples for the ARTICLE_TAGS LLM prompt (not an exhaustive list)."""
    examples = ", ".join(TAG_PROMPT_EXAMPLES)
    return f"""\
Purpose — these tags power fast news refetch:
- Each slug is stored on the article and indexed for search.
- When a user later searches (e.g. "fed rates", "earnings warning", "middle east oil"),
  the query is split into lowercase tokens and matched against stored tags.
  Any overlap returns the article — no full-text or semantic pass required.
- Tag for retrieval: ask "what short queries should surface this story again?"
  Prefer stable, reusable concepts investors might type, not one-off headline phrases.

Tagging rules:
- Invent 4–12 short lowercase slugs (snake_case: rate_cut, profit_warning, ai_chips).
- Use vocabulary users are likely to search: themes, events, sectors, policy, geographies.
- Be specific when the article is specific; avoid vague slugs (news, market, stocks, update).
- Prefer one clear slug per idea; do not duplicate the same concept under different names.
- Do not output stock tickers here (tickers are indexed separately from sentiment).

Example slugs (you may use these or create new ones in the same style): {examples}"""
