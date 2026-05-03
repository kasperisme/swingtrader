from __future__ import annotations

import logging
from typing import Any

from services.rag.articles import get_top_articles, fetch_tickers_for_articles
from services.rag.sentiment import get_cluster_trends, compute_cluster_summary
from services.rag.taxonomy import CLUSTER_ID_TO_LABEL, DIM_KEY_TO_LABEL

from .config import LOOKBACK_HOURS, MAX_ARTICLES

log = logging.getLogger(__name__)


def fetch_cluster_trends(hours: int | None = None) -> list[dict[str, Any]]:
    rows = get_cluster_trends(hours=hours or LOOKBACK_HOURS)
    log.info("Fetched %d cluster daily trend rows", len(rows))
    return rows


def fetch_top_articles(max_articles: int | None = None) -> list[dict[str, Any]]:
    articles = get_top_articles(hours=LOOKBACK_HOURS, limit=max_articles or MAX_ARTICLES)
    if not articles:
        log.warning("No articles in last %d hours", LOOKBACK_HOURS)
    else:
        log.info("Fetched %d scored articles", len(articles))
    return articles


# Re-export so existing callers keep working
__all__ = [
    "fetch_cluster_trends",
    "fetch_top_articles",
    "fetch_tickers_for_articles",
    "compute_cluster_summary",
]
