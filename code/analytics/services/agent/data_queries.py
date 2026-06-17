"""
Backward-compatible re-exports from services.rag.

All query logic has moved to services/rag/. This module keeps existing
callers working without changes.
"""

from services.rag.articles import get_top_articles, get_ticker_news, get_news_by_tag
from services.rag.sentiment import get_cluster_trends, get_dimension_trends, get_ticker_sentiment
from services.rag.portfolio import (
    get_user_positions,
    get_user_alerts,
    get_user_screening_notes,
    get_user_screening_note_details,
    get_user_trading_strategy,
    get_ticker_chat_history,
)
from services.rag.graph import get_ticker_relationships, get_company_vectors
from services.rag.embeddings import search_news

__all__ = [
    "get_top_articles", "get_ticker_news", "get_news_by_tag",
    "get_cluster_trends", "get_dimension_trends", "get_ticker_sentiment",
    "get_user_positions", "get_user_alerts", "get_user_screening_notes",
    "get_user_screening_note_details",
    "get_user_trading_strategy", "get_ticker_chat_history",
    "get_ticker_relationships", "get_company_vectors",
    "search_news",
]
