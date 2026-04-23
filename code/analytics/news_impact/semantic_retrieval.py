from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from src.db import get_pg_connection, get_schema

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_BASE = "http://localhost:11434"
_DEFAULT_EMBED_MODEL = "mxbai-embed-large"
_MXBAI_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def embed_query(text: str, model: Optional[str] = None, timeout: float = 30.0) -> list[float]:
    q = (text or "").strip()
    if not q:
        return []
    base = os.environ.get("OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE).rstrip("/")
    embed_model = (model or os.environ.get("OLLAMA_EMBED_MODEL") or _DEFAULT_EMBED_MODEL).strip()
    input_text = _MXBAI_QUERY_PREFIX + q
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{base}/api/embed", json={"model": embed_model, "input": [input_text]})
        if r.status_code == 404:
            r = client.post(f"{base}/api/embeddings", json={"model": embed_model, "prompt": input_text})
            r.raise_for_status()
            d = r.json()
            emb = d.get("embedding")
            if not isinstance(emb, list):
                return []
            return [float(x) for x in emb]
        r.raise_for_status()
        d = r.json()
        embs = d.get("embeddings")
        if not isinstance(embs, list) or not embs or not isinstance(embs[0], list):
            return []
        return [float(x) for x in embs[0]]


def search_news_embeddings(
    query: str,
    *,
    lookback_hours: int = 24,
    tickers: Optional[list[str]] = None,
    article_stream: Optional[str] = None,
    limit: int = 12,
) -> list[dict]:
    """
    Search news_article_embeddings via the swingtrader.search_news_embeddings()
    SQL function (HNSW + oversample/post-filter). Returns a list of dicts with
    article_id, title, url, published_at, snippet, similarity, article_stream.
    """
    qvec = embed_query(query)
    if not qvec:
        return []
    schema = get_schema()
    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT * FROM {schema}.search_news_embeddings(%s, %s, %s, %s, %s)
            """,
            (
                qvec,
                limit,
                lookback_hours,
                article_stream,
                [t.upper() for t in tickers] if tickers else None,
            ),
        )
        rows = cur.fetchall() or []
        out = []
        for r in rows:
            out.append(
                {
                    "article_id": int(r[0]),
                    "title": r[1] or "",
                    "url": r[2] or "",
                    "published_at": r[7].isoformat() if r[7] else None,
                    "snippet": (r[8] or "")[:260],
                    "similarity": float(r[9]) if r[9] is not None else 0.0,
                    "article_stream": r[6] or "",
                }
            )
        return out
    finally:
        conn.close()
