"""Backfill any as-of-aware screening board over past sessions.

Screening boards are the ONLY research source the arena can rewind honestly —
they carry ``run_at``, and ``services/arena/tools.py`` bounds reads by it. A
board with one run is therefore worth nothing to a backtest: every replayed
session sees the same snapshot, which is exactly the look-ahead the priced-in
tools already suffer from. This writes one run per past session.

A board opts in by accepting ``screening["_as_of"]`` in its ``run()``. It may
also export ``install_backfill_caches(start, end)``, which is where the real
saving is: run() is written for ONE date and fetches per ticker accordingly, so
across 48 dates the naive bill is 48x. The hook lets each board swap those reads
for ones keyed on TICKER instead of (ticker, date) — roughly 400 requests
instead of 9,600 for a two-month window.

WHAT ACTUALLY REWINDS is board-specific and is recorded on every row the board
writes, under ``data_used.point_in_time``. Nothing here asserts a row is
point-in-time; it only carries what the board itself claimed. A row that merely
LOOKS point-in-time is worse than no row at all.

    python -m services.market_screenings.backfill --screening burry-deep-value \
        --start 2026-07-01 --end 2026-09-04 [--every 1] [--dry-run] [--force]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from importlib import import_module
from typing import Any

from shared.db import get_supabase_client

from .registry import SCRIPTS

log = logging.getLogger(__name__)

_SCHEMA = "swingtrader"


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


def _screening_row(client, slug: str) -> dict[str, Any]:
    res = (
        client.schema(_SCHEMA).table("market_screenings")
        .select("id,slug,name,script_key").eq("slug", slug).limit(1).execute()
    )
    if not res.data:
        raise SystemExit(f"no market_screenings row with slug {slug!r} — run its activate SQL first")
    row = res.data[0]
    if row.get("script_key") not in SCRIPTS:
        raise SystemExit(f"{slug!r} maps to script_key {row.get('script_key')!r}, "
                         f"which is not in the registry")
    return row


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
    ap = argparse.ArgumentParser(prog="backfill", description=__doc__)
    ap.add_argument("--screening", required=True, help="market_screenings slug")
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
    screening = _screening_row(client, args.screening)
    script_key = screening["script_key"]
    module = import_module(f"services.market_screenings.scripts.{script_key}")
    done = set() if args.force else _already_done(client, screening["id"])
    todo = [s for s in sessions if s.isoformat() not in done]

    print(f"{len(sessions)} weekday sessions {start}..{end}; "
          f"{len(sessions) - len(todo)} already present; {len(todo)} to run.")
    if args.dry_run or not todo:
        return 0

    # Each board knows which of its own reads are per-ticker rather than
    # per-(ticker, date) and swaps them here. Without it the bill is the naive
    # 48x; with it, roughly one pass over the distinct tickers.
    installer = getattr(module, "install_backfill_caches", None)
    if installer is None:
        print(f"  note: {script_key} exports no install_backfill_caches — "
              f"this will re-fetch per date and may be slow.")
    else:
        installer(start, end)

    written = 0
    for i, session in enumerate(todo, 1):
        try:
            result = module.run(None, {"slug": args.screening, "_as_of": session})
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


if __name__ == "__main__":
    sys.exit(main())
