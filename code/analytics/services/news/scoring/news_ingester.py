"""
News article ingestion pipeline.

Full flow: article text → 8 LLM heads → aggregate → persist to Supabase.
Deduplicates by normalized URL when present, otherwise sha256(body).
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from postgrest.exceptions import APIError
from supabase import Client

from shared.db import get_supabase_client, _as_json, patch_news_article_image_if_missing
from services.news.scoring.impact_scorer import score_article, aggregate_heads, top_dimensions, HeadOutput

__all__ = ["ingest_article", "_sha256", "_normalize_url", "_check_existing", "_persist"]

logger = logging.getLogger(__name__)


def _sha256(text: str) -> str:
    """Return the hex SHA-256 digest of a UTF-8 string — used as dedup article_hash."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_url(url: Optional[str]) -> str:
    """
    Normalize a URL for stable dedupe: trim, strip fragment, lower-case host,
    strip trailing slash on path, default https if scheme missing.
    """
    if not url or not str(url).strip():
        return ""
    raw = str(url).strip()
    parts = urlsplit(raw)
    if not parts.netloc:
        return raw
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = (parts.path or "").rstrip("/") or "/"
    query = parts.query
    return urlunsplit((scheme, netloc, path, query, ""))


def _tbl(client: Client, table: str):
    """Return a schema-aware PostgREST table query builder."""
    return client.schema("swingtrader").table(table)


def _impact_for_article_id(client: Client, article_id: int) -> dict:
    vec_res = (
        _tbl(client, "news_impact_vectors")
        .select("impact_json")
        .eq("article_id", article_id)
        .limit(1)
        .execute()
    )
    if vec_res.data:
        return _as_json(vec_res.data[0]["impact_json"], default={})
    return {}


def _article_row_by_url(client: Client, url: str) -> Optional[int]:
    """Return article id if a row exists with this exact url string."""
    art_res = _tbl(client, "news_articles").select("id").eq("url", url).limit(1).execute()
    if not art_res.data:
        return None
    return int(art_res.data[0]["id"])


def _check_existing(
    client: Client,
    article_hash: str,
    url: Optional[str] = None,
) -> Optional[tuple[int, dict]]:
    """
    Returns (article_id, impact_vector) if the article is already in the DB.

    When ``url`` is non-empty, matches on normalized URL first (and legacy raw URL),
    then falls back to ``article_hash``.
    """
    url_norm = _normalize_url(url)
    article_id: Optional[int] = None

    if url_norm:
        article_id = _article_row_by_url(client, url_norm)
        if article_id is None:
            raw = (url or "").strip()
            if raw and raw != url_norm:
                article_id = _article_row_by_url(client, raw)

    if article_id is None:
        art_res = (
            _tbl(client, "news_articles")
            .select("id")
            .eq("article_hash", article_hash)
            .limit(1)
            .execute()
        )
        if not art_res.data:
            return None
        article_id = int(art_res.data[0]["id"])

    impact = _impact_for_article_id(client, article_id)
    return article_id, impact


def _delete_heads_and_vector(client: Client, article_id: int) -> None:
    """Remove existing heads and vector rows for an article (used before refresh)."""
    _tbl(client, "news_impact_heads").delete().eq("article_id", article_id).execute()
    _tbl(client, "news_impact_vectors").delete().eq("article_id", article_id).execute()


def _processing_status(heads: list[HeadOutput]) -> str:
    """
    Derive completeness status from head results.
      complete — all heads succeeded
      partial  — mix of successes and failures (e.g. one head timed out)
      failed   — every head failed (e.g. API key expired)
    """
    if not heads:
        return "failed"
    failed = sum(1 for h in heads if h.error)
    if failed == 0:
        return "complete"
    if failed == len(heads):
        return "failed"
    return "partial"


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
    image_url: Optional[str] = None,
    article_stream: Optional[str] = None,
) -> int:
    """
    Insert (or re-use) article row, then insert heads and vector.
    Returns article_id.

    If existing_article_id is provided, the article row already exists and
    we only write new heads/vector rows (caller must have deleted the old ones).
    """
    now = datetime.now().isoformat()
    status = _processing_status(heads)

    if existing_article_id is not None:
        article_id = existing_article_id
        update_fields: dict = {"processing_status": status}
        if image_url and str(image_url).strip():
            update_fields["image_url"] = str(image_url).strip()
        _tbl(client, "news_articles").update(update_fields).eq("id", article_id).execute()
    else:
        url_stored = _normalize_url(url) if url else None
        row = {
            "created_at": now,
            "url": url_stored or url,
            "title": title,
            "body": body,
            "source": source,
            "article_hash": article_hash,
            "article_stream": article_stream or "unknown",
            "processing_status": status,
        }
        if published_at is not None:
            row["published_at"] = published_at
        if publisher is not None:
            row["publisher"] = publisher
        if image_url and str(image_url).strip():
            row["image_url"] = str(image_url).strip()
        try:
            art_res = _tbl(client, "news_articles").insert(row).execute()
            article_id = int(art_res.data[0]["id"])
        except APIError as exc:
            # Same body under another URL, race, or missed cache — reuse row and refresh heads.
            if exc.code != "23505":
                raise
            combined = f"{exc.message or ''} {exc.details or ''}".lower()
            if "article_hash" not in combined:
                raise
            existing_row = _check_existing(client, article_hash, url=url)
            if existing_row is None:
                raise
            article_id = existing_row[0]
            _delete_heads_and_vector(client, article_id)
            collision_update: dict = {"processing_status": status}
            if image_url and str(image_url).strip():
                collision_update["image_url"] = str(image_url).strip()
            _tbl(client, "news_articles").update(collision_update).eq("id", article_id).execute()

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
    image_url: Optional[str] = None,
    article_stream: Optional[str] = None,
) -> tuple[int, dict[str, float]]:
    """
    Full pipeline: article → 8 LLM heads → aggregate → persist → return
    (article_id, impact_vector).

    Deduplicates by normalized URL when present, otherwise sha256(body).
    If the article already exists and refresh=False, returns the cached result
    without LLM calls. If refresh=True, re-scores and overwrites the stored heads and vector.
    """
    article_hash = _sha256(body)

    client = get_supabase_client()
    existing = _check_existing(client, article_hash, url=url)

    if existing is not None and not refresh:
        article_id, impact = existing
        patch_news_article_image_if_missing(client, article_id, image_url)
        logger.info(
            "[news_ingester] duplicate article id=%d url=%r hash=%s… — returning cached result",
            article_id,
            _normalize_url(url) or "",
            article_hash[:12],
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
            image_url=image_url,
            article_stream=article_stream,
        )
    else:
        article_id = _persist(
            client, body, article_hash, url, title, source, heads, impact,
            published_at=published_at,
            publisher=publisher,
            image_url=image_url,
            article_stream=article_stream,
        )

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
