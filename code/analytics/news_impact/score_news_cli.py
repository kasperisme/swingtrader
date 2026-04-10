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

    # Use Anthropic or DigitalOcean GenAI Agent instead of Ollama (overrides NEWS_IMPACT_BACKEND)
    python -m news_impact.score_news_cli --text "..." --news-impact-backend anthropic
    python -m news_impact.score_news_cli --text "..." --news-impact-backend do_agent

    # Fetch and embed latest news from FMP (market-wide)
    python -m news_impact.score_news_cli --fmp-news
    python -m news_impact.score_news_cli --fmp-news --limit 10
    python -m news_impact.score_news_cli --fmp-news --from 2025-09-09 --to 2025-12-10
    python -m news_impact.score_news_cli --fmp-news --sparse-fill 30 10
    python -m news_impact.score_news_cli --fmp-news --sparse-fill 30 10 --sparse-fill-loop

    # Fetch FMP news filtered to specific tickers
    python -m news_impact.score_news_cli --fmp-news --tickers AAPL MSFT NVDA
    python -m news_impact.score_news_cli --fmp-news --tickers AAPL --from 2025-11-01 --to 2025-11-30

    # Fetch recent X (Twitter) posts mentioning stock cashtags
    python -m news_impact.score_news_cli --x-news --tickers AAPL MSFT NVDA
    python -m news_impact.score_news_cli --x-news --tickers TSLA --x-limit 50

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
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parent.parent / ".env")

import httpx
from rich.console import Console

from news_impact.company_scorer import score_companies, CompanyScore
from news_impact.company_vector import build_vectors, CompanyVector
from news_impact.fmp_fetcher import FMPFetcher
from news_impact.x_fetcher import XFetcher
from news_impact.impact_scorer import (
    score_article,
    aggregate_heads,
    top_dimensions,
    HeadOutput,
    extract_tickers,
    set_news_impact_backend,
)
from news_impact.news_ingester import (
    _check_existing,
    _delete_heads_and_vector,
    ingest_article,
    _normalize_url,
    _persist,
    _sha256,
)
from src.db import (
    _as_json,
    count_news_articles_per_calendar_day_eastern,
    get_schema,
    get_supabase_client,
    load_article_tickers,
    patch_news_article_image_if_missing,
    save_article_tickers,
)


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
        scores    = _as_json(row.get("scores_json"),    default={})
        reasoning = _as_json(row.get("reasoning_json"), default={})
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


def _fetch_published_at(article_id: int) -> Optional[str]:
    """Return published_at from news_articles for display, if present."""
    if article_id < 0:
        return None
    try:
        client = get_supabase_client()
        res = (
            client.schema(get_schema())
            .table("news_articles")
            .select("published_at")
            .eq("id", article_id)
            .limit(1)
            .execute()
        )
        if res.data:
            val = res.data[0].get("published_at")
            if val is not None and str(val).strip():
                return str(val).strip()
    except Exception as exc:
        logger.debug("[score_news] published_at fetch failed: %s", exc)
    return None

logger  = logging.getLogger(__name__)
console = Console()

_CACHE_DIR = pathlib.Path(__file__).parent / "cache"

# FMP stock news API limits (see fmp_fetcher.fetch_stock_news)
_FMP_NEWS_MAX_PAGE = 100
_FMP_NEWS_MAX_LIMIT = 250

# ── HTML stripping (stdlib only) ─────────────────────────────────────────────

_TAG_RE   = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s{2,}")


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


def _normalize_fmp_published_at(raw_value: Optional[str]) -> Optional[str]:
    """
    Normalize FMP publishedDate to UTC ISO-8601.

    FMP news endpoint timestamps are treated as America/New_York when no
    explicit timezone is present.
    """
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None

    # If timezone-aware already (Z or +/-hh:mm), parse directly.
    try:
        aware = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if aware.tzinfo is not None:
            return aware.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        pass

    # Naive timestamp from FMP: interpret as US Eastern time.
    naive_candidates = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    )
    naive_dt: Optional[datetime] = None
    for fmt in naive_candidates:
        try:
            naive_dt = datetime.strptime(text, fmt)
            break
        except ValueError:
            continue
    if naive_dt is None:
        return text

    eastern = naive_dt.replace(tzinfo=ZoneInfo("America/New_York"))
    return eastern.astimezone(timezone.utc).isoformat(timespec="seconds")


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
    published_at: Optional[str] = None,
) -> None:
    sep = "━" * 52
    console.print(f"\n[bold]{sep}[/bold]")

    display_title = title or (article_text[:80].replace("\n", " ") + ("…" if len(article_text) > 80 else ""))
    console.print(f"[bold cyan]Article:[/bold cyan] {display_title}")
    if article_id >= 0:
        console.print(f"[dim]article_id={article_id}[/dim]")
    if published_at:
        console.print(f"[dim]published: {published_at}[/dim]")
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

    # Per-ticker sentiment
    sent_head = next((h for h in heads if h.cluster == "TICKER_SENTIMENT"), None)
    if sent_head and sent_head.scores:
        console.print(f"\n[bold]Ticker sentiment:[/bold]")
        for ticker, score in sorted(sent_head.scores.items(), key=lambda x: x[1], reverse=True):
            colour = "green" if score > 0 else ("red" if score < 0 else "dim")
            sign   = "+" if score > 0 else ""
            reason = sent_head.reasoning.get(ticker, "")
            console.print(f"  [{colour}]{ticker:<6}  {sign}{score:.2f}[/{colour}]  [dim]{reason}[/dim]")

    # Ticker relationships
    rel_head = next((h for h in heads if h.cluster == "TICKER_RELATIONSHIPS"), None)
    if rel_head and rel_head.scores:
        console.print(f"\n[bold]Ticker relationships:[/bold]")
        for key, strength in sorted(rel_head.scores.items(), key=lambda x: x[1], reverse=True):
            parts = key.split("__")
            if len(parts) == 3:
                frm, to, rel_type = parts
                note = rel_head.reasoning.get(key, "")
                console.print(f"  [cyan]{frm}[/cyan] → [cyan]{to}[/cyan]  [{rel_type}]  strength={strength:.2f}")
                if note:
                    console.print(f"    [dim]{note}[/dim]")

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
    source.add_argument("--x-news", action="store_true",
                        help="Fetch recent X posts mentioning stock cashtags (requires --tickers)")

    parser.add_argument(
        "--limit", type=int, default=20,
        help="Max articles to fetch with --fmp-news (default: 20, max: 250)",
    )
    parser.add_argument(
        "--page", type=int, default=0,
        help="Page offset for --fmp-news pagination (default: 0, max: 100)",
    )
    parser.add_argument(
        "--x-limit", type=int, default=50,
        help="Max X posts to fetch with --x-news (default: 50, max: 100)",
    )
    parser.add_argument(
        "--from", dest="from_date", metavar="DATE",
        help="Start date filter for --fmp-news (YYYY-MM-DD, e.g. 2025-09-09)",
    )
    parser.add_argument(
        "--to", dest="to_date", metavar="DATE",
        help="End date filter for --fmp-news (YYYY-MM-DD, e.g. 2025-12-10)",
    )
    parser.add_argument(
        "--sparse-fill",
        nargs=2,
        type=int,
        metavar=("N_DAYS", "M_NEW"),
        default=None,
        help=(
            "With --fmp-news: find the US Eastern calendar day in the last N_DAYS with the fewest "
            "rows in news_articles (by published_at/created_at), then fetch FMP for that day "
            "until M_NEW new articles are inserted (or pages exhausted). Overrides --from, "
            "--to, and --page. Requires DB (no --no-persist)."
        ),
    )
    parser.add_argument(
        "--sparse-fill-loop",
        action="store_true",
        help=(
            "With --sparse-fill: after each day finishes (M_NEW inserts or FMP exhausted), "
            "re-query counts and take the next sparsest ET day in the window, excluding days "
            "already processed this run, until every day in the window has had one pass."
        ),
    )

    parser.add_argument(
        "--tickers", nargs="+", metavar="TICKER", default=None,
        help="Optional: include explicit symbols (logged/persisted); scoring requires --score-companies",
    )
    parser.add_argument(
        "--score-companies", action="store_true",
        help="Build/load company vectors and score tailwinds/headwinds (off by default)",
    )
    parser.add_argument(
        "--use-cache", action="store_true",
        help="Load company vectors from disk cache (requires prior build_vectors_cli run)",
    )
    parser.add_argument("--title",  metavar="TITLE",  default=None, help="Article title")
    parser.add_argument(
        "--published-at",
        metavar="ISO",
        default=None,
        help="Publication time for this article (stored and printed; e.g. 2026-04-08T14:30:00)",
    )
    parser.add_argument("--source", metavar="SOURCE", default=None, help="Source label")
    parser.add_argument(
        "--top-n", type=int, default=6,
        help="Max companies per side in tailwinds/headwinds (default: 6)",
    )
    parser.add_argument(
        "--no-persist", action="store_true",
        help="Score without writing to Supabase",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Re-score even if article is already in DB, overwriting stored heads and vector",
    )
    parser.add_argument(
        "--news-impact-backend",
        dest="news_impact_backend",
        choices=["ollama", "anthropic", "do_agent"],
        default=None,
        metavar="BACKEND",
        help="Override NEWS_IMPACT_BACKEND (ollama, anthropic, do_agent; default: env or ollama)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    return parser.parse_args(argv)


# ── Main ─────────────────────────────────────────────────────────────────────

async def _main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if args.news_impact_backend is not None:
        set_news_impact_backend(args.news_impact_backend)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    if args.sparse_fill is not None:
        if not args.fmp_news:
            console.print("[red]--sparse-fill requires --fmp-news[/red]")
            sys.exit(1)
        if args.no_persist:
            console.print("[red]--sparse-fill requires persistence (omit --no-persist)[/red]")
            sys.exit(1)
        n_days, m_new = args.sparse_fill
        if n_days < 1 or m_new < 1:
            console.print("[red]--sparse-fill requires N_DAYS >= 1 and M_NEW >= 1[/red]")
            sys.exit(1)
    if args.sparse_fill_loop and args.sparse_fill is None:
        console.print("[red]--sparse-fill-loop requires --sparse-fill N_DAYS M_NEW[/red]")
        sys.exit(1)

    # FMP news batch mode — separate flow
    if args.fmp_news:
        if args.sparse_fill is not None:
            await _process_fmp_sparse_fill(args)
        else:
            await _process_fmp_news(args)
        return

    # X (Twitter) posts batch mode — separate flow
    if args.x_news:
        if not args.tickers:
            console.print("[red]--x-news requires --tickers TICKER [TICKER …][/red]")
            sys.exit(1)
        await _process_x_news(args)
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
        existing = _check_existing(client, article_hash, url=args.url)

        if existing is not None and not args.refresh:
            article_id, impact = existing
            console.print(f"[dim]Article already in DB (id={article_id}) — using cached impact vector.[/dim]")
            # Load previously extracted tickers from DB (avoid extra LLM call)
            extracted_tickers = load_article_tickers(client, article_id, source="extracted")
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
            article_id, impact = await ingest_article(
                body=article_text,
                url=args.url,
                title=args.title,
                source=args.source,
                refresh=args.refresh,
                published_at=args.published_at,
            )

    # 2b. Persist detected tickers to DB
    if not args.no_persist and article_id >= 0 and (extracted_tickers or args.tickers):
        explicit_tickers_upper = [t.upper() for t in (args.tickers or [])]
        try:
            client = get_supabase_client()
            if extracted_tickers:
                save_article_tickers(client, article_id, extracted_tickers, source="extracted")
            if explicit_tickers_upper:
                save_article_tickers(client, article_id, explicit_tickers_upper, source="explicit")
        except Exception as exc:
            logger.warning("[score_news] failed to persist tickers: %s", exc)

    # 3. Merge explicit --tickers with extracted ones
    explicit_tickers = [t.upper() for t in (args.tickers or [])]
    all_tickers = list(dict.fromkeys(explicit_tickers + extracted_tickers))  # dedupe, preserve order

    if extracted_tickers:
        auto_label = ", ".join(extracted_tickers)
        console.print(f"[dim]Extracted from article: {auto_label}[/dim]")
    if all_tickers:
        console.print(f"[dim]Symbols: {', '.join(all_tickers)}[/dim]")

    company_scores: list[CompanyScore] = []
    if all_tickers and args.score_companies:
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
    elif all_tickers:
        console.print("[dim]Skipping company vector build/scoring (use --score-companies to enable).[/dim]")

    # 4. Display
    published_display = args.published_at
    if not published_display and article_id >= 0 and not args.no_persist:
        published_display = _fetch_published_at(article_id)
    _print_results(
        article_text,
        article_id,
        heads,
        impact,
        company_scores,
        args.title,
        extracted_tickers,
        published_at=published_display,
    )


def _pick_sparsest_calendar_day(counts: dict[date, int]) -> date:
    """Among days with the minimum article count, return the earliest US Eastern calendar day."""
    min_c = min(counts.values())
    candidates = [d for d, c in counts.items() if c == min_c]
    return min(candidates)


def _pick_sparsest_calendar_day_excluding(
    counts: dict[date, int],
    excluded: set[date],
) -> date | None:
    """Like `_pick_sparsest_calendar_day` but ignoring days in ``excluded``. None if none left."""
    candidates = {d: c for d, c in counts.items() if d not in excluded}
    if not candidates:
        return None
    min_c = min(candidates.values())
    tie = [d for d, c in candidates.items() if c == min_c]
    return min(tie)


async def _process_one_fmp_article(
    args: argparse.Namespace,
    article: dict,
    seen_urls: set[str],
    seen_hashes: set[str],
    *,
    index: int,
    batch_total: int,
) -> bool:
    """
    Run one FMP article through the scoring pipeline.

    Returns True if a new row was inserted into ``news_articles`` (not a cache hit / update).
    """
    summary = article.get("text", "").strip()
    title = article.get("title", "")
    url = article.get("url", "")
    source = url
    publisher = article.get("publisher") or article.get("site") or None
    symbol = article.get("symbol", "")
    published_at = _normalize_fmp_published_at(article.get("publishedDate") or None)
    image_url = (article.get("image") or "").strip() or None

    if not summary and not url:
        console.print(f"[dim][{index}/{batch_total}] {title[:60]} — skipped (no text or url)[/dim]")
        return False

    console.print(f"[bold cyan][{index}/{batch_total}][/bold cyan] {title[:70]}")
    if published_at:
        console.print(f"  [dim]published: {published_at}[/dim]")

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
        return False

    article_hash = _sha256(body)
    url_norm = _normalize_url(url) if url else ""

    if url_norm and url_norm in seen_urls:
        console.print(
            "  [dim]skipped — same URL already processed in this run[/dim]",
        )
        return False

    # Same body can appear under multiple URLs in one FMP batch; always dedupe by hash
    # in-memory (not only when url is missing) to avoid unique violations on article_hash.
    if article_hash in seen_hashes:
        console.print(
            "  [dim]skipped — same article body already processed in this run[/dim]",
        )
        return False

    client = None if args.no_persist else get_supabase_client()
    existing = None if client is None else _check_existing(client, article_hash, url=url)
    from_cache = existing is not None and not args.refresh

    article_id = -1
    heads: list[HeadOutput]
    extracted_tickers: list[str]
    impact: dict[str, float]

    if from_cache:
        assert existing is not None
        article_id, impact = existing
        patch_news_article_image_if_missing(client, article_id, image_url)
        heads = _heads_from_db(article_id)
        extracted_tickers = load_article_tickers(client, article_id, source="extracted")
        console.print(
            f"  [dim]already in DB (id={article_id}) — skipped LLM scoring[/dim]",
        )
    else:
        heads, extracted_tickers = await asyncio.gather(
            score_article(body),
            extract_tickers(body),
        )
        impact = aggregate_heads(heads)

    if symbol and symbol not in extracted_tickers:
        extracted_tickers = [symbol] + extracted_tickers

    if client is not None and not from_cache:
        if existing is not None and args.refresh:
            _delete_heads_and_vector(client, existing[0])
            article_id = _persist(
                client,
                body,
                article_hash,
                url,
                title,
                source,
                heads,
                impact,
                existing_article_id=existing[0],
                published_at=published_at,
                publisher=publisher,
                image_url=image_url,
            )
        else:
            article_id = _persist(
                client,
                body,
                article_hash,
                url,
                title,
                source,
                heads,
                impact,
                published_at=published_at,
                publisher=publisher,
                image_url=image_url,
            )

    if client is not None and article_id >= 0 and extracted_tickers:
        save_article_tickers(client, article_id, extracted_tickers, source="extracted")
        explicit = [t.upper() for t in (args.tickers or [])]
        if explicit:
            save_article_tickers(client, article_id, explicit, source="explicit")

    if url_norm:
        seen_urls.add(url_norm)
    seen_hashes.add(article_hash)

    top = top_dimensions(impact, n=3)
    top_str = "  ".join(f"{d} {s:+.2f}" for d, s in top) if top else "no signals"
    mentioned = ", ".join(extracted_tickers[:5]) if extracted_tickers else "—"
    pub = published_at or "—"
    console.print(f"  [dim]id={article_id}  published={pub}  mentioned={mentioned}[/dim]")
    console.print(f"  [dim]top signals: {top_str}[/dim]")

    all_tickers = list(dict.fromkeys(extracted_tickers + [t.upper() for t in (args.tickers or [])]))
    if all_tickers:
        console.print(f"  [dim]symbols: {', '.join(all_tickers)}[/dim]")
    if all_tickers and impact and args.score_companies:
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
    elif all_tickers:
        console.print("  [dim]skipping company vector build/scoring (use --score-companies to enable)[/dim]")

    console.print()

    inserted_new = bool(client and not from_cache and existing is None)
    return inserted_new


async def _process_one_x_post(
    args: argparse.Namespace,
    post: dict,
    seen_ids: set[str],
    seen_hashes: set[str],
    *,
    index: int,
    batch_total: int,
) -> bool:
    """
    Run one X post through the scoring pipeline.

    Returns True if a new row was inserted into ``news_articles``.
    """
    text = post.get("text", "").strip()
    title = post.get("title", text[:80])
    url = post.get("url", "")
    published_at = post.get("published_at")
    publisher = post.get("publisher") or "x.com"
    symbol = post.get("symbol", "")
    post_id = post.get("post_id", "")
    metrics = post.get("public_metrics", {})

    if not text:
        console.print(f"[dim][{index}/{batch_total}] skipped (empty text)[/dim]")
        return False

    if post_id and post_id in seen_ids:
        console.print(f"[dim][{index}/{batch_total}] skipped (duplicate post_id)[/dim]")
        return False

    console.print(f"[bold cyan][{index}/{batch_total}][/bold cyan] {title[:70]}")
    if published_at:
        console.print(f"  [dim]published: {published_at}[/dim]")
    if metrics:
        likes = metrics.get("like_count", 0)
        rts   = metrics.get("retweet_count", 0)
        console.print(f"  [dim]likes={likes}  retweets={rts}[/dim]")

    article_hash = _sha256(text)
    if article_hash in seen_hashes:
        console.print("  [dim]skipped — duplicate content already processed in this run[/dim]")
        return False

    client = None if args.no_persist else get_supabase_client()
    existing = None if client is None else _check_existing(client, article_hash, url=url)
    from_cache = existing is not None and not args.refresh

    article_id = -1
    heads: list[HeadOutput]
    extracted_tickers: list[str]
    impact: dict[str, float]

    if from_cache:
        assert existing is not None
        article_id, impact = existing
        heads = _heads_from_db(article_id)
        extracted_tickers = load_article_tickers(client, article_id, source="extracted")
        console.print(f"  [dim]already in DB (id={article_id}) — skipped LLM scoring[/dim]")
    else:
        heads, extracted_tickers = await asyncio.gather(
            score_article(text),
            extract_tickers(text),
        )
        impact = aggregate_heads(heads)

    if symbol and symbol not in extracted_tickers:
        extracted_tickers = [symbol] + extracted_tickers

    if client is not None and not from_cache:
        if existing is not None and args.refresh:
            _delete_heads_and_vector(client, existing[0])
            article_id = _persist(
                client, text, article_hash, url, title, "x.com",
                heads, impact, existing_article_id=existing[0],
                published_at=published_at, publisher=publisher,
            )
        else:
            article_id = _persist(
                client, text, article_hash, url, title, "x.com",
                heads, impact,
                published_at=published_at, publisher=publisher,
            )

    if client is not None and article_id >= 0 and extracted_tickers:
        save_article_tickers(client, article_id, extracted_tickers, source="extracted")
        explicit = [t.upper() for t in (args.tickers or [])]
        if explicit:
            save_article_tickers(client, article_id, explicit, source="explicit")

    if post_id:
        seen_ids.add(post_id)
    seen_hashes.add(article_hash)

    top = top_dimensions(impact, n=3)
    top_str = "  ".join(f"{d} {s:+.2f}" for d, s in top) if top else "no signals"
    mentioned = ", ".join(extracted_tickers[:5]) if extracted_tickers else "—"
    pub = published_at or "—"
    console.print(f"  [dim]id={article_id}  published={pub}  mentioned={mentioned}[/dim]")
    console.print(f"  [dim]top signals: {top_str}[/dim]")

    all_tickers = list(dict.fromkeys(extracted_tickers + [t.upper() for t in (args.tickers or [])]))
    if all_tickers and impact and args.score_companies:
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
            logger.warning("company scoring failed for X post %d: %s", article_id, exc)
    elif all_tickers:
        console.print("  [dim]skipping company vector build/scoring (use --score-companies to enable)[/dim]")

    console.print()

    inserted_new = bool(client and not from_cache and existing is None)
    return inserted_new


async def _process_x_news(args: argparse.Namespace) -> None:
    """Fetch recent X posts for the given tickers and run each through the pipeline."""
    tickers = [t.upper() for t in args.tickers]
    x_limit = min(getattr(args, "x_limit", 50), 100)

    console.print(
        f"\nFetching up to [bold]{x_limit}[/bold] X posts "
        f"for [cyan]{', '.join(tickers)}[/cyan]…\n"
    )

    try:
        fetcher = XFetcher()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    posts = fetcher.fetch_stock_posts(tickers=tickers, max_results=x_limit)

    if not posts:
        console.print("[yellow]No X posts returned (check X_BEARER_TOKEN and tickers).[/yellow]")
        return

    console.print(f"Fetched [bold]{len(posts)}[/bold] X posts\n")

    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()

    for i, post in enumerate(posts, 1):
        await _process_one_x_post(
            args, post, seen_ids, seen_hashes, index=i, batch_total=len(posts),
        )


async def _process_fmp_news(args: argparse.Namespace) -> None:
    """Fetch articles from FMP and run each through the full pipeline."""
    fetcher = FMPFetcher()
    tickers = [t.upper() for t in args.tickers] if args.tickers else None
    articles = await fetcher.fetch_stock_news(
        tickers=tickers,
        limit=args.limit,
        page=args.page,
        from_date=getattr(args, "from_date", None),
        to_date=getattr(args, "to_date", None),
    )

    if not articles:
        console.print("[red]No articles returned from FMP.[/red]")
        return

    console.print(f"\nFetched [bold]{len(articles)}[/bold] articles from FMP news\n")

    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()

    for i, article in enumerate(articles, 1):
        await _process_one_fmp_article(
            args, article, seen_urls, seen_hashes, index=i, batch_total=len(articles),
        )


async def _run_sparse_fill_for_day(
    args: argparse.Namespace,
    fetcher: FMPFetcher,
    tickers: list[str] | None,
    target_day: date,
    m_new: int,
    seen_urls: set[str],
    seen_hashes: set[str],
) -> int:
    """Fetch/score FMP news for ``target_day`` until ``m_new`` new rows or FMP exhausted. Returns insert count."""
    day_iso = target_day.isoformat()
    page_limit = min(_FMP_NEWS_MAX_LIMIT, max(1, args.limit))
    added = 0
    page = 0

    while added < m_new and page <= _FMP_NEWS_MAX_PAGE:
        articles = await fetcher.fetch_stock_news(
            tickers=tickers,
            limit=page_limit,
            page=page,
            from_date=day_iso,
            to_date=day_iso,
        )
        if not articles:
            console.print(
                f"[yellow]No articles returned from FMP for {day_iso} at page {page} — stopping.[/yellow]",
            )
            break

        console.print(
            f"\n[dim]Page {page}[/dim]: fetched [bold]{len(articles)}[/bold] articles from FMP "
            f"({added}/{m_new} new so far)\n",
        )

        for i, article in enumerate(articles, 1):
            is_new = await _process_one_fmp_article(
                args, article, seen_urls, seen_hashes, index=i, batch_total=len(articles),
            )
            if is_new:
                added += 1
                if added >= m_new:
                    break

        if added >= m_new:
            break
        if len(articles) < page_limit:
            console.print(
                "[dim]Last page had fewer than limit — no more pagination for this day.[/dim]",
            )
            break
        page += 1

    if added < m_new:
        console.print(
            f"\n[yellow]This day stopped at {added}/{m_new} new articles "
            f"(FMP exhausted or page cap {_FMP_NEWS_MAX_PAGE}).[/yellow]",
        )
    else:
        console.print(f"\n[green]Day complete: {added} new article(s) inserted.[/green]")
    return added


async def _process_fmp_sparse_fill(args: argparse.Namespace) -> None:
    """Pick sparsest UTC day(s) in the last N days, then ingest until M new articles per pass (optional loop)."""
    assert args.sparse_fill is not None
    n_days, m_new = args.sparse_fill
    loop = bool(getattr(args, "sparse_fill_loop", False))

    fetcher = FMPFetcher()
    tickers = [t.upper() for t in args.tickers] if args.tickers else None
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    excluded: set[date] = set()
    round_idx = 0

    while True:
        counts = count_news_articles_per_calendar_day_eastern(n_days)
        if loop:
            target_day = _pick_sparsest_calendar_day_excluding(counts, excluded)
            if target_day is None:
                console.print(
                    "\n[dim]Sparse-fill loop: no remaining days in window (all processed).[/dim]",
                )
                break
        else:
            target_day = _pick_sparsest_calendar_day(counts)

        min_count = counts[target_day]
        round_idx += 1

        if loop:
            console.print(
                f"\n[bold]Sparse fill[/bold] round [cyan]{round_idx}[/cyan] / up to [cyan]{n_days}[/cyan] — "
                f"next sparsest day [green]{target_day.isoformat()}[/green] "
                f"([bold]{min_count}[/bold] article(s) in DB). "
                f"Target: [bold]{m_new}[/bold] new insert(s).\n",
            )
        else:
            console.print(
                f"\n[bold]Sparse fill[/bold]: last [cyan]{n_days}[/cyan] ET day(s) — "
                f"sparsest day [green]{target_day.isoformat()}[/green] "
                f"([bold]{min_count}[/bold] article(s) in DB). "
                f"Target: [bold]{m_new}[/bold] new insert(s).\n",
            )

        for d in sorted(counts.keys()):
            bar = "█" if d == target_day else "░"
            ex = " (done)" if d in excluded else ""
            console.print(f"  {bar} {d.isoformat()}  {counts[d]:>4} articles{ex}")

        await _run_sparse_fill_for_day(
            args, fetcher, tickers, target_day, m_new, seen_urls, seen_hashes,
        )

        if not loop:
            break

        excluded.add(target_day)
        if len(excluded) >= n_days:
            console.print(
                f"\n[dim]Sparse-fill loop finished: processed [cyan]{len(excluded)}[/cyan] day(s).[/dim]",
            )
            break


def main(argv: list[str] | None = None) -> None:
    asyncio.run(_main(argv))


if __name__ == "__main__":
    main()
