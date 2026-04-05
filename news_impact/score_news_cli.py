"""
CLI entry point for the news impact scorer.

The primary operation is embedding a news article into an impact vector —
no tickers are needed for that. Passing --tickers is optional and triggers
company scoring on top.

Usage:
    # Embed only — no tickers needed
    python -m news_impact.score_news_cli --text "Fed raises rates 50bps..."
    python -m news_impact.score_news_cli --url "https://..."
    python -m news_impact.score_news_cli --file article.txt

    # Fetch and embed latest news from FMP (market-wide)
    python -m news_impact.score_news_cli --fmp-news
    python -m news_impact.score_news_cli --fmp-news --limit 10

    # Fetch FMP news filtered to specific tickers
    python -m news_impact.score_news_cli --fmp-news --tickers AAPL MSFT NVDA

    # Embed + score companies
    python -m news_impact.score_news_cli --text "..." --tickers AAPL MSFT NVDA JPM XOM
    python -m news_impact.score_news_cli --url "..." --tickers AAPL MSFT --use-cache
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pathlib
import re
import sys
from typing import Optional

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

import httpx
from rich.console import Console

from news_impact.company_scorer import score_companies, CompanyScore
from news_impact.company_vector import build_vectors, CompanyVector
from news_impact.fmp_fetcher import FMPFetcher
from news_impact.impact_scorer import score_article, aggregate_heads, top_dimensions, HeadOutput, extract_tickers
from news_impact.news_ingester import _sha256, _check_existing
from src.db import get_supabase_client, get_schema, ensure_schema, save_article_tickers


def _heads_from_db(article_id: int) -> list[HeadOutput]:
    """Reconstruct HeadOutput list from stored news_impact_heads rows."""
    client = get_supabase_client()
    res = (
        client.schema(get_schema()).table("news_impact_heads")
        .select("cluster,scores_json,reasoning_json,confidence,model,latency_ms")
        .eq("article_id", article_id)
        .execute()
    )
    heads = []
    for row in (res.data or []):
        try:
            scores    = json.loads(row.get("scores_json")    or "{}")
            reasoning = json.loads(row.get("reasoning_json") or "{}")
        except json.JSONDecodeError:
            scores = reasoning = {}
        heads.append(HeadOutput(
            cluster=row["cluster"],
            scores=scores,
            reasoning=reasoning,
            confidence=float(row.get("confidence") or 0),
            model=row.get("model") or "",
            latency_ms=int(row.get("latency_ms") or 0),
            raw_response="",
        ))
    return heads

logger  = logging.getLogger(__name__)
console = Console()

_CACHE_DIR = pathlib.Path(__file__).parent / "cache"

# ── HTML stripping (stdlib only) ─────────────────────────────────────────────

_TAG_RE   = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s{2,}")


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


# ── Article source loaders ───────────────────────────────────────────────────

async def _load_from_url(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 news-impact-bot/1.0"})
        r.raise_for_status()
    content_type = r.headers.get("content-type", "")
    if "html" in content_type:
        paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", r.text, re.IGNORECASE | re.DOTALL)
        if paragraphs:
            return _strip_html(" ".join(paragraphs))
        return _strip_html(r.text)
    return r.text


def _load_from_file(path: str) -> str:
    p = pathlib.Path(path)
    if not p.exists():
        console.print(f"[red]Error: file not found: {path}[/red]")
        sys.exit(1)
    return p.read_text(encoding="utf-8").strip()


# ── Company vector loading ────────────────────────────────────────────────────

def _load_cached_vectors(tickers: list[str]) -> list[CompanyVector]:
    """Load the most recent cached vector per ticker from news_impact/cache/."""
    vectors: list[CompanyVector] = []
    for ticker in tickers:
        candidates = sorted(_CACHE_DIR.glob(f"{ticker}_*.json"), reverse=True)
        if not candidates:
            console.print(f"[yellow]Warning: no cached vector for {ticker} — skipping[/yellow]")
            continue
        try:
            data = json.loads(candidates[0].read_text())
            vectors.append(CompanyVector.from_json(data))
        except Exception as exc:
            console.print(f"[yellow]Warning: failed to load cache for {ticker}: {exc}[/yellow]")
    return vectors


# ── Rich display ──────────────────────────────────────────────────────────────

def _bar(value: float, width: int = 10) -> str:
    filled = round(max(0.0, min(1.0, value)) * width)
    return "█" * filled + "░" * (width - filled)


def _print_results(
    article_text: str,
    article_id: int,
    heads: list[HeadOutput],
    impact: dict[str, float],
    company_scores: list[CompanyScore],
    title: Optional[str],
    extracted_tickers: Optional[list[str]] = None,
) -> None:
    sep = "━" * 52
    console.print(f"\n[bold]{sep}[/bold]")

    display_title = title or (article_text[:80].replace("\n", " ") + ("…" if len(article_text) > 80 else ""))
    console.print(f"[bold cyan]Article:[/bold cyan] {display_title}")
    if article_id >= 0:
        console.print(f"[dim]article_id={article_id}[/dim]")
    if extracted_tickers:
        console.print(f"[dim]Companies mentioned: {', '.join(extracted_tickers)}[/dim]")

    # Cluster confidence bars
    console.print(f"\n[bold]Cluster confidence:[/bold]")
    for h in sorted(heads, key=lambda h: h.confidence, reverse=True):
        bar   = _bar(h.confidence)
        label = h.cluster[:20]
        err   = f"  [red](err)[/red]" if h.error else ""
        console.print(f"  [cyan]{label:<22}[/cyan] [green]{bar}[/green]  {h.confidence:.2f}{err}")

    # Top signals from the impact vector
    top = top_dimensions(impact, n=5)
    if top:
        console.print(f"\n[bold]Top signals:[/bold]")
        for dim, score in top:
            colour = "green" if score > 0 else "red"
            sign   = "+" if score > 0 else ""
            console.print(f"  [{colour}]{dim:<36}  {sign}{score:.2f}[/{colour}]")
    else:
        console.print("\n[dim]No signals — article may not relate to any cluster.[/dim]")

    # Company scores (only printed when tickers were passed)
    if company_scores:
        tailwinds = [s for s in company_scores if s.score > 0]
        headwinds = list(reversed([s for s in company_scores if s.score < 0]))

        console.print(f"\n[bold green]TAILWINDS[/bold green]{'':12}[bold red]HEADWINDS[/bold red]")
        for i in range(max(len(tailwinds), len(headwinds))):
            tw_str = hw_str = ""
            if i < len(tailwinds):
                cs = tailwinds[i]
                tw_str = f"{cs.ticker:<6} [green]+{cs.score:.2f}[/green]"
            if i < len(headwinds):
                cs = headwinds[i]
                hw_str = f"{cs.ticker:<6} [red]{cs.score:.2f}[/red]"
            console.print(f"  {tw_str:<28}{hw_str}")

    console.print(f"[bold]{sep}[/bold]\n")


# ── Argument parsing ──────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m news_impact.score_news_cli",
        description=(
            "Embed a news article into an impact vector. "
            "Pass --tickers to also score companies against the vector."
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url",      metavar="URL",  help="Fetch article from URL")
    source.add_argument("--text",     metavar="TEXT", help="Article text inline")
    source.add_argument("--file",     metavar="PATH", help="Read article from file")
    source.add_argument("--fmp-news", action="store_true",
                        help="Fetch latest stock news from FMP (filterable by --tickers)")

    parser.add_argument(
        "--limit", type=int, default=20,
        help="Max articles to fetch with --fmp-news (default: 20)",
    )
    parser.add_argument(
        "--page", type=int, default=0,
        help="Page offset for --fmp-news pagination (default: 0)",
    )

    parser.add_argument(
        "--tickers", nargs="+", metavar="TICKER", default=None,
        help="Optional: score these tickers against the impact vector",
    )
    parser.add_argument(
        "--use-cache", action="store_true",
        help="Load company vectors from disk cache (requires prior build_vectors_cli run)",
    )
    parser.add_argument("--title",  metavar="TITLE",  default=None, help="Article title")
    parser.add_argument("--source", metavar="SOURCE", default=None, help="Source label")
    parser.add_argument(
        "--top-n", type=int, default=6,
        help="Max companies per side in tailwinds/headwinds (default: 6)",
    )
    parser.add_argument(
        "--no-persist", action="store_true",
        help="Score without writing to DuckDB",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-score even if article is already in DB, overwriting stored heads and vector",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    return parser.parse_args(argv)


# ── Main ─────────────────────────────────────────────────────────────────────

async def _main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    # FMP news batch mode — separate flow
    if args.fmp_news:
        await _process_fmp_news(args)
        return

    # 1. Load article text
    if args.url:
        console.print(f"[dim]Fetching {args.url}…[/dim]")
        try:
            article_text = await _load_from_url(args.url)
        except Exception as exc:
            console.print(f"[red]Failed to fetch URL: {exc}[/red]")
            sys.exit(1)
    elif args.text:
        article_text = args.text
    else:
        article_text = _load_from_file(args.file)

    if not article_text.strip():
        console.print("[red]Error: article text is empty[/red]")
        sys.exit(1)

    # 2. Score article + extract tickers in parallel
    article_id: int = -1
    impact: dict[str, float] = {}
    heads: list[HeadOutput]  = []
    extracted_tickers: list[str] = []

    if args.no_persist:
        console.print("[dim]Scoring article (no DB persist)…[/dim]")
        heads, extracted_tickers = await asyncio.gather(
            score_article(article_text),
            extract_tickers(article_text),
        )
        impact = aggregate_heads(heads)
    else:
        # Check for existing article before showing status message
        article_hash = _sha256(article_text)
        client = get_supabase_client()
        ensure_schema()
        existing = _check_existing(client, article_hash)

        if existing is not None and not args.refresh:
            article_id, impact = existing
            console.print(f"[dim]Article already in DB (id={article_id}) — using cached impact vector.[/dim]")
            # Extract tickers only (no LLM scoring needed)
            extracted_tickers = await extract_tickers(article_text)
            # Reconstruct heads from DB for display
            heads = _heads_from_db(article_id)
        else:
            action = "Re-scoring" if (existing and args.refresh) else "Scoring"
            console.print(f"[dim]{action} article…[/dim]")
            heads, extracted_tickers = await asyncio.gather(
                score_article(article_text),
                extract_tickers(article_text),
            )
            impact = aggregate_heads(heads)
            from news_impact.news_ingester import ingest_article as _ingest
            article_id, impact = await _ingest(
                body=article_text,
                url=args.url,
                title=args.title,
                source=args.source,
                refresh=args.refresh,
            )

    # 2b. Persist detected tickers to DB
    if not args.no_persist and article_id >= 0 and (extracted_tickers or args.tickers):
        explicit_tickers_upper = [t.upper() for t in (args.tickers or [])]
        try:
            client = get_supabase_client()
            ensure_schema()
            if extracted_tickers:
                save_article_tickers(client, article_id, extracted_tickers, source="extracted")
            if explicit_tickers_upper:
                save_article_tickers(client, article_id, explicit_tickers_upper, source="explicit")
        except Exception as exc:
            logger.warning("[score_news] failed to persist tickers: %s", exc)

    # 3. Merge explicit --tickers with extracted ones, then score companies
    explicit_tickers = [t.upper() for t in (args.tickers or [])]
    all_tickers = list(dict.fromkeys(explicit_tickers + extracted_tickers))  # dedupe, preserve order

    if extracted_tickers:
        auto_label = ", ".join(extracted_tickers)
        console.print(f"[dim]Extracted from article: {auto_label}[/dim]")

    company_scores: list[CompanyScore] = []
    if all_tickers:
        if args.use_cache:
            console.print("[dim]Loading company vectors from cache…[/dim]")
            company_vectors = _load_cached_vectors(all_tickers)
            if not company_vectors:
                console.print("[yellow]No cached vectors found — skipping company scoring.[/yellow]")
        else:
            console.print("[dim]Fetching company vectors from FMP…[/dim]")
            company_vectors = await build_vectors(all_tickers, use_cache=True)
        if company_vectors:
            company_scores = score_companies(impact, company_vectors, top_n=args.top_n)

    # 4. Display
    _print_results(article_text, article_id, heads, impact, company_scores, args.title, extracted_tickers)


async def _process_fmp_news(args: argparse.Namespace) -> None:
    """Fetch articles from FMP and run each through the full pipeline."""
    fetcher   = FMPFetcher()
    tickers   = [t.upper() for t in args.tickers] if args.tickers else None
    articles  = await fetcher.fetch_stock_news(tickers=tickers, limit=args.limit, page=args.page)

    if not articles:
        console.print("[red]No articles returned from FMP.[/red]")
        return

    console.print(f"\nFetched [bold]{len(articles)}[/bold] articles from FMP news\n")

    for i, article in enumerate(articles, 1):
        summary = article.get("text", "").strip()
        title   = article.get("title", "")
        url     = article.get("url", "")
        source  = article.get("site") or article.get("publisher") or "fmp"
        symbol  = article.get("symbol", "")

        if not summary and not url:
            console.print(f"[dim][{i}/{len(articles)}] {title[:60]} — skipped (no text or url)[/dim]")
            continue

        console.print(f"[bold cyan][{i}/{len(articles)}][/bold cyan] {title[:70]}")

        # Fetch full article from URL; fall back to FMP summary on failure
        body = summary
        if url:
            try:
                full = await _load_from_url(url)
                if full and len(full) > len(summary):
                    body = full
                    console.print(f"  [dim]fetched full article ({len(body)} chars)[/dim]")
                else:
                    console.print(f"  [dim]url returned no usable content — using summary[/dim]")
            except Exception as exc:
                console.print(f"  [dim]url fetch failed ({exc.__class__.__name__}) — using summary[/dim]")

        if not body:
            console.print(f"  [dim]skipped (no content)[/dim]")
            continue

        # Score + extract in parallel
        heads, extracted_tickers = await asyncio.gather(
            score_article(body),
            extract_tickers(body),
        )
        impact = aggregate_heads(heads)

        # Always include the article's own symbol if present
        if symbol and symbol not in extracted_tickers:
            extracted_tickers = [symbol] + extracted_tickers

        # Persist
        article_id = -1
        if not args.no_persist:
            article_hash = _sha256(body)
            client = get_supabase_client()
            ensure_schema()
            existing = _check_existing(client, article_hash)

            if existing is not None and not args.refresh:
                article_id = existing[0]
                console.print(f"  [dim]already in DB (id={article_id})[/dim]")
            else:
                from news_impact.news_ingester import _delete_heads_and_vector, _persist
                if existing and args.refresh:
                    _delete_heads_and_vector(client, existing[0])
                    article_id = _persist(client, body, article_hash, url, title, source, heads, impact,
                                          existing_article_id=existing[0])
                else:
                    article_id = _persist(client, body, article_hash, url, title, source, heads, impact)

            if article_id >= 0 and extracted_tickers:
                save_article_tickers(client, article_id, extracted_tickers, source="extracted")
                explicit = [t.upper() for t in (args.tickers or [])]
                if explicit:
                    save_article_tickers(client, article_id, explicit, source="explicit")

        # Compact summary line
        top = top_dimensions(impact, n=3)
        top_str = "  ".join(f"{d} {s:+.2f}" for d, s in top) if top else "no signals"
        mentioned = ", ".join(extracted_tickers[:5]) if extracted_tickers else "—"
        console.print(f"  [dim]id={article_id}  mentioned={mentioned}[/dim]")
        console.print(f"  [dim]top signals: {top_str}[/dim]")

        # Optional company scoring
        all_tickers = list(dict.fromkeys(extracted_tickers + [t.upper() for t in (args.tickers or [])]))
        if all_tickers and impact:
            try:
                company_vectors = await build_vectors(all_tickers, use_cache=True)
                if company_vectors:
                    scores = score_companies(impact, company_vectors, top_n=4)
                    tw = [s for s in scores if s.score > 0]
                    hw = list(reversed([s for s in scores if s.score < 0]))
                    if tw or hw:
                        tw_str = "  ".join(f"[green]{s.ticker} +{s.score:.2f}[/green]" for s in tw[:2])
                        hw_str = "  ".join(f"[red]{s.ticker} {s.score:.2f}[/red]" for s in hw[:2])
                        console.print(f"  tailwinds: {tw_str or '—'}   headwinds: {hw_str or '—'}")
            except Exception as exc:
                logger.warning("company scoring failed for article %d: %s", article_id, exc)

        console.print()


def main(argv: list[str] | None = None) -> None:
    asyncio.run(_main(argv))


if __name__ == "__main__":
    main()
