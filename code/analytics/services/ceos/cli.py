"""CLI — fill and inspect `swingtrader.company_ceos` (the /ceos directory).

    .venv/bin/python -m services.ceos.cli refresh --limit 500          # largest 500 not fetched in 30d
    .venv/bin/python -m services.ceos.cli refresh --symbols NVDA,GOOGL  # specific tickers, always
    .venv/bin/python -m services.ceos.cli refresh --dry-run --limit 5   # fetch + print, no writes
    .venv/bin/python -m services.ceos.cli show NVDA                     # a row, or a slug
    .venv/bin/python -m services.ceos.cli stats
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

from shared.db import get_pg_connection
from services.ceos import store
from services.ceos.fmp import Fmp, FmpQuotaError, fetch_company

# Symbols FMP names no CEO for (ETFs, SPACs, shells). Remembered locally so a
# nightly pass does not spend three calls re-asking about each one.
_MISSES = Path(__file__).resolve().parents[2] / "output" / "ceos" / "misses.json"


def _load_misses(max_age_days: float) -> dict[str, str]:
    try:
        data = json.loads(_MISSES.read_text())
    except (OSError, ValueError):
        return {}
    cutoff = (date.today() - timedelta(days=max_age_days)).isoformat()
    return {s: d for s, d in data.items() if d >= cutoff}


def _save_misses(misses: dict[str, str]) -> None:
    _MISSES.parent.mkdir(parents=True, exist_ok=True)
    _MISSES.write_text(json.dumps(misses, indent=0, sort_keys=True))


def cmd_refresh(args) -> int:
    conn = get_pg_connection()
    explicit = [s.strip().upper() for s in (args.symbols or "").split(",") if s.strip()]
    misses = _load_misses(args.stale_days)
    todo = store.universe(conn, symbols=explicit or None, limit=None, stale_days=args.stale_days)
    if not explicit:
        todo = [s for s in todo if s not in misses][: args.limit]
    print(f"  {len(todo)} symbols to fetch ({args.workers} workers, {args.rpm} calls/min)")
    if not todo:
        return 0

    fmp = Fmp(per_minute=args.rpm)
    batch: list[dict] = []
    gone: list[str] = []
    failed: list[str] = []
    written = 0
    fetched = 0
    quota_hit: str | None = None

    def flush():
        nonlocal written, batch
        if args.dry_run or not batch:
            batch = []
            return
        written += store.upsert(conn, batch)
        batch = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_company, fmp, s): s for s in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            sym = futures[fut]
            # as_completed still yields the futures cancelled below; .result()
            # on one raises CancelledError, so they are skipped, not read.
            if fut.cancelled():
                continue
            try:
                row = fut.result()
            except FmpQuotaError as e:
                # Stop queueing more work; what already landed still gets written.
                if quota_hit is None:
                    quota_hit = str(e)
                    for f in futures:
                        f.cancel()
                continue
            except Exception as e:  # one bad symbol must not sink the batch
                failed.append(sym)
                print(f"  ! {sym}: {type(e).__name__}: {e}", file=sys.stderr)
                continue
            if row is None:
                gone.append(sym)
                misses[sym] = date.today().isoformat()
            else:
                fetched += 1
                batch.append(row)
                if args.dry_run:
                    comp = row["compensation"][0] if row["compensation"] else {}
                    print(f"  {sym:<6} {row['ceo_name']:<32} {row['ceo_title'] or '—':<40} "
                          f"born {row['year_born'] or '—'}  comp {comp.get('year', '—')} "
                          f"{comp.get('total') or '—'}  team {len(row['executives'])}")
            if len(batch) >= 100:
                flush()
            if i % 250 == 0:
                print(f"  … {i}/{len(todo)}")
    flush()

    if quota_hit:
        print(f"  ✗ FMP quota exhausted, run stopped early: {quota_hit}", file=sys.stderr)

    if not args.dry_run:
        removed = store.delete(conn, gone)
        relabelled = store.assign_slugs(conn)
        _save_misses(misses)
        print(f"  ✓ wrote {written}, removed {removed} (no CEO), re-slugged {relabelled}, "
              f"failed {len(failed)}")
    else:
        print(f"  dry run: {fetched} rows fetched, {len(gone)} without a CEO, "
              f"{len(failed)} failed")
    return 1 if quota_hit or (failed and len(failed) == len(todo)) else 0


def cmd_show(args) -> int:
    conn = get_pg_connection()
    key = args.key.strip()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT row_to_json(c) FROM swingtrader.company_ceos c "
            "WHERE c.symbol = %s OR c.ceo_slug = %s",
            (key.upper(), key.lower()),
        )
        rows = [r[0] for r in cur.fetchall()]
    if not rows:
        print(f"  no row for {key}")
        return 1
    print(json.dumps(rows, indent=2, default=str))
    return 0


def cmd_stats(_args) -> int:
    conn = get_pg_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*), count(DISTINCT ceo_slug),
                   count(*) FILTER (WHERE jsonb_array_length(compensation) > 0),
                   count(*) FILTER (WHERE year_born IS NOT NULL),
                   min(fetched_at), max(fetched_at)
            FROM swingtrader.company_ceos
            """
        )
        n, people, comp, born, oldest, newest = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM swingtrader.tickers WHERE COALESCE(is_actively_trading, true)"
        )
        (universe,) = cur.fetchone()
    print(f"  rows        {n:,} of {universe:,} actively-traded tickers")
    print(f"  people      {people:,}")
    print(f"  with pay    {comp:,}")
    print(f"  with born   {born:,}")
    print(f"  fetched     {oldest} → {newest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="services.ceos.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("refresh", help="fetch CEOs from FMP into company_ceos")
    r.add_argument("--symbols", help="comma-separated; bypasses the staleness filter")
    r.add_argument("--limit", type=int, default=500)
    r.add_argument("--stale-days", type=float, default=30)
    r.add_argument("--workers", type=int, default=6)
    r.add_argument("--rpm", type=int, default=600, help="FMP calls per minute, all workers")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_refresh)

    s = sub.add_parser("show", help="print the row(s) for a symbol or slug")
    s.add_argument("key")
    s.set_defaults(fn=cmd_show)

    st = sub.add_parser("stats")
    st.set_defaults(fn=cmd_stats)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
