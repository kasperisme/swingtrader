"""
Backfill a single news_impact_heads cluster for articles that were ingested
before the head existed.

Selects articles that already have head rows in ``news_impact_heads`` but no row
for the target cluster, runs ONLY that head via ``score_article(body, clusters=[...])``,
and inserts the resulting row alongside the existing heads. The impact vector is
untouched — special heads (TICKER_RELATIONSHIPS, TICKER_SENTIMENT, STORY_KEY_POINTS)
are excluded from ``aggregate_heads`` by design, so no vector recompute is needed.
ARTICLE_TAGS also refreshes ``news_articles.search_tags`` (GIN-indexed).

For non-special (dimension cluster) heads, the existing impact vector is recomputed
from the merged head set.

Usage (from code/analytics):
    python -m scripts.backfill_head                                     # default: STORY_KEY_POINTS
    python -m scripts.backfill_head --head key_points --limit 100
    python -m scripts.backfill_head --head STORY_KEY_POINTS --concurrency 8
    python -m scripts.backfill_head --dry-run --limit 5
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import pathlib
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

from rich.console import Console

from shared.db import get_pg_connection, get_supabase_client, _tbl
from services.news.scoring.impact_scorer import (
    SPECIAL_HEAD_CLUSTERS,
    aggregate_heads,
    normalize_head_clusters,
    score_article,
    set_news_impact_backend,
    top_dimensions,
    HeadOutput,
)
from services.news.scoring.news_ingester import sync_article_search_tags
from services.news.scoring.score_cli import (
    _normalize_relationship_and_sentiment_heads,
    _load_identity_alias_maps,
    _strip_html,
)

console = Console()
logger = logging.getLogger(__name__)

_PAGE_SIZE = 1000


# ── DB helpers ────────────────────────────────────────────────────────────────


def _fetch_missing_ids(head_cluster: str) -> list[int]:
    """
    Articles that have head rows but no row for ``head_cluster``.

    Anti-join via direct SQL: an article qualifies if it has at least one head row
    in any cluster and no row whose ``cluster = head_cluster`` exists. The
    ``HAVING count(*) = 1`` clause on the inner query keeps the with-head set to
    article_ids that have exactly one row for the target cluster — duplicates or
    nulls fall back to the missing set and will get a clean re-insert.
    """
    console.print(
        f"[dim]Scanning news_impact_heads for articles missing {head_cluster}…[/dim]"
    )
    sql = """
        select scored.article_id
        from (
            select article_id
            from swingtrader.news_impact_heads
            group by article_id
        ) scored
        left join (
            select article_id
            from swingtrader.news_impact_heads
            where cluster = %s
            group by article_id
            having count(*) = 1
        ) have_head using (article_id)
        where have_head.article_id is null
        order by scored.article_id desc
    """
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (head_cluster,))
            missing = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

    console.print(
        f"[dim]Articles missing {head_cluster}: [bold]{len(missing)}[/bold][/dim]"
    )
    return missing


def _fetch_articles(client, ids: list[int]) -> list[dict]:
    res = (
        client.schema("swingtrader")
        .table("news_articles")
        .select("id, body, title")
        .in_("id", ids)
        .execute()
    )
    return res.data or []


def _fetch_existing_heads(client, article_id: int) -> list[HeadOutput]:
    """
    Read the article's existing head rows back as ``HeadOutput`` so we can
    recompute the impact vector after inserting a new dimension head.
    """
    res = (
        client.schema("swingtrader")
        .table("news_impact_heads")
        .select("cluster, scores_json, reasoning_json, confidence, model, latency_ms")
        .eq("article_id", article_id)
        .execute()
    )
    out: list[HeadOutput] = []
    for row in res.data or []:
        out.append(
            HeadOutput(
                cluster=row.get("cluster") or "",
                scores=row.get("scores_json") or {},
                reasoning=row.get("reasoning_json") or {},
                confidence=float(row.get("confidence") or 0.0),
                model=row.get("model") or "",
                latency_ms=int(row.get("latency_ms") or 0),
                raw_response="",
            )
        )
    return out


def _insert_head_row(client, article_id: int, head: HeadOutput) -> None:
    _tbl(client, "news_impact_heads").insert(
        {
            "article_id": article_id,
            "cluster": head.cluster,
            "scores_json": head.scores,
            "reasoning_json": head.reasoning,
            "confidence": head.confidence,
            "model": head.model,
            "latency_ms": head.latency_ms,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()


def _replace_impact_vector(client, article_id: int, impact: dict[str, float]) -> None:
    _tbl(client, "news_impact_vectors").delete().eq("article_id", article_id).execute()
    _tbl(client, "news_impact_vectors").insert(
        {
            "article_id": article_id,
            "impact_json": impact,
            "top_dimensions": top_dimensions(impact, n=5),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()


# ── Scoring ───────────────────────────────────────────────────────────────────


async def _backfill_one(
    client,
    row: dict,
    head_cluster: str,
    is_special: bool,
    ticker_alias_map: dict,
    company_alias_map: dict,
    semaphore: asyncio.Semaphore,
    *,
    index: int,
    total: int,
    dry_run: bool,
) -> bool:
    article_id = row["id"]
    title = row.get("title") or ""
    body = _strip_html(row.get("body") or "")

    if not body.strip():
        console.print(f"  [{index}/{total}] id={article_id} — skipped (empty body)")
        return False

    async with semaphore:
        console.print(
            f"[bold cyan][{index}/{total}][/bold cyan] id={article_id}  {title[:65]}"
        )
        try:
            new_heads = await score_article(body, clusters=[head_cluster])
        except Exception as exc:
            console.print(f"  [red]id={article_id} scoring failed: {exc}[/red]")
            return False

    if not new_heads:
        console.print(f"  [yellow]id={article_id} — scorer returned no heads[/yellow]")
        return False

    head = new_heads[0]
    if head.error:
        console.print(
            f"  [yellow]id={article_id} {head_cluster} returned error: {head.error}[/yellow]"
        )
        # Insert the empty row anyway so the rescore-unscored sweep can pick it up
        # uniformly later if desired. Matches the contract used by the main pipeline.

    # Canonicalise ticker keys for relationship/sentiment heads.
    if head_cluster in ("TICKER_RELATIONSHIPS", "TICKER_SENTIMENT"):
        _normalize_relationship_and_sentiment_heads(
            [head], ticker_alias_map, company_alias_map
        )

    n_keys = len(head.scores)
    console.print(
        f"  id={article_id}  {head_cluster}: {n_keys} entries  conf={head.confidence:.2f}"
    )

    if dry_run:
        return True

    _insert_head_row(client, article_id, head)

    all_heads = _fetch_existing_heads(client, article_id)
    sync_article_search_tags(client, article_id, all_heads)

    if not is_special:
        impact = aggregate_heads(all_heads)
        _replace_impact_vector(client, article_id, impact)

    return True


# ── Main ─────────────────────────────────────────────────────────────────────


async def main(args: argparse.Namespace) -> None:
    if args.news_impact_backend:
        set_news_impact_backend(args.news_impact_backend)

    [head_cluster] = normalize_head_clusters([args.head])
    is_special = head_cluster in SPECIAL_HEAD_CLUSTERS

    console.print(
        f"[bold]Backfilling head [cyan]{head_cluster}[/cyan]"
        f" ({'special — no vector recompute' if is_special else 'dimension — vector will be recomputed'})[/bold]"
    )

    client = get_supabase_client()
    ids = _fetch_missing_ids(head_cluster)

    if args.limit is not None and args.limit > 0:
        ids = ids[: args.limit]
        console.print(f"[dim]--limit {args.limit}: capped to {len(ids)} article(s)[/dim]")

    total = len(ids)
    if total == 0:
        console.print("[green]Nothing to backfill — every scored article already has this head.[/green]")
        return

    if args.dry_run:
        console.print("[yellow]DRY RUN — no DB writes[/yellow]")

    try:
        ticker_alias_map, company_alias_map = _load_identity_alias_maps()
    except Exception as exc:
        logger.warning("Failed to load identity alias maps: %s", exc)
        ticker_alias_map, company_alias_map = {}, {}

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    succeeded = 0
    failed = 0
    seen = 0

    for batch_start in range(0, total, args.batch_size):
        batch_ids = ids[batch_start : batch_start + args.batch_size]
        rows = _fetch_articles(client, batch_ids)
        rows_by_id = {r["id"]: r for r in rows}

        tasks = []
        for offset, aid in enumerate(batch_ids):
            row = rows_by_id.get(aid)
            if row is None:
                failed += 1
                console.print(
                    f"  [yellow]id={aid} not found in news_articles, skipping[/yellow]"
                )
                continue
            seen += 1
            tasks.append(
                _backfill_one(
                    client,
                    row,
                    head_cluster,
                    is_special,
                    ticker_alias_map,
                    company_alias_map,
                    semaphore,
                    index=batch_start + offset + 1,
                    total=total,
                    dry_run=args.dry_run,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                failed += 1
                console.print(f"  [red]batch error: {r}[/red]")
            elif r:
                succeeded += 1
            else:
                failed += 1

    console.print(
        f"\n[bold]Done.[/bold]  succeeded={succeeded}  failed/skipped={failed}  seen={seen}"
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--head",
        default="STORY_KEY_POINTS",
        help="Head cluster to backfill. Accepts aliases (e.g. key_points). Default: STORY_KEY_POINTS",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap total articles to backfill (newest id first). Default: no cap.",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max articles scored in parallel. Default: 5.",
    )
    p.add_argument(
        "--batch-size",
        dest="batch_size",
        type=int,
        default=50,
        help="Articles fetched per DB query. Default: 50.",
    )
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Score but do not insert head rows or touch impact vectors.",
    )
    p.add_argument(
        "--news-impact-backend",
        dest="news_impact_backend",
        choices=["ollama", "anthropic", "do_agent"],
        default=None,
        help="Override NEWS_IMPACT_BACKEND for this run.",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true", help="Debug logging"
    )
    return p


if __name__ == "__main__":
    args = _build_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    asyncio.run(main(args))
