"""
Rescore articles that have no impact heads (e.g. failed due to Ollama HTTP 401).

Queries news_articles LEFT JOIN news_impact_heads to find all articles with zero
head rows, then re-runs the full scoring pipeline and persists the results.
The body is used as-is from the DB — no URL refetching.

Usage:
    cd code/analytics
    python -m scripts.rescore_401_articles
    python -m scripts.rescore_401_articles --concurrency 5 --batch-size 50
    python -m scripts.rescore_401_articles --dry-run --batch-size 5
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import pathlib

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

os.environ.setdefault("OLLAMA_IMPACT_MODEL", "gemma4:31b-cloud")

from src.db import get_supabase_client, get_schema, save_article_tickers
from news_impact.news_ingester import _delete_heads_and_vector, _persist, _sha256
from news_impact.impact_scorer import score_article, aggregate_heads, extract_tickers, top_dimensions
from news_impact.score_news_cli import (
    _normalize_relationship_and_sentiment_heads,
    _canonicalize_ticker_token,
    _load_identity_alias_maps,
    _strip_html,
)
from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)

PAGE_SIZE = 1000  # rows per PostgREST page when scanning the DB


# ── DB helpers ────────────────────────────────────────────────────────────────

def _paginate(client, table: str, select: str, filters: dict | None = None) -> list[dict]:
    """Paginate through a table and return all rows."""
    schema = get_schema()
    result = []
    offset = 0
    while True:
        q = client.schema(schema).table(table).select(select).range(offset, offset + PAGE_SIZE - 1)
        for col, val in (filters or {}).items():
            q = q.neq(col, val)
        res = q.execute()
        rows = res.data or []
        result.extend(rows)
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return result


def fetch_unscored_ids(client) -> list[int]:
    """
    Return IDs of all news_articles where ALL heads have scores_json = '{}',
    i.e. no head has produced any actual scores.

    Scored = has at least one head where scores_json != '{}'.
    Unscored = no such head exists (all empty, or no heads at all).
    """
    console.print("[dim]Querying DB for unscored articles…[/dim]")

    # All article IDs
    all_rows = _paginate(client, "news_articles", "id")
    all_article_ids = {row["id"] for row in all_rows}

    # Article IDs that have at least one head with non-empty scores_json → scored
    scored_rows = _paginate(client, "news_impact_heads", "article_id",
                            filters={"scores_json": "{}"})
    scored_ids = {row["article_id"] for row in scored_rows}

    unscored = sorted(all_article_ids - scored_ids)
    console.print(
        f"[dim]Found {len(all_article_ids)} articles total, "
        f"{len(scored_ids)} with non-empty heads → [bold]{len(unscored)} to rescore[/bold][/dim]"
    )
    return unscored


def fetch_articles_batch(client, ids: list[int]) -> list[dict]:
    """Fetch article rows for the given IDs."""
    schema = get_schema()
    res = (
        client.schema(schema)
        .table("news_articles")
        .select("id, body, title, url, published_at, publisher, article_stream, article_hash")
        .in_("id", ids)
        .execute()
    )
    return res.data or []


def has_non_empty_heads(client, article_id: int) -> bool:
    """Return True if the article has at least one head with non-empty scores_json."""
    schema = get_schema()
    res = (
        client.schema(schema)
        .table("news_impact_heads")
        .select("article_id")
        .eq("article_id", article_id)
        .neq("scores_json", "{}")
        .limit(1)
        .execute()
    )
    return bool(res.data)


# ── Scoring ───────────────────────────────────────────────────────────────────

async def rescore_article(
    client,
    row: dict,
    ticker_alias_map: dict,
    company_alias_map: dict,
    semaphore: asyncio.Semaphore,
    *,
    index: int,
    total: int,
    dry_run: bool = False,
) -> bool:
    """Rescore a single article. Returns True on success."""
    article_id = row["id"]
    body = row.get("body") or ""
    title = row.get("title") or ""

    body = _strip_html(body)

    if not body.strip():
        console.print(f"  [{index}/{total}] id={article_id} — skipped (empty body)")
        return False

    # Check immediately before scoring — skip if heads appeared since the batch was fetched
    if not dry_run and client and has_non_empty_heads(client, article_id):
        console.print(f"  [{index}/{total}] id={article_id} — already scored, skipping")
        return False

    async with semaphore:
        console.print(f"[bold cyan][{index}/{total}][/bold cyan] id={article_id}  {title[:65]}")
        try:
            heads, extracted_tickers = await asyncio.gather(
                score_article(body),
                extract_tickers(body),
            )
        except Exception as exc:
            console.print(f"  [red]id={article_id} scoring failed: {exc}[/red]")
            return False

    _normalize_relationship_and_sentiment_heads(heads, ticker_alias_map, company_alias_map)
    extracted_tickers = [
        t for t in (
            _canonicalize_ticker_token(t, ticker_alias_map, company_alias_map)
            for t in extracted_tickers
        ) if t
    ]
    extracted_tickers = list(dict.fromkeys(extracted_tickers))
    impact = aggregate_heads(heads)

    top = top_dimensions(impact, n=3)
    top_str = "  ".join(f"{d} {s:+.2f}" for d, s in top) if top else "no signals"
    console.print(
        f"  id={article_id}  signals: {top_str}  "
        f"tickers: {', '.join(extracted_tickers[:5]) or '—'}"
    )

    if dry_run:
        return True

    clean_hash = _sha256(body)

    # Write cleaned body + updated hash back to news_articles
    client.schema(get_schema()).table("news_articles").update({
        "body": body,
        "article_hash": clean_hash,
    }).eq("id", article_id).execute()

    _delete_heads_and_vector(client, article_id)
    _persist(
        client,
        body,
        clean_hash,
        row.get("url"),
        title,
        row.get("url"),
        heads,
        impact,
        existing_article_id=article_id,
        published_at=row.get("published_at"),
        publisher=row.get("publisher"),
        article_stream=row.get("article_stream"),
    )

    if extracted_tickers:
        save_article_tickers(client, article_id, extracted_tickers, source="extracted")

    return True


# ── Main ─────────────────────────────────────────────────────────────────────

async def main(args: argparse.Namespace) -> None:
    os.environ["OLLAMA_IMPACT_MODEL"] = args.model

    client = get_supabase_client()
    ids = fetch_unscored_ids(client)
    total = len(ids)

    if total == 0:
        console.print("[green]No unscored articles found — nothing to do.[/green]")
        return

    console.print(
        f"[bold]Rescoring {total} articles "
        f"(concurrency={args.concurrency}, model={args.model})[/bold]"
    )
    if args.dry_run:
        console.print("[yellow]DRY RUN — no DB writes[/yellow]")
        db_client = None
    else:
        db_client = client

    try:
        ticker_alias_map, company_alias_map = _load_identity_alias_maps()
    except Exception as exc:
        logger.warning("Failed to load identity alias maps: %s", exc)
        ticker_alias_map, company_alias_map = {}, {}

    semaphore = asyncio.Semaphore(args.concurrency)
    done = 0
    failed = 0

    for batch_start in range(0, total, args.batch_size):
        batch_ids = ids[batch_start:batch_start + args.batch_size]
        rows = fetch_articles_batch(client, batch_ids)
        row_map = {r["id"]: r for r in rows}

        tasks = []
        for i, article_id in enumerate(batch_ids):
            row = row_map.get(article_id)
            if row is None:
                console.print(f"  id={article_id} — not found in DB, skipping")
                continue
            tasks.append(rescore_article(
                db_client,
                row,
                ticker_alias_map,
                company_alias_map,
                semaphore,
                index=batch_start + i + 1,
                total=total,
                dry_run=args.dry_run,
            ))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                console.print(f"[red]Unhandled error: {r}[/red]")
                failed += 1
            elif r:
                done += 1
            else:
                failed += 1

        console.print(
            f"[dim]Batch done ({min(batch_start + args.batch_size, total)}/{total}). "
            f"Progress: {done} rescored, {failed} failed[/dim]\n"
        )

    console.print(
        f"\n[bold green]Done.[/bold green] "
        f"{done} rescored, {failed} failed out of {total} unscored articles."
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rescore articles with no impact heads."
    )
    parser.add_argument(
        "--batch-size", type=int, default=50,
        help="Articles fetched per DB query (default: 50)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=5,
        help="Max articles scored in parallel (default: 5)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Score without writing to DB",
    )
    parser.add_argument(
        "--model", default="gemma4:31b-cloud",
        help="Ollama model to use (default: gemma4:31b-cloud)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(_parse_args()))
