"""Drawdown recon CLI. Only the snapshot collector exists so far (SPEC.md §14 step 1).

    python -m services.drawdown.cli snapshot                 # today (US/Eastern): estimates + macro -> JSONL + Supabase
    python -m services.drawdown.cli snapshot --limit 20 --no-db
    python -m services.drawdown.cli load --date 2026-11-21   # backfill Supabase from a day's JSONL
    python -m services.drawdown.cli narrative                # priced-in narrative stress test -> output/drawdown/narrative/<date>/
    python -m services.drawdown.cli judge batches            # panel review: blind sector batches (+ news, trend)
    python -m services.drawdown.cli judge whatif --ticker MU --margin 0.22 --cut 0.15
    python -m services.drawdown.cli judge commit --batch <batch_NN.json>  # hash the verdict draft (before reveal)
    python -m services.drawdown.cli judge reveal --batch <batch_NN.json>  # the rule's answer, after commit
    python -m services.drawdown.cli judge check --batch <batch_NN.json>   # panel + verdict vs the arithmetic
    python -m services.drawdown.cli judge apply [--db]       # merge -> output/drawdown/judged/<date>/scorecard.json
    python -m services.drawdown.cli picks pool               # reviewed long/short pools (unranked) -> output/drawdown/picks/<date>/
    python -m services.drawdown.cli picks dossiers --tickers MU,PINS   # evidence bundles for the names chosen to research
    python -m services.drawdown.cli picks deep --file <research_queue.json>   # deep-panel batches
    python -m services.drawdown.cli picks deep-check --batch <deep_NN.json>
    python -m services.drawdown.cli picks seal --file <picks.json>   # validate, stamp entry prices, seal (once per day)
    python -m services.drawdown.cli picks control --date 2026-11-21  # seal the random control + research queue (before the next open)
    python -m services.drawdown.cli picks grade --date 2026-11-21    # sealed picks vs SPY since entry, and vs the control
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

    pk = sub.add_parser("picks", help="long/short picks: pool -> (agents choose + research) -> dossiers -> seal -> grade")
    pk.add_argument("action", choices=["pool", "dossiers", "deep", "deep-check", "seal", "control", "grade"])
    pk.add_argument("--as-of", default=None, help="pool/dossiers: use this day's reviewed scorecard (default: latest)")
    pk.add_argument("--tickers", default=None, help="dossiers: comma-separated names the session chose to research")
    pk.add_argument("--file", default=None, help="seal: the book's picks.json; deep: research_queue.json")
    pk.add_argument("--batch", default=None, help="deep-check: a deep_NN.json path")
    pk.add_argument("--size", type=int, default=8, help="deep: names per deep panel")
    pk.add_argument("--date", default=None, help="grade: the sealed day")

    j = sub.add_parser("judge", help="agent review of the stress test: batches -> (agents) -> check -> apply")
    j.add_argument("action", choices=["batches", "whatif", "commit", "reveal", "check", "apply"])
    j.add_argument("--as-of", default=None)
    j.add_argument("--size", type=int, default=60, help="batches: names per panel")
    j.add_argument("--manifest", help="apply: run manifest JSON (reviewer, model, agent ids)")
    j.add_argument("--ticker")
    j.add_argument("--margin", type=float, help="whatif: margin as a fraction, e.g. 0.25")
    j.add_argument("--cut", type=float, help="whatif: cut to 3y consensus growth as a fraction, e.g. 0.12")
    j.add_argument("--r", type=float, help="whatif: discount rate, e.g. 0.09")
    j.add_argument("--batch", help="commit/reveal/check: a batch_NN.json path")
    j.add_argument("--db", action="store_true", help="apply: also write the reviewed day to Supabase")

    a = ap.parse_args()
    if a.cmd == "judge":
        from . import judge

        if a.action == "batches":
            res = judge.batches(a.as_of, a.size)
            for b in res["batches"]:
                print(f"  batch {b['batch']:02d}  {b['n']:>3} names  {', '.join(b['sectors'])}\n     in  {b['path']}")
            print(f"\n{len(res['batches'])} batches; panel paths in {res['batches'][0]['path'].rsplit('/', 1)[0]}/index.json")
        elif a.action == "whatif":
            if not a.ticker:
                ap.error("whatif needs --ticker")
            print(json.dumps(judge.whatif(a.ticker, a.margin, a.cut, a.r, a.as_of), indent=2))
        elif a.action in ("commit", "reveal"):
            if not a.batch:
                ap.error(f"{a.action} needs --batch")
            res = getattr(judge, a.action)(a.batch)
            print(json.dumps(res, indent=1))
            sys.exit(0 if res.get("ok", "error" not in res) else 5)
        elif a.action == "check":
            if not a.batch:
                ap.error("check needs --batch")
            res = judge.check(a.batch)
            print(json.dumps(res, indent=2))
            sys.exit(0 if res["ok"] else 5)
        else:
            res = judge.apply(a.as_of, db=a.db, manifest=a.manifest)
            print(json.dumps(res.get("meta", res), indent=2, default=str))
            if not res["ok"] or not res["meta"]["db"].startswith(("written", "skipped")):
                sys.exit(5)
        return
    if a.cmd == "picks":
        from . import picks

        if a.action == "pool":
            res = picks.pool(as_of=a.as_of)
            f = lambda v, d=0: "—" if v is None else f"{v:+.{d}%}"  # noqa: E731
            for side in ("long", "short"):
                print(f"\n{side} pool: {len(res[side])} reviewed names (alphabetical by sector; no ranking)")
                for r in res[side]:
                    print(f"  {r['ticker']:<6} {r['group']:<8} cushion {r['cushion_pt']:+6.1f}pt  panel cut {r['panel_cut_pt']}pt  "
                          f"in-sector {r['sector_pct']}  trend {r['trend']:<5} 3m {f(r['ret_3m'])}  beta {r['beta_spy_1y'] and round(r['beta_spy_1y'], 2)}  "
                          f"{r['quality']:<7} {r['exposure']:<6} {r['sector']}")
            if res["dropped"]:
                print("\ndropped:", "; ".join(f"{d['ticker']} ({d['why']})" for d in res["dropped"]))
            print("\n->", res["out_dir"])
        elif a.action == "dossiers":
            if not a.tickers:
                ap.error("dossiers needs --tickers")
            print(json.dumps(picks.dossiers([t.strip().upper() for t in a.tickers.split(",") if t.strip()], a.as_of), indent=2))
        elif a.action == "deep":
            if not a.file:
                ap.error("deep needs --file research_queue.json")
            for b in picks.deep(a.file, a.size)["batches"]:
                print(f"  deep {b['deep']:02d} {b['side']:<5} {', '.join(b['tickers'])}\n     {b['path']}")
        elif a.action == "deep-check":
            if not a.batch:
                ap.error("deep-check needs --batch")
            res = picks.deep_check(a.batch)
            print(json.dumps(res, indent=1))
            sys.exit(0 if res["ok"] else 5)
        elif a.action == "seal":
            if not a.file:
                ap.error("seal needs --file")
            try:
                body = picks.seal(a.file)
            except (ValueError, FileExistsError) as exc:
                print(exc)
                sys.exit(4)
            print(f"sealed {body['as_of']}  sha256 {body['seal_sha256']}")
            for side in ("long", "short"):
                print(f"  {side}: " + ", ".join(f"{p['ticker']}@{p.get('reference_close')}" for p in body[side]))
        elif a.action == "control":
            if not a.date:
                ap.error("control needs --date")
            body = picks.control(a.date)
            print(f"control sealed {body['sealed_at']}  sha256 {body['seal_sha256']}")
            for side in ("long", "short"):
                print(f"  {side}: " + ", ".join(c["ticker"] for c in body["control"][side]))
            print(f"  panel files on record: {len(body['panel_files'])}")
        else:
            if not a.date:
                ap.error("grade needs --date")
            print(json.dumps(picks.grade(a.date), indent=2, default=str))
        return
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
