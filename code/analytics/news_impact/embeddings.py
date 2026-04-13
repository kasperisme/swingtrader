"""
Embedding pipeline for news article semantic retrieval.

Split-job model:
  1) score_news_cli enqueues article IDs
  2) embeddings_cli processes jobs and writes chunk embeddings
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Iterable

import httpx

from src.db import get_pg_connection, get_schema

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_BASE = "http://localhost:11434"
_DEFAULT_EMBED_MODEL = "mxbai-embed-large"


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


def _embed_ollama(texts: list[str], model: str, timeout: float = 60.0) -> list[list[float]]:
    if not texts:
        return []
    base = os.environ.get("OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE).rstrip("/")
    payload = {"model": model, "input": texts}
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{base}/api/embed", json=payload)
        if r.status_code == 404:
            embeddings: list[list[float]] = []
            for t in texts:
                r2 = client.post(f"{base}/api/embeddings", json={"model": model, "prompt": t})
                r2.raise_for_status()
                d2 = r2.json()
                vec = d2.get("embedding")
                if not isinstance(vec, list):
                    raise RuntimeError("Malformed /api/embeddings response from Ollama")
                embeddings.append([float(x) for x in vec])
            return embeddings
        r.raise_for_status()
        data = r.json()
    emb = data.get("embeddings")
    if not isinstance(emb, list):
        raise RuntimeError("Malformed /api/embed response from Ollama")
    return [[float(x) for x in vec] for vec in emb]


def enqueue_article_embedding_job(article_id: int) -> None:
    schema = get_schema()
    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            INSERT INTO {schema}.news_article_embedding_jobs
              (article_id, status, attempt_count, last_error, completed_at, updated_at)
            VALUES (%s, 'pending', 0, NULL, NULL, NOW())
            ON CONFLICT (article_id) DO UPDATE
              SET status='pending',
                  last_error=NULL,
                  completed_at=NULL,
                  updated_at=NOW()
            """,
            (int(article_id),),
        )
        conn.commit()
    finally:
        conn.close()


def enqueue_missing_embedding_jobs(limit: int = 1000) -> int:
    schema = get_schema()
    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            INSERT INTO {schema}.news_article_embedding_jobs
              (article_id, status, attempt_count, created_at, updated_at)
            SELECT na.id, 'pending', 0, NOW(), NOW()
            FROM {schema}.news_articles na
            LEFT JOIN {schema}.news_article_embedding_jobs j
              ON j.article_id = na.id
            LEFT JOIN {schema}.news_article_embeddings e
              ON e.article_id = na.id
            WHERE j.article_id IS NULL
              AND e.article_id IS NULL
            ORDER BY na.id DESC
            LIMIT %s
            """,
            (int(limit),),
        )
        inserted = cur.rowcount or 0
        conn.commit()
        return inserted
    finally:
        conn.close()


def process_embedding_jobs(
    limit: int = 50,
    retry_failed: bool = False,
    model: str | None = None,
    timeout: float = 60.0,
) -> tuple[int, int]:
    """
    Process pending embedding jobs.
    Returns (completed_count, failed_count).
    """
    embed_model = (model or os.environ.get("OLLAMA_EMBED_MODEL") or _DEFAULT_EMBED_MODEL).strip()
    schema = get_schema()
    conn = get_pg_connection()
    completed = 0
    failed = 0
    try:
        cur = conn.cursor()
        status_clause = "IN ('pending','failed')" if retry_failed else "= 'pending'"
        cur.execute(
            f"""
            SELECT article_id
            FROM {schema}.news_article_embedding_jobs
            WHERE status {status_clause}
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (int(limit),),
        )
        ids = [int(r[0]) for r in (cur.fetchall() or [])]
        for article_id in ids:
            try:
                cur.execute(
                    f"""
                    UPDATE {schema}.news_article_embedding_jobs
                    SET status='processing',
                        attempt_count=attempt_count+1,
                        last_attempt_at=NOW(),
                        updated_at=NOW()
                    WHERE article_id=%s
                    """,
                    (article_id,),
                )
                conn.commit()

                cur.execute(
                    f"SELECT title, body FROM {schema}.news_articles WHERE id=%s LIMIT 1",
                    (article_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("Article not found")

                title, body = row[0] or "", row[1] or ""
                combined = f"{title}\n\n{body}".strip()
                chunks = _chunk_text(combined)
                if not chunks:
                    raise RuntimeError("No chunkable text")
                vectors = _embed_ollama(chunks, model=embed_model, timeout=timeout)
                if len(vectors) != len(chunks):
                    raise RuntimeError("Embedding count mismatch")

                cur.execute(
                    f"""
                    DELETE FROM {schema}.news_article_embeddings
                    WHERE article_id=%s AND embedding_model=%s
                    """,
                    (article_id, embed_model),
                )
                for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                    chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                    cur.execute(
                        f"""
                        INSERT INTO {schema}.news_article_embeddings
                          (article_id, chunk_index, chunk_hash, chunk_text, embedding, embedding_model)
                        VALUES (%s, %s, %s, %s, %s::vector, %s)
                        ON CONFLICT (article_id, chunk_index, embedding_model) DO UPDATE
                          SET chunk_hash=EXCLUDED.chunk_hash,
                              chunk_text=EXCLUDED.chunk_text,
                              embedding=EXCLUDED.embedding,
                              created_at=NOW()
                        """,
                        (article_id, i, chunk_hash, chunk, _vector_literal(vec), embed_model),
                    )

                cur.execute(
                    f"""
                    UPDATE {schema}.news_article_embedding_jobs
                    SET status='completed',
                        last_error=NULL,
                        completed_at=NOW(),
                        updated_at=NOW()
                    WHERE article_id=%s
                    """,
                    (article_id,),
                )
                conn.commit()
                completed += 1
            except Exception as exc:
                conn.rollback()
                cur.execute(
                    f"""
                    UPDATE {schema}.news_article_embedding_jobs
                    SET status='failed',
                        last_error=%s,
                        updated_at=NOW()
                    WHERE article_id=%s
                    """,
                    (str(exc)[:1200], article_id),
                )
                conn.commit()
                failed += 1
                logger.warning("[embeddings] article_id=%s failed: %s", article_id, exc)
        return completed, failed
    finally:
        conn.close()


def cleanup_embedding_orphans() -> tuple[int, int]:
    """Remove orphan jobs/embeddings whose article row no longer exists."""
    schema = get_schema()
    conn = get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            DELETE FROM {schema}.news_article_embeddings e
            WHERE NOT EXISTS (
              SELECT 1 FROM {schema}.news_articles a WHERE a.id = e.article_id
            )
            """
        )
        deleted_emb = cur.rowcount or 0
        cur.execute(
            f"""
            DELETE FROM {schema}.news_article_embedding_jobs j
            WHERE NOT EXISTS (
              SELECT 1 FROM {schema}.news_articles a WHERE a.id = j.article_id
            )
            """
        )
        deleted_jobs = cur.rowcount or 0
        conn.commit()
        return deleted_emb, deleted_jobs
    finally:
        conn.close()
