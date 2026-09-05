"""Backfill the Burry board over past sessions, so a replay has history.

Screening boards are the ONLY research source the arena can rewind honestly —
they carry ``run_at``, and ``services/arena/tools.py`` bounds reads by it. A
board with one run is therefore worth nothing to a backtest: every replayed
session sees the same snapshot, which is exactly the look-ahead the priced-in
tools already suffer from. This writes one run per past session so a replayed
2 July decision reads the board as it would have stood on 2 July.

WHAT ACTUALLY REWINDS, and what does not. Being precise about this matters more
than the backfill itself, because a row that merely looks point-in-time is worse
than no row at all:

  ✅ mentions + sentiment — recomputed from news_articles.published_at over the
     90 days ending on the as-of date. Raw sources go back to 2025-04-10, well
     past the 120-day rolling window ticker_coverage_daily keeps.
  ✅ price and market cap — the FMP daily close on the date, used to reprice
     EV/EBITDA and free-cash-flow yield (see _reprice_value).
  ❌ EBITDA, free cash flow, net debt — FMP serves the CURRENT TTM, not what was
     on file that day. Same limitation the arena README records for Barren
     Wuffett. A company that has since restated or reported looks, on a July
     date, like it already had numbers it published in August.
  ❌ sector and liquidity membership — current FMP screener output, so a name
     that has since been delisted or fallen below the volume floor is missing
     from every historical run.
  ⚠️  sentiment SCORES — the article existed on its publication date; the LLM
     score exists because we ran a scorer later. The score reads text that was
     public at the time, so it is a defensible approximation, not a clean one.

Every backfilled row carries that table in ``data_used.point_in_time`` and is
tagged ``is_test = false`` but with ``backfilled`` in the summary, so nothing
downstream mistakes it for a live observation.

Cost control: the per-ticker FMP reads (key metrics, daily bars) are cached
across dates, so the bill is roughly two calls per DISTINCT ticker rather than
two per ticker per date.

    python -m services.market_screenings.backfill_burry --start 2026-07-01 \
        --end 2026-09-04 [--every 1] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

from shared.db import get_supabase_client

from .scripts import burry_deep_value as burry

log = logging.getLogger(__name__)

_SCHEMA = "swingtrader"
_SLUG = "burry-deep-value"


def _sessions(start: date, end: date, every: int) -> list[date]:
    """Weekdays in the range, every Nth. Holidays are not filtered — a run on a
    closed day simply reprices against the previous close, which is what the
    board would have shown that morning anyway."""
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out[::max(1, every)]


def _screening_row(client) -> dict[str, Any]:
    res = (
        client.schema(_SCHEMA).table("market_screenings")
        .select("id,slug,name").eq("slug", _SLUG).limit(1).execute()
    )
    if not res.data:
        raise SystemExit(f"no market_screenings row with slug {_SLUG!r} — run the activate SQL first")
    return res.data[0]


def _already_done(client, screening_id: str) -> set[str]:
    """Dates already backfilled, so a re-run resumes instead of duplicating."""
    res = (
        client.schema(_SCHEMA).table("market_screening_results")
        .select("run_at").eq("market_screening_id", screening_id).execute()
    )
    return {str(r["run_at"])[:10] for r in (res.data or [])}


def _persist(client, screening_id: str, session: date, result) -> int:
    """One result row plus its per-ticker rows, stamped at the session's close."""
    payload = result.data_used or {}
    symbols = payload.get("symbols") or []
    lean = {k: v for k, v in payload.items() if k != "symbols"}
    run_at = datetime.combine(session, datetime.min.time(), tzinfo=timezone.utc) \
        .replace(hour=13, minute=0)

    ins = (
        client.schema(_SCHEMA).table("market_screening_results")
        .insert({
            "market_screening_id": screening_id,
            "run_at": run_at.isoformat(),
            "started_at": run_at.isoformat(),
            "status": "done",
            "triggered": bool(result.triggered),
            "summary": (result.summary or "") + "\n\n[backfilled run — see data_used.point_in_time]",
            "data_used": lean,
            "error": result.error,
            "is_test": False,
        }).execute()
    )
    result_id = (ins.data or [{}])[0].get("id")
    if not result_id or not symbols:
        return 0
    client.schema(_SCHEMA).table("market_screening_result_rows").insert([
        {
            "market_screening_id": screening_id,
            "result_id": result_id,
            "scan_date": session.isoformat(),
            "dataset": "default",
            "symbol": s.get("symbol"),
            "row_data": s,
        }
        for s in symbols if isinstance(s, dict) and s.get("symbol")
    ]).execute()
    return len(symbols)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="backfill-burry", description=__doc__)
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--every", type=int, default=1, help="every Nth weekday (1 = daily)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    ap.add_argument("--force", action="store_true", help="re-run dates that already have a row")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S")
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    sessions = _sessions(start, end, args.every)

    client = get_supabase_client()
    screening = _screening_row(client)
    done = set() if args.force else _already_done(client, screening["id"])
    todo = [s for s in sessions if s.isoformat() not in done]

    print(f"{len(sessions)} weekday sessions {start}..{end}; "
          f"{len(sessions) - len(todo)} already present; {len(todo)} to run.")
    if args.dry_run or not todo:
        return 0

    # Two caches, both keyed on TICKER rather than (ticker, date), because the
    # same names recur on most sessions. Without them the bill is one key-metrics
    # call and one price call per ticker PER DATE — roughly 9,600 requests for
    # this window instead of ~400.
    burry._value_read = _memoize(burry._value_read)          # type: ignore[assignment]
    burry._price_ratio = _series_backed_price_ratio(start, end)  # type: ignore[assignment]

    written = 0
    for i, session in enumerate(todo, 1):
        try:
            result = burry.run(None, {"slug": _SLUG, "_as_of": session})
        except Exception as exc:                               # noqa: BLE001
            log.exception("backfill: %s failed", session)
            print(f"  [{i}/{len(todo)}] {session}  ERROR {exc}")
            continue
        n = _persist(client, screening["id"], session, result)
        written += 1
        d = result.data_used or {}
        print(f"  [{i}/{len(todo)}] {session}  "
              f"{d.get('passed_long', 0)} long / {d.get('passed_short', 0)} short "
              f"({n} rows, from {d.get('attention_candidates', 0)} candidates)")

    print(f"\nwrote {written} runs.")
    return 0


def _series_backed_price_ratio(start: date, end: date):
    """A ``_price_ratio`` that fetches each ticker's bars ONCE for the window.

    The screen's own version asks FMP for a short range per call, which is right
    for a single live run and catastrophic across 48 of them. This pulls one
    series per ticker covering the whole backfill and then answers every date
    out of memory, falling back to the last close at or before the session so a
    holiday or a halted name still prices.
    """
    cache: dict[str, list[tuple[str, float]]] = {}
    frm = (start - timedelta(days=10)).strftime("%Y-%m-%d")
    to = end.strftime("%Y-%m-%d")

    def load(fmp_client, symbol: str) -> list[tuple[str, float]]:
        if symbol in cache:
            return cache[symbol]
        series: list[tuple[str, float]] = []
        try:
            df = fmp_client.daily_chart(symbol, frm, to)
            if df is not None and not getattr(df, "empty", True):
                col = "close" if "close" in df.columns else df.columns[-1]
                for _, row in df.iterrows():
                    try:
                        series.append((str(row["date"])[:10], float(row[col])))
                    except Exception:                          # noqa: BLE001
                        continue
                series.sort()
        except Exception as exc:                               # noqa: BLE001
            log.debug("backfill: no bars for %s: %s", symbol, exc)
        cache[symbol] = series
        return series

    def ratio(fmp_client, symbol: str, as_of: date, price_now):
        if not price_now or price_now <= 0:
            return None
        series = load(fmp_client, symbol)
        key = as_of.isoformat()
        prior = [px for d, px in series if d <= key]
        if not prior:
            return None
        return prior[-1] / price_now

    return ratio


def _memoize(fn):
    cache: dict[tuple, Any] = {}

    def wrapped(client, symbol, *a, **kw):
        if symbol not in cache:
            cache[symbol] = fn(client, symbol, *a, **kw)
        return cache[symbol]
    return wrapped


if __name__ == "__main__":
    sys.exit(main())
