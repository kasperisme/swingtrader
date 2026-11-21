"""Drawdown recon CLI. Only the snapshot collector exists so far (SPEC.md §14 step 1).

    python -m services.drawdown.cli snapshot                 # today (US/Eastern): estimates + macro -> JSONL + Supabase
    python -m services.drawdown.cli snapshot --limit 20 --no-db
    python -m services.drawdown.cli load --date 2026-11-21   # backfill Supabase from a day's JSONL
    python -m services.drawdown.cli narrative                # priced-in narrative stress test -> output/drawdown/narrative/<date>/
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from dotenv import load_dotenv


def main() -> None:
    load_dotenv(".env")
    ap = argparse.ArgumentParser(prog="services.drawdown.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="snapshot analyst estimates + macro series")
    s.add_argument("--limit", type=int, default=None, help="first N symbols only (testing)")
    s.add_argument("--no-db", action="store_true", help="write JSONL only")

    l = sub.add_parser("load", help="upsert a day's JSONL into Supabase")
    l.add_argument("--date", type=date.fromisoformat, required=True)

    n = sub.add_parser("narrative", help="stress-test every priced-in narrative against today's consensus")
    n.add_argument("--drop-date", type=date.fromisoformat, default=date(2026, 11, 20))
    n.add_argument("--no-db", action="store_true", help="write files only")

    a = ap.parse_args()
    if a.cmd == "narrative":
        from . import narrative

        res = narrative.run(drop_date=a.drop_date, db=not a.no_db)
        print(json.dumps(res["meta"], indent=2))
        for g in ("on_top", "drowns"):
            print(f"\n{g}:")
            for r in [r for r in res["rows"] if r.group == g][:15]:
                print(f"  {r.rank:>3} {r.ticker:<6} {r.reason}  [{r.flags}]")
        print("\n->", res["out_dir"])
        if not res["meta"]["db"].startswith(("written", "skipped")):
            sys.exit(3)
        return
    from . import snapshots

    if a.cmd == "snapshot":
        res = snapshots.run(limit=a.limit, write_db=not a.no_db)
    else:
        res = snapshots.load(a.date)
    print(json.dumps(res.__dict__, indent=2))
    # Non-zero exit so cron/job_health sees a bad day: a partial run, or a day that
    # never reached the database. The JSONL is kept either way.
    if res.status != "complete" or not res.db.startswith("written"):
        sys.exit(2 if res.status != "complete" else 3)


if __name__ == "__main__":
    main()
