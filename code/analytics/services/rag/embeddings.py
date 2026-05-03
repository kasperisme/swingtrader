"""
Semantic search over news embeddings.

Thin wrapper over services/news/embeddings/semantic_retrieval — keeps the
call site clean and lets us swap the underlying retrieval without touching callers.
"""

from __future__ import annotations

from typing import Any


def search_news(
    query: str,
    *,
    lookback_hours: int = 24,
    tickers: list[str] | None = None,
    article_stream: str | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Semantic search over news_article_embeddings via HNSW vector similarity.

    Returns: [{article_id, title, url, published_at, snippet, similarity, article_stream}].
    """
    from services.news.embeddings.semantic_retrieval import search_news_embeddings
    return search_news_embeddings(
        query,
        lookback_hours=lookback_hours,
        tickers=tickers,
        article_stream=article_stream,
        limit=limit,
    )


def embed_query(text: str, model: str | None = None) -> list[float]:
    """Embed a query string via Ollama (mxbai-embed-large)."""
    from services.news.embeddings.semantic_retrieval import embed_query as _embed
    return _embed(text, model=model)
