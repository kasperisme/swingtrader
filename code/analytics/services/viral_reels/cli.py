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
    _emit(ds.price_overlay(args.ticker, window_days=args.window_days), args.out)


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
        overlay=overlay,
    )
    problems = spec_mod.validate(spec)
    if problems:
        log.warning("scaffold produced a spec with issues:\n- %s", "\n- ".join(problems))
    _emit(spec, args.out)


def cmd_validate(args):
    spec = spec_mod.load(args.spec)
    problems = spec_mod.validate(spec)
    if problems:
        print("INVALID:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("OK — spec is valid")


def cmd_render(args):
    spec_path = pathlib.Path(args.spec).resolve()
    if not spec_path.exists():
        print(f"spec not found: {spec_path}", file=sys.stderr)
        sys.exit(1)
    problems = spec_mod.validate(spec_mod.load(spec_path))
    if problems and not args.force:
        print("Refusing to render an invalid spec (use --force to override):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)

    out_path = pathlib.Path(args.out or (_PKG_DIR / "out" / "reel.mp4")).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not (_REEL_DIR / "node_modules").exists():
        print(
            "Remotion deps not installed. Run:\n"
            f"  cd {_REEL_DIR} && npm install",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = [
        "npx",
        "remotion",
        "render",
        "src/index.ts",
        args.composition,
        str(out_path),
        f"--props={spec_path}",
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
    p_stories.add_argument("--window-days", type=int, default=14)
    p_stories.add_argument("--out", default=None)

    p_snap = sub.add_parser("snapshot", help="Cluster/dimension movers snapshot")
    p_snap.add_argument("--window-days", type=int, default=14)
    p_snap.add_argument("--out", default=None)

    p_series = sub.add_parser("series", help="Build race keyframes")
    p_series.add_argument("--kind", choices=list(ds.SERIES_BUILDERS), required=True)
    p_series.add_argument("--window-days", type=int, default=14)
    p_series.add_argument("--top", type=int, default=8)
    p_series.add_argument("--value-mode", choices=ds.VALUE_MODES, default="cumulative_articles")
    p_series.add_argument("--tickers", default=None, help="comma list (ticker kind only)")
    p_series.add_argument("--out", default=None)

    p_prices = sub.add_parser("prices", help="FMP price overlay for a ticker")
    p_prices.add_argument("--ticker", required=True)
    p_prices.add_argument("--window-days", type=int, default=30)
    p_prices.add_argument("--out", default=None)

    p_scaf = sub.add_parser("scaffold", help="Build a starter ReelSpec to edit")
    p_scaf.add_argument("--kind", choices=list(ds.SERIES_BUILDERS), default="cluster")
    p_scaf.add_argument("--window-days", type=int, default=14)
    p_scaf.add_argument("--top", type=int, default=8)
    p_scaf.add_argument("--value-mode", choices=ds.VALUE_MODES, default="cumulative_articles")
    p_scaf.add_argument("--theme", default="midnight")
    p_scaf.add_argument("--overlay-ticker", default=None)
    p_scaf.add_argument("--out", default=str(_PKG_DIR / "out" / "reel_spec.json"))

    p_val = sub.add_parser("validate", help="Validate a ReelSpec JSON file")
    p_val.add_argument("spec")

    p_render = sub.add_parser("render", help="Render a ReelSpec to MP4 via Remotion")
    p_render.add_argument("spec")
    p_render.add_argument("--out", default=None)
    p_render.add_argument("--composition", default="BarChartRace")
    p_render.add_argument("--force", action="store_true", help="render even if validation fails")

    args = parser.parse_args()
    dispatch = {
        "stories": cmd_stories,
        "snapshot": cmd_snapshot,
        "series": cmd_series,
        "prices": cmd_prices,
        "scaffold": cmd_scaffold,
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
