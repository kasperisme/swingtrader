"""
News article ingestion pipeline.

Full flow: article text → 8 LLM heads → aggregate → persist to Supabase.
Deduplicates by sha256(body) — already-ingested articles return immediately.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Optional

from supabase import Client

from src.db import get_supabase_client, get_schema, _as_json
from news_impact.impact_scorer import score_article, aggregate_heads, top_dimensions, HeadOutput

__all__ = ["ingest_article", "_sha256", "_check_existing", "_persist"]

logger = logging.getLogger(__name__)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tbl(client: Client, table: str):
    return client.schema(get_schema()).table(table)


def _check_existing(client: Client, article_hash: str) -> Optional[tuple[int, dict]]:
    """
    Returns (article_id, impact_vector) if the article is already in the DB,
    otherwise None.
    """
    art_res = _tbl(client, "news_articles").select("id").eq("article_hash", article_hash).limit(1).execute()
    if not art_res.data:
        return None

    article_id = int(art_res.data[0]["id"])
    vec_res = (
        _tbl(client, "news_impact_vectors")
        .select("impact_json")
        .eq("article_id", article_id)
        .limit(1)
        .execute()
    )
    if vec_res.data:
        impact = _as_json(vec_res.data[0]["impact_json"], default={})
        return article_id, impact
    return article_id, {}


def _delete_heads_and_vector(client: Client, article_id: int) -> None:
    """Remove existing heads and vector rows for an article (used before refresh)."""
    _tbl(client, "news_impact_heads").delete().eq("article_id", article_id).execute()
    _tbl(client, "news_impact_vectors").delete().eq("article_id", article_id).execute()


def _persist(
    client: Client,
    body: str,
    article_hash: str,
    url: Optional[str],
    title: Optional[str],
    source: Optional[str],
    heads: list[HeadOutput],
    impact: dict[str, float],
    existing_article_id: Optional[int] = None,
    published_at: Optional[str] = None,
    publisher: Optional[str] = None,
) -> int:
    """
    Insert (or re-use) article row, then insert heads and vector.
    Returns article_id.

    If existing_article_id is provided, the article row already exists and
    we only write new heads/vector rows (caller must have deleted the old ones).
    """
    now = datetime.now().isoformat()

    if existing_article_id is not None:
        article_id = existing_article_id
    else:
        row = {
            "created_at": now,
            "url": url,
            "title": title,
            "body": body,
            "source": source,
            "article_hash": article_hash,
        }
        if published_at is not None:
            row["published_at"] = published_at
        if publisher is not None:
            row["publisher"] = publisher
        art_res = _tbl(client, "news_articles").insert(row).execute()
        article_id = int(art_res.data[0]["id"])

    # Insert one head row per cluster
    if heads:
        head_rows = [
            {
                "article_id": article_id,
                "cluster": head.cluster,
                "scores_json": head.scores,
                "reasoning_json": head.reasoning,
                "confidence": head.confidence,
                "model": head.model,
                "latency_ms": head.latency_ms,
                "created_at": now,
            }
            for head in heads
        ]
        _tbl(client, "news_impact_heads").insert(head_rows).execute()

    # Aggregate impact vector row
    top = top_dimensions(impact, n=5)
    _tbl(client, "news_impact_vectors").insert({
        "article_id": article_id,
        "impact_json": impact,
        "top_dimensions": top,
        "created_at": now,
    }).execute()

    return article_id


async def ingest_article(
    body: str,
    url: Optional[str] = None,
    title: Optional[str] = None,
    source: Optional[str] = None,
    db_path: Optional[str] = None,  # kept for call-site compat, ignored
    refresh: bool = False,
    published_at: Optional[str] = None,
    publisher: Optional[str] = None,
) -> tuple[int, dict[str, float]]:
    """
    Full pipeline: article → 8 LLM heads → aggregate → persist → return
    (article_id, impact_vector).

    Deduplicates by sha256(body). If the article already exists and
    refresh=False, returns the cached result without LLM calls.
    If refresh=True, re-scores and overwrites the stored heads and vector.
    """
    article_hash = _sha256(body)

    client = get_supabase_client()
    existing = _check_existing(client, article_hash)

    if existing is not None and not refresh:
        article_id, impact = existing
        logger.info(
            "[news_ingester] duplicate article %s (id=%d) — returning cached result",
            article_hash[:12], article_id,
        )
        return article_id, impact

    logger.info(
        "[news_ingester] %s article (hash=%s…)",
        "refreshing" if existing else "scoring", article_hash[:12],
    )
    heads = await score_article(body)
    impact = aggregate_heads(heads)

    scored_heads = sum(1 for h in heads if not h.error)
    logger.info(
        "[news_ingester] %d/%d heads succeeded, %d impact dims",
        scored_heads, len(heads), len(impact),
    )

    if existing is not None:
        existing_article_id = existing[0]
        _delete_heads_and_vector(client, existing_article_id)
        article_id = _persist(
            client, body, article_hash, url, title, source, heads, impact,
            existing_article_id=existing_article_id,
            published_at=published_at,
            publisher=publisher,
        )
    else:
        article_id = _persist(client, body, article_hash, url, title, source, heads, impact,
                              published_at=published_at, publisher=publisher)

    logger.info("[news_ingester] persisted article_id=%d", article_id)
    return article_id, impact


if __name__ == "__main__":
    import asyncio
    import pathlib
    from dotenv import load_dotenv

    load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

    _DEMO = (
        "The Federal Reserve raised interest rates by 50 basis points today, "
        "surprising markets that had expected only 25bps. Chair Powell signalled "
        "further hikes ahead to combat persistent inflation. Treasury yields surged "
        "and bank stocks rallied while growth stocks sold off sharply."
    )

    async def _demo():
        article_id, impact = await ingest_article(
            body=_DEMO,
            title="Fed raises 50bps",
            source="demo",
        )
        print(f"article_id={article_id}")
        print(f"impact dims={len(impact)}")
        for dim, score in sorted(impact.items(), key=lambda x: abs(x[1]), reverse=True)[:8]:
            print(f"  {dim:<40} {score:+.3f}")

    asyncio.run(_demo())
