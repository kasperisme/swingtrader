"""
Backfill gte-small embeddings into swingtrader.news_article_embeddings_gte.

Usage:
  python -m news_impact.gte_backfill --limit 200
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
from typing import Iterable

import httpx

from src.db import get_pg_connection, get_schema

logger = logging.getLogger(__name__)


def _chunk_text(text: str, max_chars: int = 900, overlap_chars: int = 120) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return [text]
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + max_chars)
        if j < n:
            split = text.rfind(". ", i + max_chars // 2, j)
            if split > i:
                j = split + 1
        chunk = text[i:j].strip()
        if chunk:
            out.append(chunk)
        if j >= n:
            break
        i = max(j - overlap_chars, i + 1)
    return out


def _vector_literal(values: Iterable[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in values) + "]"


def _embed_text(client: httpx.Client, text: str) -> list[float]:
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not base or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")

    r = client.post(
        f"{base}/functions/v1/embed",
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "Content-Type": "application/json",
        },
        json={"input": text},
    )
    r.raise_for_status()
    data = r.json()
    emb = data.get("embedding")
    if not isinstance(emb, list):
        raise RuntimeError("embed function returned invalid payload")
    return [float(x) for x in emb]


def run(limit: int) -> tuple[int, int]:
    schema = get_schema()
    conn = get_pg_connection()
    done = 0
    failed = 0
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT na.id, na.title, na.body
            FROM {schema}.news_articles na
            WHERE NOT EXISTS (
              SELECT 1
              FROM {schema}.news_article_embeddings_gte e
              WHERE e.article_id = na.id
            )
            ORDER BY na.id DESC
            LIMIT %s
            """,
            (int(limit),),
        )
        rows = cur.fetchall() or []
        if not rows:
            return 0, 0

        with httpx.Client(timeout=60.0) as client:
            for article_id, title, body in rows:
                try:
                    text = f"{title or ''}\n\n{body or ''}".strip()
                    chunks = _chunk_text(text)
                    if not chunks:
                        continue
                    for i, chunk in enumerate(chunks):
                        vec = _embed_text(client, chunk)
                        chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                        cur.execute(
                            f"""
                            INSERT INTO {schema}.news_article_embeddings_gte
                              (article_id, chunk_index, chunk_hash, chunk_text, embedding, embedding_model)
                            VALUES (%s, %s, %s, %s, %s::vector, 'gte-small')
                            ON CONFLICT (article_id, chunk_index, embedding_model) DO UPDATE
                              SET chunk_hash = EXCLUDED.chunk_hash,
                                  chunk_text = EXCLUDED.chunk_text,
                                  embedding = EXCLUDED.embedding,
                                  created_at = NOW()
                            """,
                            (int(article_id), i, chunk_hash, chunk, _vector_literal(vec)),
                        )
                    conn.commit()
                    done += 1
                except Exception as exc:
                    conn.rollback()
                    failed += 1
                    logger.warning("article_id=%s failed: %s", article_id, exc)
        return done, failed
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill gte-small article embeddings")
    parser.add_argument("--limit", type=int, default=100, help="Max articles to backfill")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ok, bad = run(args.limit)
    print(f"backfilled={ok} failed={bad}")


if __name__ == "__main__":
    main()
