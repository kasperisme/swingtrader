"""Run the autonomous researcher.

    python -m strategylab.autonomous.cli status          # what is wired up
    python -m strategylab.autonomous.cli run             # 24/7 until stopped
    python -m strategylab.autonomous.cli run --campaigns 1   # one campaign, then exit
    python -m strategylab.autonomous.cli report          # read the digest
    python -m strategylab.autonomous.cli publish --check  # can we reach Supabase?
    python -m strategylab.autonomous.cli publish --notes  # push research/*.md

Ctrl-C finishes the current campaign and stops cleanly rather than tearing down
mid-backtest.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from ..config import OUTPUT_ROOT, LabConfig, load_env
from ..data.prices import PriceStore
from ..data.universe import UniverseBuilder
from ..genome import default_genome
from ..validation import build_context
from .budget import DailyBudget, SearchBudget
from .daemon import Daemon
from .llm import Client
from .publish import ResearchPublisher


def _context(args, cfg: LabConfig):
    ub, st = UniverseBuilder(), PriceStore()
    ordered = [r["symbol"] for r in ub.membership("nyse_nasdaq", include_delisted=True)]
    cached = set(st.cached_symbols())
    syms = [s for s in ordered if s in cached]
    if args.limit:
        syms = syms[: args.limit]
    if not syms:
        raise SystemExit("no cached prices — run:  strategylab data sync")
    return build_context(cfg, syms, ub.sectors(syms))


def _cfg(args) -> LabConfig:
    cfg = LabConfig(run_id="autonomous")
    cfg.prefilter = args.prefilter
    cfg.search.proposals_per_iteration = args.batch
    if args.dev_start:
        cfg.splits.dev_start = args.dev_start
    if args.dev_end:
        cfg.splits.dev_end = args.dev_end
    return cfg


def cmd_status(args) -> int:
    load_env()
    c = Client(models=args.models.split(",") if args.models else None)
    st = c.status()
    print("Ollama")
    print(f"   reachable   : {st['reachable']}")
    print(f"   model chain : {' -> '.join(st['chain'])}")
    print(f"   installed   : {', '.join(st['installed']) or 'none'}")
    store = PriceStore()
    print(f"\nData\n   cached price series : {len(store.cached_symbols())}")
    root = Path(OUTPUT_ROOT / "autonomous")
    print(f"\nOutput\n   {root}")
    if (root / "report.md").exists():
        print(f"   report.md present ({(root / 'report.md').stat().st_size} bytes)")
    if not st["reachable"]:
        print("\n! Ollama is not reachable. Start it, or set OLLAMA_URL.")
        return 1
    return 0


def cmd_run(args) -> int:
    load_env()
    cfg = _cfg(args)
    client = Client(models=args.models.split(",") if args.models else None)
    if not client.api.available():
        raise SystemExit("Ollama is not reachable — start it or set OLLAMA_URL")
    print(f"models : {' -> '.join(client.models)}")
    ctx = _context(args, cfg)
    print(f"universe: {len(ctx.panel.symbols)} symbols, "
          f"{ctx.panel.shape[0]} sessions")
    if ctx.prefilter_result is not None:
        print(ctx.prefilter_result.summary())

    budget = SearchBudget(
        soft_trial_budget=args.soft_budget, hard_trial_budget=args.hard_budget,
        patience=args.patience, max_pbo=args.max_pbo,
        max_wall_clock_hours=args.max_hours)
    daily = DailyBudget(max_campaigns_per_day=args.campaigns_per_day)
    d = Daemon(cfg, ctx, search_budget=budget, daily=daily, client=client)
    print(f"\nstopping rules: plateau after {budget.patience} stale iterations · "
          f"PBO > {budget.max_pbo} · hard budget {budget.hard_trial_budget} trials · "
          f"{budget.max_wall_clock_hours}h per campaign")
    print(f"output: {d.root}\n")
    d.run(max_campaigns=args.campaigns, sleep_between=args.sleep)
    return 0


def cmd_report(args) -> int:
    p = Path(OUTPUT_ROOT / "autonomous" / "report.md")
    if not p.exists():
        print("no report yet — run the daemon first")
        return 1
    print(p.read_text())
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="strategylab.autonomous", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default="INFO")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--models", default=None,
                       help="comma-separated Ollama models, best first")
        p.add_argument("--limit", type=int, default=800)
        p.add_argument("--prefilter", default="minervini")
        p.add_argument("--batch", type=int, default=8)
        p.add_argument("--dev-start", default=None)
        p.add_argument("--dev-end", default=None)

    p = sub.add_parser("status", help="what is wired up")
    common(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("run", help="run campaigns until stopped")
    common(p)
    p.add_argument("--campaigns", type=int, default=None,
                   help="stop after N campaigns (default: run forever)")
    p.add_argument("--campaigns-per-day", type=int, default=6)
    p.add_argument("--soft-budget", type=int, default=60)
    p.add_argument("--hard-budget", type=int, default=150)
    p.add_argument("--patience", type=int, default=6)
    p.add_argument("--max-pbo", type=float, default=0.45)
    p.add_argument("--max-hours", type=float, default=8.0)
    p.add_argument("--sleep", type=float, default=60.0)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("publish", help="push the research record to Supabase")
    p.add_argument("--check", action="store_true",
                   help="verify connection + migration, write nothing")
    p.add_argument("--notes", action="store_true", help="publish research/*.md")
    p.add_argument("--notes-dir", default="")
    p.add_argument("--findings", action="store_true", help="publish the findings store")
    p.add_argument("--artifacts", action="store_true",
                   help="upload the files a write-up cites, or record why not")
    p.add_argument("--charts", action="store_true",
                   help="upload chart PNGs to Storage and catalogue them")
    p.add_argument("--backfill", action="store_true",
                   help="import output/runs/*/ledger.sqlite as historical campaigns")
    p.add_argument("--top", type=int, default=5,
                   help="strategies per run to publish (default 5 — publishing "
                        "every trial publishes the search, not the results)")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--all-findings", action="store_true",
                   help="include OBSERVED/REPLICATING (recorded, still not visible)")
    p.add_argument("--live", action="store_true",
                   help="set published=true — the note goes on the public site")
    p.add_argument("--kind", default="negative",
                   choices=["negative", "positive", "replication", "method"])
    p.add_argument("--tags", nargs="*", default=[])
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("report", help="print the latest digest")
    p.set_defaults(func=cmd_report)
    return ap


def cmd_publish(args) -> int:
    """Push the research record to Supabase.

    Publishing is deliberately conservative. `--check` verifies the connection
    and that the migration has been applied before anything is written, and a
    note is inserted with published=false unless --live is passed: a finding
    should be reviewed once by a human before it appears on a public site,
    because this lab's own history is that the first look is usually wrong.
    """
    pub = ResearchPublisher()
    ok, why = pub.ready()
    if not ok:
        print(f"not ready: {why}")
        return 1
    print("connected; research tables present")
    if args.check:
        return 0

    if args.notes:
        notes_dir = Path(args.notes_dir) if args.notes_dir else (
            Path(__file__).resolve().parents[2] / "research")
        files = sorted(notes_dir.glob("*.md"))
        if not files:
            print(f"no markdown in {notes_dir}")
            return 1
        for f in files:
            slug = pub.publish_note(f, published=args.live,
                                    result_kind=args.kind, tags=args.tags or [])
            state = "PUBLISHED" if args.live else "draft"
            print(f"  {state:9s} {slug:<50s} <- {f.name}")
        print(f"\n{len(files)} notes written."
              + ("" if args.live else "\nAll as drafts. Review them, then flip "
                 "published=true (or re-run with --live)."))

    if args.backfill:
        from .backfill import backfill_all
        cfg = LabConfig()
        res = backfill_all(pub, cfg, universe_size=args.limit or 0, top=args.top)
        for run_id, n in res.items():
            print(f"  {run_id:<28s} {n} strategies")
        print(f"\n{sum(res.values())} strategies from {len(res)} runs.")

    if args.charts:
        from .charts_publish import ChartPublisher
        cp = ChartPublisher(pub)
        ok, msg = cp.ensure_bucket()
        print(f"  storage: {msg}")
        if not ok:
            return 1
        runs_root = OUTPUT_ROOT / "runs"
        total = 0
        for run_dir in sorted(d for d in runs_root.glob("*") if (d / "charts").is_dir()):
            trials = None
            led = run_dir / "ledger.sqlite"
            if led.exists():
                from ..ledger import Ledger
                trials = Ledger(led).count(distinct=True)
            slugs = cp.publish_run_charts(run_dir, trials=trials, published=args.live)
            print(f"  {run_dir.name:<28s} {len(slugs)} charts (trials={trials})")
            total += len(slugs)
        flow = cp.publish_flow_charts(published=args.live)
        print(f"  {'flow investigation':<28s} {len(flow)} charts")
        total += len(flow)
        state = "PUBLISHED" if args.live else "drafts"
        print(f"\n{total} charts uploaded as {state}.")

    if args.artifacts:
        from .artifacts import NOTE_ARTIFACTS, ArtifactPublisher
        from .charts_publish import ChartPublisher
        ap = ArtifactPublisher(pub, ChartPublisher(pub))
        for slug in NOTE_ARTIFACTS:
            for line in ap.publish_for_note(slug):
                print(f"  {slug[:34]:<34s} {line}")

    if args.findings:
        from .findings import FindingStore
        store = FindingStore(OUTPUT_ROOT / "autonomous" / "findings.sqlite")
        n = pub.publish_findings(store, only_confirmed=not args.all_findings)
        print(f"{n} findings written "
              f"(visible on the site only where status=CONFIRMED)")
    pub.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
