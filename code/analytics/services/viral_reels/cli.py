"""
viral_reels.cli — data + render commands for the reel generator.

The `viral-reel` Claude Code skill drives these; you can also run them by hand.

Usage:
    # Inspect what's moving, to choose a subject
    python -m services.viral_reels.cli stories [--window-days 14]
    python -m services.viral_reels.cli snapshot [--window-days 14]

    # Build race keyframes for a subject (-> stdout or --out)
    python -m services.viral_reels.cli series --kind cluster --window-days 14
    python -m services.viral_reels.cli series --kind ticker  --top 8 --value-mode cumulative_articles

    # External overlay
    python -m services.viral_reels.cli prices --ticker NVDA --window-days 30

    # One-shot starter spec the director then edits (copy/captions)
    python -m services.viral_reels.cli scaffold --kind cluster --window-days 14 \
        --overlay-ticker NVDA --out out/reel_spec.json

    # Validate + render
    python -m services.viral_reels.cli validate out/reel_spec.json
    python -m services.viral_reels.cli render   out/reel_spec.json --out out/reel.mp4
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

_ANALYTICS = pathlib.Path(__file__).resolve().parent.parent.parent
_PKG_DIR = pathlib.Path(__file__).resolve().parent
_REEL_DIR = _PKG_DIR / "reel"
# Generated specs + reels land in the repo's conventional output dir
# (alongside carousels/, podcast/, screening/), organised per project rather
# than as one flat pile:
#   output/viral_reels/<TICKER>/data/*.json   raw source pulls (catalysts, fmp…)
#   output/viral_reels/<TICKER>/spec.json     the assembled ReelSpec
#   output/viral_reels/<TICKER>/reel.mp4      the render (lands next to its spec)
#   output/viral_reels/race/                  bar-chart-race (not ticker-scoped)
_OUT_DIR = _ANALYTICS / "output" / "viral_reels"


def _proj_dir(slug: str) -> pathlib.Path:
    """Per-project output folder, e.g. output/viral_reels/NVDA/."""
    return _OUT_DIR / ((slug or "").upper().strip() or "_misc")


def _data_out(ticker: str, name: str) -> str:
    """Default path for a raw source pull under a ticker's data/ folder."""
    return str(_proj_dir(ticker) / "data" / name)

from dotenv import load_dotenv

load_dotenv(_ANALYTICS / ".env")
sys.path.insert(0, str(_ANALYTICS))

from services.viral_reels import data_sources as ds
from services.viral_reels import spec as spec_mod
from services.viral_reels import story_finder


def _emit(obj, out: str | None) -> None:
    text = json.dumps(obj, indent=2)
    if out:
        path = pathlib.Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {path} ({path.stat().st_size} bytes)")
    else:
        print(text)


def cmd_stories(args):
    _emit(story_finder.find_stories(window_days=args.window_days), args.out)


def cmd_snapshot(args):
    _emit(ds.trend_snapshot(window_days=args.window_days), args.out)


def cmd_series(args):
    builder = ds.SERIES_BUILDERS[args.kind]
    kwargs = {"window_days": args.window_days, "value_mode": args.value_mode}
    if args.kind in ("dimension", "ticker"):
        kwargs["top_k"] = args.top
    if args.kind == "ticker" and args.tickers:
        kwargs["tickers"] = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    _emit(builder(**kwargs), args.out)


def cmd_prices(args):
    _emit(ds.price_overlay(args.ticker, window_days=args.window_days),
          args.out or _data_out(args.ticker, "overlay.json"))


def cmd_headlines(args):
    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers
        else None
    )
    _emit(
        ds.headlines(
            window_days=args.window_days,
            limit=args.limit,
            dimension_key=args.dimension_key,
            tickers=tickers,
        ),
        args.out,
    )


def cmd_scaffold(args):
    builder = ds.SERIES_BUILDERS[args.kind]
    kwargs = {"window_days": args.window_days, "value_mode": args.value_mode}
    if args.kind in ("dimension", "ticker"):
        kwargs["top_k"] = args.top
    keyframes = builder(**kwargs)

    overlay = None
    if args.overlay_ticker:
        try:
            overlay = ds.price_overlay(args.overlay_ticker, window_days=max(args.window_days, 30))
        except Exception as exc:
            log.warning("price overlay skipped: %s", exc)

    headlines = []
    if args.headlines:
        try:
            headlines = ds.headlines(
                window_days=args.window_days,
                limit=args.headlines,
                dimension_key=args.dimension_key,
            )
        except Exception as exc:
            log.warning("headlines skipped: %s", exc)

    metric_label = "Articles" if args.kind != "ticker" else "Mentions"
    spec = spec_mod.build_spec(
        keyframes=keyframes,
        metric_label=metric_label,
        value_format="count",
        theme=args.theme,
        title="<EDIT: hook headline>",
        subtitle=f"AI-scored news impact · last {args.window_days} days",
        outro_title="<EDIT: the takeaway>",
        outro_takeaway="<EDIT: one-line so-what>",
        captions=[],
        headlines=headlines,
        overlay=overlay,
    )
    problems = spec_mod.validate(spec)
    if problems:
        log.warning("scaffold produced a spec with issues:\n- %s", "\n- ".join(problems))
    _emit(spec, args.out)


def cmd_article_images(args):
    ids = [int(x) for x in args.ids.split(",") if x.strip()]
    _emit(ds.article_images(ids), args.out)


def cmd_price_news(args):
    """Scaffold a price+news ReelSpec: price line + scored news events on it."""
    chart = ds.price_history(args.ticker, window_days=args.window_days)
    chart["events"] = ds.news_events(
        args.ticker,
        window_days=args.window_days,
        max_events=args.max_events,
        points=chart["points"],
    )
    # Put the first article on the 2nd rendered date so it shows up early.
    chart = ds.align_first_event_to_second_point(chart, lead=1)
    spec = spec_mod.build_price_news_spec(
        chart=chart,
        theme=args.theme,
        title=f"<EDIT: did the news move {args.ticker.upper()}?>",
        subtitle=f"Price vs. AI-scored headlines · last {args.window_days} days",
        outro_title="<EDIT: the takeaway>",
        outro_takeaway="<EDIT: which headlines moved it, and how much>",
    )
    problems = spec_mod.validate(spec)
    if problems:
        log.warning("price-news scaffold has issues:\n- %s", "\n- ".join(problems))
    _emit(spec, args.out or str(_proj_dir(args.ticker) / "spec.json"))


def cmd_card(args):
    """Scaffold a stock-card poster spec (CEO/hero portrait + logo + stats).

    Pulls the FMP company profile + quote and the internal news pulse, fills
    sensible defaults, and writes a card spec the director then edits (headline,
    tag, the fetched CEO ``heroImageUrl``, badge/stat overrides). Render with
    ``render`` — the CLI renders card specs as a single PNG.
    """
    card = ds.build_card(
        args.ticker,
        window_days=args.window_days,
        headline=args.headline,
        tag=args.tag,
        hero_image_url=args.hero_image_url,
        # Auto-fetch a Wikipedia/Commons CEO portrait unless disabled or an
        # explicit --hero-image-url was given.
        fetch_ceo_photo=not args.no_ceo_photo,
        # --no-nis forces an empty list (skip the DB lookup + hide the badge);
        # otherwise auto-detect the screenings featuring this ticker.
        nis_screenings=[] if args.no_nis else None,
    )
    spec = spec_mod.build_card_spec(card=card, theme=args.theme)
    problems = spec_mod.validate(spec)
    if problems:
        log.warning("card scaffold has issues:\n- %s", "\n- ".join(problems))
    _emit(spec, args.out or str(_proj_dir(args.ticker) / "card.json"))


def cmd_news_candidates(args):
    """Dump the full pool of plottable news events for a ticker.

    This is the director's input: Claude Code reviews the pool (each day's
    strongest headline, its next-day move and an advisory ``impact`` score) and
    hand-picks which events to drop into a price-news spec's ``chart.events``.
    """
    chart = ds.price_history(args.ticker, window_days=args.window_days)
    pool = ds.news_candidates(
        args.ticker,
        window_days=args.window_days,
        points=chart["points"],
    )
    _emit(pool, args.out or _data_out(args.ticker, "candidates.json"))


def cmd_catalysts(args):
    """Dump the biggest price moves, each with the headlines that could explain it.

    Price-aware director input: for each of the largest close-to-close moves,
    lists the articles published on the session that produced it (the news just
    *before* the move), so the director can pick the catalyst behind each drop
    or gain when curating a price-news spec.
    """
    chart = ds.price_history(args.ticker, window_days=args.window_days)
    catalysts = ds.move_catalysts(
        args.ticker,
        window_days=args.window_days,
        points=chart["points"],
        top_moves=args.top_moves,
        per_move=args.per_move,
    )
    _emit(catalysts, args.out or _data_out(args.ticker, "catalysts.json"))


def cmd_fmp_news(args):
    """Dump FMP stock-news headlines for a ticker as plottable events.

    Broader/fresher coverage than the internal feed (and always an article
    image). Sentiment is recovered from internal scores by url where possible;
    otherwise neutral. The next-day price move is annotated from FMP OHLC.
    """
    chart = ds.price_history(args.ticker, window_days=args.window_days)
    news = ds.fmp_stock_news(
        args.ticker,
        window_days=args.window_days,
        limit=args.limit,
        points=chart["points"],
        enrich_sentiment=not args.no_sentiment,
    )
    _emit(news, args.out or _data_out(args.ticker, "fmp_news.json"))


def cmd_fmp_press(args):
    """Dump FMP company press releases for a ticker as plottable events.

    The company's own catalysts at their exact timestamp — best for anchoring a
    price move to its true cause (e.g. an earnings release) when third-party
    write-ups lag a day. No image/sentiment; next-day move annotated from OHLC.
    """
    chart = ds.price_history(args.ticker, window_days=args.window_days)
    press = ds.fmp_press_releases(
        args.ticker,
        window_days=args.window_days,
        limit=args.limit,
        points=chart["points"],
    )
    _emit(press, args.out or _data_out(args.ticker, "fmp_press.json"))


def cmd_validate(args):
    spec = spec_mod.load(args.spec)
    problems = spec_mod.validate(spec)
    if problems:
        print("INVALID:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("OK — spec is valid")
    # Non-fatal coverage check: price-news reels should plot an event every few
    # chart ticks so the line is never empty for long.
    for w in spec_mod.event_spacing_warnings(spec):
        print(f"  ! coverage: {w}")


def cmd_render(args):
    spec_path = pathlib.Path(args.spec).resolve()
    if not spec_path.exists():
        print(f"spec not found: {spec_path}", file=sys.stderr)
        sys.exit(1)
    spec = spec_mod.load(spec_path)
    problems = spec_mod.validate(spec)
    if problems and not args.force:
        print("Refusing to render an invalid spec (use --force to override):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)
    for w in spec_mod.event_spacing_warnings(spec):
        log.warning("event coverage: %s", w)

    still = spec_mod.is_still(spec)
    # Default the render next to its spec — a PNG for card (still) specs, else
    # the reel mp4.
    default_name = "card.png" if still else "reel.mp4"
    out_path = pathlib.Path(args.out or (spec_path.parent / default_name)).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not (_REEL_DIR / "node_modules").exists():
        print(
            "Remotion deps not installed. Run:\n"
            f"  cd {_REEL_DIR} && npm install",
            file=sys.stderr,
        )
        sys.exit(1)

    # Remotion input props must match the composition's prop shape, i.e.
    # {"spec": <ReelSpec>} — passing a bare ReelSpec silently loses to the
    # default props during the merge. Write a wrapped props file next to the
    # spec and hand that to Remotion.
    props_path = out_path.parent / "_remotion_props.json"
    props_path.write_text(json.dumps({"spec": spec}))

    composition = args.composition or spec_mod.composition_for(spec)
    # Card specs are single posters → `remotion still`; everything else is a
    # video → `remotion render`.
    verb = "still" if still else "render"
    cmd = [
        "npx",
        "remotion",
        verb,
        "src/index.ts",
        composition,
        str(out_path),
        f"--props={props_path}",
    ]
    log.info("rendering: %s (cwd=%s)", " ".join(cmd), _REEL_DIR)
    result = subprocess.run(cmd, cwd=_REEL_DIR)
    if result.returncode != 0:
        sys.exit(result.returncode)
    print(f"rendered {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Viral reel generator")
    sub = parser.add_subparsers(dest="command")

    p_stories = sub.add_parser("stories", help="Rank candidate viral stories")
    p_stories.add_argument("--window-days", type=int, default=30)
    p_stories.add_argument("--out", default=None)

    p_snap = sub.add_parser("snapshot", help="Cluster/dimension movers snapshot")
    p_snap.add_argument("--window-days", type=int, default=30)
    p_snap.add_argument("--out", default=None)

    p_series = sub.add_parser("series", help="Build race keyframes")
    p_series.add_argument("--kind", choices=list(ds.SERIES_BUILDERS), required=True)
    p_series.add_argument("--window-days", type=int, default=30)
    p_series.add_argument("--top", type=int, default=8)
    p_series.add_argument("--value-mode", choices=ds.VALUE_MODES, default="cumulative_articles")
    p_series.add_argument("--tickers", default=None, help="comma list (ticker kind only)")
    p_series.add_argument("--out", default=None)

    p_prices = sub.add_parser("prices", help="FMP price overlay for a ticker")
    p_prices.add_argument("--ticker", required=True)
    p_prices.add_argument("--window-days", type=int, default=30)
    p_prices.add_argument("--out", default=None)

    p_hl = sub.add_parser("headlines", help="Top article headlines behind a window (UI-styled cards)")
    p_hl.add_argument("--window-days", type=int, default=30)
    p_hl.add_argument("--limit", type=int, default=8)
    p_hl.add_argument("--dimension-key", default=None, help="rank by load on this dimension")
    p_hl.add_argument("--tickers", default=None, help="comma list to scope by ticker")
    p_hl.add_argument("--out", default=None)

    p_scaf = sub.add_parser("scaffold", help="Build a starter ReelSpec to edit")
    p_scaf.add_argument("--kind", choices=list(ds.SERIES_BUILDERS), default="cluster")
    p_scaf.add_argument("--window-days", type=int, default=30)
    p_scaf.add_argument("--top", type=int, default=8)
    p_scaf.add_argument("--value-mode", choices=ds.VALUE_MODES, default="cumulative_articles")
    p_scaf.add_argument("--theme", default="midnight")
    p_scaf.add_argument("--overlay-ticker", default=None)
    p_scaf.add_argument("--headlines", type=int, default=0, help="include N real headline cards")
    p_scaf.add_argument("--dimension-key", default=None, help="rank headlines by this dimension")
    p_scaf.add_argument("--out", default=str(_OUT_DIR / "race" / "reel_spec.json"))

    p_ai = sub.add_parser("article-images", help="Look up id/title/source/image_url for article ids")
    p_ai.add_argument("--ids", required=True, help="comma-separated news_articles ids, e.g. 117422,117510")
    p_ai.add_argument("--out", default=None)

    p_pn = sub.add_parser("price-news", help="Scaffold a price+news chart reel (price line + events)")
    p_pn.add_argument("--ticker", required=True)
    p_pn.add_argument("--window-days", type=int, default=45)
    p_pn.add_argument("--max-events", type=int, default=8)
    p_pn.add_argument("--theme", default="midnight")
    p_pn.add_argument("--out", default=None,
                      help="defaults to output/viral_reels/<TICKER>/spec.json")

    p_card = sub.add_parser("card",
                            help="Scaffold a stock-card poster (CEO/hero portrait + logo + stats)")
    p_card.add_argument("--ticker", required=True)
    p_card.add_argument("--window-days", type=int, default=14, help="window for the news pulse")
    p_card.add_argument("--headline", default=None, help="the big hook headline (else a placeholder)")
    p_card.add_argument("--tag", default=None, help="pill under the headline, e.g. 'Earnings Beat'")
    p_card.add_argument("--hero-image-url", default=None,
                        help="explicit CEO photo URL; overrides the auto Wikipedia fetch")
    p_card.add_argument("--no-ceo-photo", action="store_true",
                        help="skip the Wikipedia/Commons CEO-portrait fetch (use the logo)")
    p_card.add_argument("--no-nis", action="store_true",
                        help="skip the NIS-screening badge lookup (hide the badge)")
    p_card.add_argument("--theme", default="midnight")
    p_card.add_argument("--out", default=None,
                        help="defaults to output/viral_reels/<TICKER>/card.json")

    p_nc = sub.add_parser("news-candidates",
                          help="Dump the full pool of plottable news events (director picks from this)")
    p_nc.add_argument("--ticker", required=True)
    p_nc.add_argument("--window-days", type=int, default=30)
    p_nc.add_argument("--out", default=None)

    p_cat = sub.add_parser("catalysts",
                          help="Biggest price moves + the headlines that could explain each (director input)")
    p_cat.add_argument("--ticker", required=True)
    p_cat.add_argument("--window-days", type=int, default=30)
    p_cat.add_argument("--top-moves", type=int, default=8, help="how many of the largest moves to surface")
    p_cat.add_argument("--per-move", type=int, default=4, help="candidate articles per move")
    p_cat.add_argument("--out", default=None)

    p_fn = sub.add_parser("fmp-news",
                          help="FMP stock-news headlines as plottable events (broader coverage)")
    p_fn.add_argument("--ticker", required=True)
    p_fn.add_argument("--window-days", type=int, default=30)
    p_fn.add_argument("--limit", type=int, default=100)
    p_fn.add_argument("--no-sentiment", action="store_true",
                      help="skip recovering internal AI sentiment by url match")
    p_fn.add_argument("--out", default=None)

    p_fp = sub.add_parser("fmp-press",
                          help="FMP company press releases as plottable events (exact catalyst timing)")
    p_fp.add_argument("--ticker", required=True)
    p_fp.add_argument("--window-days", type=int, default=30)
    p_fp.add_argument("--limit", type=int, default=100)
    p_fp.add_argument("--out", default=None)

    p_val = sub.add_parser("validate", help="Validate a ReelSpec JSON file")
    p_val.add_argument("spec")

    p_render = sub.add_parser("render", help="Render a ReelSpec to MP4 via Remotion")
    p_render.add_argument("spec")
    p_render.add_argument("--out", default=None)
    p_render.add_argument("--composition", default=None,
                          help="override the composition (default: inferred from the spec shape)")
    p_render.add_argument("--force", action="store_true", help="render even if validation fails")

    args = parser.parse_args()
    dispatch = {
        "stories": cmd_stories,
        "snapshot": cmd_snapshot,
        "series": cmd_series,
        "prices": cmd_prices,
        "headlines": cmd_headlines,
        "article-images": cmd_article_images,
        "scaffold": cmd_scaffold,
        "price-news": cmd_price_news,
        "card": cmd_card,
        "news-candidates": cmd_news_candidates,
        "catalysts": cmd_catalysts,
        "fmp-news": cmd_fmp_news,
        "fmp-press": cmd_fmp_press,
        "validate": cmd_validate,
        "render": cmd_render,
    }
    fn = dispatch.get(args.command)
    if not fn:
        parser.print_help()
        return
    fn(args)


if __name__ == "__main__":
    main()
