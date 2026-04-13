from __future__ import annotations

import os
from typing import Optional

import httpx

from src.db import get_pg_connection, get_schema

_DEFAULT_OLLAMA_BASE = "http://localhost:11434"
_DEFAULT_EMBED_MODEL = "mxbai-embed-large"
_MXBAI_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


def embed_query(text: str, model: Optional[str] = None, timeout: float = 30.0) -> list[float]:
    q = (text or "").strip()
    if not q:
        return []
    base = os.environ.get("OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE).rstrip("/")
    embed_model = (model or os.environ.get("OLLAMA_EMBED_MODEL") or _DEFAULT_EMBED_MODEL).strip()
    # mxbai retrieval guidance: apply query instruction for query embeddings.
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
    Search swingtrader.news_article_embeddings (mxbai/1024) with optional ticker/stream filters.
    Returns [{article_id,title,url,published_at,snippet,similarity,article_stream}, ...]
    """
    qvec = embed_query(query)
    if not qvec:
        return []
    schema = get_schema()
    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        ticker_filter = bool(tickers)
        sql = f"""
            WITH q AS (SELECT %s::vector(1024) AS emb)
            SELECT
              na.id,
              na.title,
              na.url,
              COALESCE(na.published_at, na.created_at) AS published_at,
              e.chunk_text,
              1 - (e.embedding <=> q.emb) AS similarity,
              na.article_stream
            FROM q
            JOIN {schema}.news_article_embeddings e ON TRUE
            JOIN {schema}.news_articles na ON na.id = e.article_id
            WHERE COALESCE(na.published_at, na.created_at) >= NOW() - (%s || ' hours')::interval
              AND (%s::text IS NULL OR na.article_stream = %s::text)
              AND (
                %s = FALSE OR EXISTS (
                  SELECT 1
                  FROM {schema}.news_article_tickers nat
                  WHERE nat.article_id = na.id
                    AND nat.ticker = ANY(%s)
                )
              )
            ORDER BY e.embedding <=> q.emb
            LIMIT %s
        """
        cur.execute(
            sql,
            (
                _vector_literal(qvec),
                int(max(1, lookback_hours)),
                article_stream,
                article_stream,
                ticker_filter,
                [t.upper() for t in (tickers or [])],
                int(max(1, limit)),
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
                    "published_at": r[3].isoformat() if r[3] else None,
                    "snippet": (r[4] or "")[:260],
                    "similarity": float(r[5]) if r[5] is not None else 0.0,
                    "article_stream": r[6] or "",
                }
            )
        return out
    finally:
        conn.close()
