"""strategylab command line.

    strategylab data sync         download and cache adjusted prices
    strategylab data status       what is cached, and the survivorship note
    strategylab baseline          backtest the incumbent rules
    strategylab backtest          backtest one genome (file or default)
    strategylab investigate       diagnostics for one genome
    strategylab search            run the RL loop
    strategylab finalize          score the leader, open the vault, export
    strategylab signals           today's orders from a deployed strategy
    strategylab report            markdown run report
    strategylab space             dump the search space
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from .config import OUTPUT_ROOT, LabConfig, load_env
from .genome import Genome, default_genome, space_spec


def _log(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _cfg(args) -> LabConfig:
    cfg = LabConfig(run_id=getattr(args, "run", "default"))
    if getattr(args, "dev_start", None):
        cfg.splits.dev_start = args.dev_start
    if getattr(args, "dev_end", None):
        cfg.splits.dev_end = args.dev_end
    if getattr(args, "equity", None):
        cfg.initial_equity = args.equity
    if getattr(args, "prefilter", None):
        cfg.prefilter = args.prefilter
    return cfg


def _load_genome(path: str | None) -> Genome:
    if not path:
        return default_genome()
    p = Path(path)
    payload = json.loads(p.read_text())
    return Genome(payload.get("genome", payload))


def _universe(args, cfg: LabConfig, g: Genome):
    from .data.prices import PriceStore
    from .data.universe import UniverseBuilder

    ub = UniverseBuilder()
    # membership() preserves the source's own ordering (liquidity-ranked for
    # `liquid_mid_large`), so --limit takes the most tradable names rather than
    # everything starting with "A" — an alphabetical cap is a biased sample.
    ordered = [r["symbol"] for r in ub.membership(
        g["universe.source"], include_delisted=not args.no_delisted)]
    store = PriceStore()
    cached = set(store.cached_symbols())
    usable = [s for s in ordered if s in cached]
    if getattr(args, "limit", None):
        usable = usable[: args.limit]
    if not usable:
        raise SystemExit("No cached prices. Run:  strategylab data sync")
    return usable, ub


def _context(args, cfg: LabConfig, g: Genome):
    from .validation import build_context
    symbols, ub = _universe(args, cfg, g)
    ctx = build_context(cfg, symbols, ub.sectors(symbols),
                       use_fundamentals=g["gates.use_fundamentals"] or args.fundamentals,
                       use_news=g["gates.use_news"] or args.news,
                       news_lookback=int(g["gates.news_lookback_days"]))
    if ctx.prefilter_result is not None:
        print("\n" + ctx.prefilter_result.summary() + "\n")
    return ctx


# ----------------------------------------------------------------------
def cmd_data(args) -> int:
    from .data.news import NewsStore
    from .data.prices import PriceStore
    from .data.universe import UniverseBuilder

    cfg = _cfg(args)
    store = PriceStore()
    ub = UniverseBuilder()

    if args.action == "status":
        from .data.earnings import EarningsStore
        from .data.fundamentals import FundamentalsStore
        from .flow.etf_flow import ETFFlowStore

        cached = store.cached_symbols()
        print(f"cached price series : {len(cached)}")

        # Per-dataset coverage. A dataset that is silently incomplete does not
        # raise — it just drops names from the universe, which reads as "the
        # filter was strict" rather than "the data was missing".
        fs = FundamentalsStore()
        have_fund = sum(1 for s_ in cached if fs._path(s_).exists())
        es = EarningsStore()
        have_earn = sum(1 for s_ in cached if es._path(s_).exists())
        ef = ETFFlowStore()
        have_w = sum(1 for s_ in cached if ef._weight_path(s_).exists())
        n_flow = len(list(ef.flow_dir.glob("*.csv.gz")))
        # The consequence of each gap differs, and saying so is the point:
        # two of these silently shrink the universe, the third silently
        # weakens a filter without shrinking anything.
        consequences = {
            "fundamentals (PIT shares/EPS)":
                "no market cap -> name DROPPED from the universe",
            "ETF weight maps":
                "fails the ETF-ownership gate -> name DROPPED",
            "earnings dates (blackout)":
                "no earnings blackout applied for that name -> filter silently weaker",
        }
        for label, n in (("fundamentals (PIT shares/EPS)", have_fund),
                         ("ETF weight maps", have_w),
                         ("earnings dates (blackout)", have_earn)):
            pct = n / max(1, len(cached))
            flag = "" if pct > 0.95 else f"   <- {consequences[label]}"
            print(f"{label:<32}: {n}/{len(cached)} ({pct:.0%}){flag}")
        print(f"{'ETF daily flow series':<32}: {n_flow}")
        cov = ub.coverage_report()
        print(f"listed symbols      : {cov['listed']}")
        print(f"delisted symbols    : {cov['delisted']}")
        print(f"survivorship        : {'corrected' if cov['survivorship_corrected'] else 'BIASED'}")
        print(f"\n{cov['note']}")
        ns = NewsStore()
        c = ns.coverage()
        print(f"\nnews overlay        : {'%s .. %s' % c if c else 'not synced'}")
        return 0

    if args.action == "sync":
        symbols = ub.symbols(args.source, include_delisted=not args.no_delisted)
        if args.limit:
            symbols = symbols[: args.limit]
        symbols = sorted(set(symbols) | {"SPY", "QQQ"})
        print(f"syncing {len(symbols)} symbols "
              f"{cfg.splits.warmup_start} .. {cfg.splits.vault_end}")
        stats = store.sync(symbols, cfg.splits.warmup_start, cfg.splits.vault_end,
                           workers=args.workers, force=args.force)
        print(json.dumps(stats, indent=2))
        if args.fundamentals:
            from .data.fundamentals import FundamentalsStore
            print("syncing point-in-time fundamentals…")
            print(json.dumps(FundamentalsStore().ensure(symbols, workers=args.workers), indent=2))
        if args.news:
            print("syncing news overlay…")
            print(json.dumps(NewsStore().sync(), indent=2))
        return 0

    print("unknown data action")
    return 2


def cmd_backtest(args) -> int:
    from .investigate import investigate
    from .reward import compute_reward
    from .validation import evaluate

    cfg = _cfg(args)
    g = _load_genome(args.genome)
    ctx = _context(args, cfg, g)
    ev = evaluate(g, ctx, rung=args.rung)
    rw = compute_reward(ev, g, cfg)

    print(f"\ngenome {g.hash}   valid={ev.valid} {ev.reason}")
    print(f"reward {rw.value:+.3f}  (base {rw.base:+.3f}, penalties "
          f"{ {k: round(v, 3) for k, v in rw.penalties.items()} })")
    print("\nmetrics:")
    for k, v in sorted(ev.metrics.items()):
        print(f"  {k:<26} {v:.4f}" if isinstance(v, float) else f"  {k:<26} {v}")
    if ev.fold_metrics:
        print("\nfolds:")
        for f in ev.fold_metrics:
            print(f"  {f['fold']:<7} {f['start']}..{f['end']}  sharpe {f['sharpe']:+.2f}  "
                  f"ret {f['return']:+.1%}  dd {f['max_drawdown']:.1%}  n={f['n_trades']}")
    if args.investigate and ev.result:
        print("\ninvestigation:\n" + investigate(ev, g, ctx).brief(20))
    if args.out:
        Path(args.out).write_text(json.dumps(
            {"genome": dict(g), "metrics": ev.metrics, "folds": ev.fold_metrics,
             "reward": rw.to_dict()}, indent=2, default=str))
        print(f"\n→ {args.out}")
    return 0


def cmd_investigate(args) -> int:
    from .investigate import investigate
    from .validation import evaluate

    cfg = _cfg(args)
    g = _load_genome(args.genome)
    ctx = _context(args, cfg, g)
    ev = evaluate(g, ctx, rung=1)
    d = investigate(ev, g, ctx)
    if args.json:
        print(json.dumps(d.to_dict(), indent=2, default=str))
    else:
        print(d.brief(40))
        print("\ntables:")
        print(json.dumps(d.tables, indent=2, default=str)[:6000])
    return 0


def _load_seed(args) -> tuple[Genome | None, int, str]:
    """Resolve --seed-from / --seed-genome into (genome, inherited_trials, origin)."""
    if getattr(args, "seed_genome", None):
        path = Path(args.seed_genome)
        payload = json.loads(path.read_text())
        g = Genome(payload.get("genome", payload))
        inherited = int(payload.get("n_trials") or payload.get("inherited_trials") or 0)
        return g, inherited, f"file {path.name}"

    run = getattr(args, "seed_from", None)
    if not run:
        return None, 0, ""

    from .ledger import Ledger
    src = LabConfig(run_id=run).ledger_path
    if not src.exists():
        raise SystemExit(f"no ledger for run '{run}' at {src}")
    led = Ledger(src)
    best = led.best(n=1, rung=1)
    if not best:
        raise SystemExit(f"run '{run}' has no valid genome to seed from")
    g = Genome(json.loads(best[0]["genome_json"]))
    # Own trials plus whatever that run itself inherited — ancestry compounds.
    inherited = led.count(distinct=True) + led.inherited_trials()
    return g, inherited, f"run '{run}' (genome {g.hash})"


def cmd_search(args) -> int:
    from .ledger import Ledger
    from .loop import Lab
    from .report import run_report

    cfg = _cfg(args)
    cfg.search.proposals_per_iteration = args.batch
    seed, inherited, origin = _load_seed(args)
    g = seed or default_genome()
    ctx = _context(args, cfg, g)
    ledger = Ledger(cfg.ledger_path)
    lab = Lab(cfg, ctx, ledger, use_llm=not args.no_llm,
              seed_genome=seed, inherited_trials=inherited, seed_origin=origin)
    if seed is not None:
        print(f"Seeding from {origin}")
        print(f"  changes vs incumbent: {seed.describe_diff(default_genome())[:300]}")
        print(f"  inherited trial count: {inherited} — carried into the deflated "
              f"Sharpe so restarting cannot reset the selection-bias clock.\n")

    if lab.policy and not lab.policy.available:
        print("! ANTHROPIC_API_KEY not set — running with the non-LLM samplers only.\n")

    lab.run(args.iterations, on_iteration=_chart_hook(cfg, ledger, args))
    (cfg.run_dir / "report.md").write_text(run_report(cfg, ledger))
    print(f"\n→ {cfg.run_dir / 'report.md'}")
    print(f"→ {cfg.ledger_path}")
    if not args.no_charts:
        _render_charts(cfg, ledger, lab, ctx)
    print("\nNext:  strategylab finalize --run " + cfg.run_id)
    return 0


def _chart_hook(cfg, ledger, args):
    """Refresh the search charts every few iterations so a long run can be
    watched while it happens rather than only autopsied afterwards."""
    if args.no_charts:
        return None
    every = max(1, args.chart_every)

    def hook(rep):
        if rep.iteration % every:
            return
        try:
            from .charts import search_charts
            search_charts(cfg.ledger_path, cfg.run_dir / "charts")
        except Exception as exc:
            logging.getLogger(__name__).warning("chart refresh failed: %s", exc)
    return hook


def _render_charts(cfg, ledger, lab, ctx) -> None:
    """Search progress plus the leader's performance, as one HTML page."""
    from .charts import contact_sheet, performance_charts, search_charts
    from .validation import evaluate

    out = cfg.run_dir / "charts"
    print("\nRendering charts…")
    images = search_charts(cfg.ledger_path, out)

    if lab.elites:
        g, reward, ev = lab.elites[0]
        if ev is None or ev.result is None:
            ev = evaluate(g, ctx, rung=1)
        if ev.result is not None:
            i0, i1 = ctx.dev_range()
            images += performance_charts(
                ev.result, ev.metrics, out,
                bench_returns=ctx.bench_returns[i0:i1],
                fold_metrics=ev.fold_metrics,
                label=f"best genome {g.hash}")

    if images:
        sheet = contact_sheet(
            images, out / "report.html",
            f"strategylab — run {cfg.run_id}",
            f"{ledger.count(distinct=True)} configurations evaluated · "
            f"dev {cfg.splits.dev_start} to {cfg.splits.dev_end} · "
            f"{len(ctx.panel.symbols)} symbols")
        print(f"→ {sheet}   (open this)")
    for i in images:
        print(f"→ {i}")


def cmd_finalize(args) -> int:
    from .deploy import export
    from .ledger import Ledger
    from .loop import Lab
    from .report import run_report

    cfg = _cfg(args)
    g = default_genome()
    ctx = _context(args, cfg, g)
    ledger = Ledger(cfg.ledger_path)
    _check_universe_matches(ledger, ctx, args)
    lab = Lab(cfg, ctx, ledger, use_llm=False)
    final = lab.finalize(open_vault=not args.no_vault)

    if "error" in final:
        print(final["error"])
        return 1

    print(json.dumps({k: v for k, v in final.items()
                      if k not in {"genome", "operator_table", "diagnostics"}},
                     indent=2, default=str)[:8000])

    (cfg.run_dir / "report.md").write_text(run_report(cfg, ledger, final))
    if not args.no_charts:
        _render_charts(cfg, ledger, lab, ctx)
    if final.get("deployable") or args.force_export:
        out = export(cfg, Genome(final["genome"]), final)
        print(f"\n→ exported to {out}")
    else:
        print("\nNot deployable — nothing exported. "
              "Use --force-export to write the artifacts anyway.")
    return 0


def _check_universe_matches(ledger, ctx, args) -> None:
    """Refuse to judge a genome on a universe the search never used.

    Results are materially sensitive to how far down the liquidity curve the
    universe reaches. Finalising a run at a different `--limit` re-evaluates the
    winner against a different opportunity set and produces a verdict about a
    strategy nobody searched for — silently, and with an authoritative-looking
    gate table attached.
    """
    row = ledger.conn.execute(
        "SELECT payload FROM events WHERE kind='run_started' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        print("! This ledger predates universe recording — cannot verify that the "
              "universe matches the search. Re-run the search to get the guarantee.\n")
        return
    try:
        searched = int(json.loads(row[0]).get("universe_loaded", 0))
    except Exception:
        return
    loaded = len(ctx.panel.symbols)
    if searched and abs(loaded - searched) > max(2, 0.01 * searched):
        msg = (f"Universe mismatch: the search ran on {searched} symbols, this "
               f"finalize loaded {loaded}. The verdict would describe a strategy "
               f"that was never searched.")
        if not getattr(args, "allow_universe_mismatch", False):
            raise SystemExit(msg + f"\n  Fix: --limit {searched}   "
                                   "(or pass --allow-universe-mismatch if you mean it)")
        print(f"! {msg}\n")


def cmd_signals(args) -> int:
    from .deploy import live_signals

    cfg = _cfg(args)
    spec_path = Path(args.strategy or (cfg.deploy_dir / "strategy.json"))
    if not spec_path.exists():
        raise SystemExit(f"no deployed strategy at {spec_path}")
    g = Genome(json.loads(spec_path.read_text())["genome"])
    ctx = _context(args, cfg, g)
    df = live_signals(g, ctx, as_of=args.as_of, equity=cfg.initial_equity)
    if df.empty:
        print("No entries today.")
    else:
        print(df.to_string(index=False))
    return 0


def cmd_compare(args) -> int:
    """Every candidate on ONE footing — same universe, same window, same costs.

    Numbers quoted from different runs are not comparable: the cached universe
    grows as more symbols are synced, so `--limit 800` selects different names
    over time, and the same genome can read 0.464 in one run and 0.377 in
    another. This command re-evaluates everything together so the ranking means
    something.
    """
    import numpy as np
    from .factor import wml as W
    from .ledger import Ledger
    from .reward import compute_reward
    from .validation import evaluate

    cfg = _cfg(args)
    ctx = _context(args, cfg, default_genome())
    i0, i1 = ctx.dev_range()
    print(f"common footing: {len(ctx.panel.symbols)} symbols · "
          f"{cfg.splits.dev_start}..{cfg.splits.dev_end} · costs applied\n")

    candidates: dict[str, Genome] = {"incumbent NIS Momentum": default_genome()}
    for run in args.runs:
        path = LabConfig(run_id=run).ledger_path
        if not path.exists():
            print(f"  (skipping '{run}' — no ledger)")
            continue
        best = Ledger(path).best(n=1, rung=1)
        if best:
            candidates[f"{run} leader"] = Genome(json.loads(best[0]["genome_json"]))
    if args.genome:
        payload = json.loads(Path(args.genome).read_text())
        candidates[Path(args.genome).stem] = Genome(payload.get("genome", payload))

    hdr = (f"{'strategy':<38}{'Sharpe':>8}{'CAGR':>8}{'maxDD':>8}{'Calmar':>8}"
           f"{'trades':>8}{'expos':>7}{'alphaT':>8}{'reward':>9}")
    print(hdr + "\n" + "-" * len(hdr))

    curves: dict[str, np.ndarray] = {}
    for name, g in candidates.items():
        ev = evaluate(g, ctx, rung=1)
        rw = compute_reward(ev, g, cfg)
        m = ev.metrics
        print(f"{name:<38}{m.get('sharpe',0):>8.3f}{m.get('cagr',0):>8.1%}"
              f"{m.get('max_drawdown',0):>8.1%}{m.get('calmar',0):>8.2f}"
              f"{m.get('n_trades',0):>8}{m.get('avg_exposure',0):>7.0%}"
              f"{m.get('alpha_t',0):>8.2f}{rw.value:>+9.3f}")
        if ev.daily_returns is not None:
            curves[name] = ev.daily_returns

    if not args.no_factors:
        panel, bank = ctx.panel, ctx.bank
        dv = bank.get("dollar_volume_20d")
        elig = np.isfinite(panel.close) & (panel.close > 5.0) & (dv > 5e6)
        res = W.build_wml(panel, bank.get("momo_12m_1m"), elig, weights=dv, min_names=100)
        refs = {
            "WML long-short (after costs)": W.apply_costs(res, 13.0, 100.0).returns,
            "WML long leg only (after costs)":
                W.apply_costs(W.long_leg_only(res), 13.0, 0.0, 0.8).returns,
            "SPY buy-and-hold": ctx.bench_returns,
        }
        for name, series in refs.items():
            sub = W.WMLResult(panel.dates[i0:i1], series[i0:i1], res.long_returns[i0:i1],
                              res.short_returns[i0:i1], res.n_long[i0:i1],
                              res.n_short[i0:i1], [], name)
            st = sub.stats()
            calmar = (st["annual_return"] / st["max_drawdown"]
                      if st["max_drawdown"] > 1e-9 else 0.0)
            print(f"{name:<38}{st['sharpe']:>8.3f}{st['annual_return']:>8.1%}"
                  f"{st['max_drawdown']:>8.1%}{calmar:>8.2f}{'—':>8}{'100%':>7}"
                  f"{'—':>8}{'—':>9}")
            curves[name] = series[i0:i1]

    if not args.no_charts and curves:
        import matplotlib.pyplot as plt
        from .charts import GRID, INK, MUTED, SERIES, _note, _save
        out = OUTPUT_ROOT / "compare"
        dates = pd.DatetimeIndex(ctx.dates[i0:i1])
        fig, ax = plt.subplots(figsize=(11, 5.6))
        for k, (name, r) in enumerate(curves.items()):
            r = np.asarray(r)[: len(dates)]
            eq = np.cumprod(1.0 + np.nan_to_num(r))
            bench = "SPY" in name
            ax.plot(dates[: len(eq)], eq, lw=2.4 if bench else 1.7,
                    color=MUTED if bench else SERIES[k % len(SERIES)],
                    ls="--" if bench else "-", label=name)
        ax.set_yscale("log")
        ax.set_ylabel("growth of $1")
        ax.set_title("Every candidate, one universe, one window")
        _note(ax, "Log scale. The dashed line is buy-and-hold — anything below it "
                  "did not justify the effort of trading.")
        ax.legend(frameon=False, fontsize=8.5, loc="upper left")
        print(f"\n→ {_save(fig, out, 'compare_equity.png')}")
    return 0


def cmd_report(args) -> int:
    from .ledger import Ledger
    from .report import run_report

    cfg = _cfg(args)
    text = run_report(cfg, Ledger(cfg.ledger_path))
    (cfg.run_dir / "report.md").write_text(text)
    print(text)
    return 0


def cmd_space(args) -> int:
    spec = space_spec()
    if args.json:
        print(json.dumps(spec, indent=2))
        return 0
    for row in spec:
        rng = (f"[{row['min']}, {row['max']}]" if "min" in row
               else ("{" + ", ".join(map(str, row["options"])) + "}" if "options" in row
                     else "true/false"))
        cond = f"   (only when {row['active_when']})" if "active_when" in row else ""
        print(f"{row['key']:<34} {rng:<38} default={row['default']}{cond}")
        if row["doc"]:
            print(f"{'':<34} {row['doc']}")
    return 0


# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="strategylab", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default="INFO")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, universe=True):
        p.add_argument("--run", default="default", help="run id (namespaces the ledger)")
        if universe:
            p.add_argument("--limit", type=int, default=None, help="cap the symbol count")
            p.add_argument("--no-delisted", action="store_true",
                           help="exclude delisted names (reintroduces survivorship bias)")
            p.add_argument("--fundamentals", action="store_true")
            p.add_argument("--news", action="store_true")
        p.add_argument("--prefilter", default=None,
                       help="qualification screen applied before the strategy: "
                            "none | stage2 | minervini | minervini_strict | "
                            "accumulation | contraction | near_high, or an "
                            "ensemble like '2of3:stage2,accumulation,contraction'")
        p.add_argument("--dev-start", default=None)
        p.add_argument("--dev-end", default=None)
        p.add_argument("--equity", type=float, default=None)

    p = sub.add_parser("data", help="price / fundamentals / news cache")
    p.add_argument("action", choices=["sync", "status"])
    p.add_argument("--source", default="nyse_nasdaq",
                   choices=["nyse_nasdaq", "sp500", "liquid_mid_large"])
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-delisted", action="store_true")
    p.add_argument("--fundamentals", action="store_true")
    p.add_argument("--news", action="store_true")
    p.add_argument("--run", default="default")
    p.set_defaults(func=cmd_data)

    p = sub.add_parser("baseline", help="backtest the incumbent NIS Momentum rules")
    common(p)
    p.add_argument("--rung", type=int, default=1)
    p.add_argument("--investigate", action="store_true", default=True)
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_backtest, genome=None)

    p = sub.add_parser("backtest", help="backtest one genome")
    common(p)
    p.add_argument("--genome", default=None, help="path to strategy.json / genome json")
    p.add_argument("--rung", type=int, default=1)
    p.add_argument("--investigate", action="store_true")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("investigate", help="diagnostics for one genome")
    common(p)
    p.add_argument("--genome", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_investigate)

    p = sub.add_parser("search", help="run the reinforcement search loop")
    common(p)
    p.add_argument("--iterations", type=int, default=10)
    p.add_argument("--batch", type=int, default=8, help="proposals per iteration")
    p.add_argument("--no-llm", action="store_true", help="samplers only, no Claude")
    p.add_argument("--seed-from", default=None, metavar="RUN",
                   help="continue from another run's best genome (carries its trial count)")
    p.add_argument("--seed-genome", default=None, metavar="PATH",
                   help="continue from a strategy.json / genome json file")
    p.add_argument("--no-charts", action="store_true")
    p.add_argument("--chart-every", type=int, default=3,
                   help="refresh search charts every N iterations")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("finalize", help="score the leader, open the vault, export")
    common(p)
    p.add_argument("--no-vault", action="store_true", help="keep the vault sealed")
    p.add_argument("--force-export", action="store_true")
    p.add_argument("--allow-universe-mismatch", action="store_true",
                   help="finalize against a different universe than the search used")
    p.add_argument("--no-charts", action="store_true")
    p.set_defaults(func=cmd_finalize)

    p = sub.add_parser("signals", help="today's orders from a deployed strategy")
    common(p)
    p.add_argument("--strategy", default=None)
    p.add_argument("--as-of", default=None)
    p.set_defaults(func=cmd_signals)

    p = sub.add_parser("compare", help="rank every candidate on one footing")
    common(p)
    p.add_argument("runs", nargs="*", default=[], help="run ids to include")
    p.add_argument("--genome", default=None, help="also include a strategy.json")
    p.add_argument("--no-factors", action="store_true",
                   help="skip the WML / buy-and-hold reference portfolios")
    p.add_argument("--no-charts", action="store_true")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("report", help="markdown run report")
    common(p, universe=False)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("space", help="print the search space")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_space)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _log(args.log)
    load_env()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
