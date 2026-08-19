"""Evaluation protocol: data context, walk-forward folds, and the fidelity ladder.

Three ideas do the work here.

**One data context, many trials.** Prices, features and alternative data are
loaded and computed once for the whole timeline. A trial then costs a signal
build plus a simulation, which is what makes a few hundred experiments per hour
possible on a laptop.

**Folds measure stability, not fit.** Nothing is fitted on a training set — the
search itself is the estimator. So the dev period is run once end to end and
its daily returns are sliced into contiguous folds, with an embargo after each
boundary so a position spanning the join is not counted on both sides. What the
folds answer is "does this work in more than one regime, or once?".

**The vault is sealed.** `vault_start`..`vault_end` is never touched by the
search loop. It is opened once, by `evaluate_vault`, for a genome that has
already cleared every dev gate. Once opened for a given run, any further
searching against it is contaminated, and `ledger` records the event so that
cannot happen silently.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .backtest import BacktestResult, run_backtest
from .config import LabConfig
from .data.prices import Panel, PriceStore
from .features import FeatureBank, benchmark_series
from .genome import Genome
from .metrics import summarize
from .strategy import Signals, build_signals

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
@dataclass
class Fold:
    name: str
    start: np.datetime64
    end: np.datetime64
    i0: int
    i1: int


@dataclass
class Evaluation:
    genome_hash: str
    rung: int
    valid: bool
    reason: str = ""
    metrics: dict = field(default_factory=dict)
    fold_metrics: list[dict] = field(default_factory=list)
    daily_returns: np.ndarray | None = None
    dates: np.ndarray | None = None
    result: BacktestResult | None = None
    universe_size: int = 0


class DataContext:
    """Everything a trial reads. Built once per run."""

    def __init__(self, cfg: LabConfig, symbols: list[str], sectors: dict[str, str],
                 panel: Panel, bank: FeatureBank, bench_close: np.ndarray,
                 bench_returns: np.ndarray):
        self.cfg = cfg
        self.symbols = symbols
        self.panel = panel
        self.bank = bank
        self.sectors = [sectors.get(s, "Unknown") for s in panel.symbols]
        self.bench_close = bench_close
        self.bench_returns = bench_returns
        self.dates = panel.dates
        # Genome-independent, so it is computed once per data window and reused
        # by every trial — the cheapest possible thing to add to the pipeline.
        self.prefilter = None
        self.prefilter_result = None
        if getattr(cfg, "prefilter", "none") not in ("", "none", None):
            from .prefilter import build as _build_prefilter
            self.prefilter_result = _build_prefilter(cfg.prefilter, bank)
            self.prefilter = self.prefilter_result.mask
        self._folds: list[Fold] | None = None
        self._rung0_mask: np.ndarray | None = None
        # Signal construction runs over the whole timeline and is the dominant
        # per-trial cost. Rung 0 and rung 1 evaluate the SAME genome, so caching
        # by hash roughly halves the work for every promoted candidate.
        self._signal_cache: "OrderedDict[str, Signals]" = OrderedDict()
        # Only needs to span one iteration's rung-0 batch so the promoted
        # genomes hit on rung 1. Larger caches buy nothing and cost hundreds of
        # megabytes at a realistic universe size.
        self._signal_cache_limit = 10

    def signals_for(self, g: Genome) -> Signals:
        hit = self._signal_cache.get(g.hash)
        if hit is None:
            hit = build_signals(g, self.bank, self.sectors, self.bench_close,
                                prefilter=self.prefilter)
            if len(self._signal_cache) >= self._signal_cache_limit:
                self._signal_cache.popitem(last=False)
            self._signal_cache[g.hash] = hit
        else:
            self._signal_cache.move_to_end(g.hash)
        return hit

    # ---------------------------------------------------------- windows --
    def idx(self, day: str) -> int:
        return int(np.searchsorted(self.dates, np.datetime64(pd.Timestamp(day).date()), "left"))

    def dev_range(self) -> tuple[int, int]:
        s = self.cfg.splits
        return self.idx(s.dev_start), min(len(self.dates), self.idx(s.dev_end) + 1)

    def vault_range(self) -> tuple[int, int]:
        s = self.cfg.splits
        return self.idx(s.vault_start), min(len(self.dates), self.idx(s.vault_end) + 1)

    def holdout_range(self) -> tuple[int, int]:
        s = self.cfg.splits
        return (self.idx(s.holdout_start),
                min(len(self.dates), self.idx(s.holdout_end) + 1))

    def folds(self) -> list[Fold]:
        if self._folds is not None:
            return self._folds
        i0, i1 = self.dev_range()
        n = i1 - i0
        k = self.cfg.splits.n_folds
        emb = self.cfg.splits.embargo_days
        size = n // k
        out = []
        for f in range(k):
            a = i0 + f * size + (emb if f > 0 else 0)
            b = i0 + (f + 1) * size if f < k - 1 else i1
            if b - a < 40:
                continue
            out.append(Fold(f"fold{f + 1}", self.dates[a], self.dates[b - 1], a, b))
        self._folds = out
        return out

    # ------------------------------------------------------ rung-0 mask --
    def rung0_symbol_mask(self) -> np.ndarray:
        """The most liquid N names, chosen once so the cheap rung is a stable,
        comparable subsample rather than a different universe per trial."""
        if self._rung0_mask is None:
            cap = self.cfg.search.rung0_universe_cap
            dv = np.nanmedian(self.bank.get("dollar_volume_20d"), axis=0)
            order = np.argsort(-np.nan_to_num(dv, nan=-1.0))
            mask = np.zeros(len(self.panel.symbols), dtype=bool)
            mask[order[:cap]] = True
            self._rung0_mask = mask
        return self._rung0_mask


# ----------------------------------------------------------------------
def _slice_signals(sig: Signals, i0: int, i1: int, sym_mask: np.ndarray | None) -> Signals:
    cols = slice(None) if sym_mask is None else np.flatnonzero(sym_mask)
    def cut(a):
        return a[i0:i1, cols] if a.ndim == 2 else a[i0:i1]
    return Signals(
        eligible=cut(sig.eligible), trigger=cut(sig.trigger), score=cut(sig.score),
        short_eligible=cut(sig.short_eligible), short_trigger=cut(sig.short_trigger),
        short_score=cut(sig.short_score),
        regime_ok=sig.regime_ok[i0:i1], atr=cut(sig.atr), stop_ma=cut(sig.stop_ma),
        exit_ma=cut(sig.exit_ma), gap_pct=cut(sig.gap_pct),
        gate_pass_counts=sig.gate_pass_counts,
        n_days=i1 - i0, n_symbols=(sig.n_symbols if sym_mask is None else int(sym_mask.sum())),
    )


def _run_window(g: Genome, ctx: DataContext, i0: int, i1: int,
                sym_mask: np.ndarray | None) -> tuple[BacktestResult, int]:
    sig = ctx.signals_for(g)
    sub_sig = _slice_signals(sig, i0, i1, sym_mask)

    panel = ctx.panel
    if sym_mask is not None:
        cols = np.flatnonzero(sym_mask)
        panel = Panel(panel.dates[i0:i1], [panel.symbols[j] for j in cols],
                      panel.open[i0:i1][:, cols], panel.high[i0:i1][:, cols],
                      panel.low[i0:i1][:, cols], panel.close[i0:i1][:, cols],
                      panel.volume[i0:i1][:, cols])
        sectors = [ctx.sectors[j] for j in cols]
        rs = ctx.bank.get("rs_rank")[i0:i1][:, cols]
        adr = ctx.bank.get("adr_pct", length=20)[i0:i1][:, cols]
        dv = ctx.bank.get("dollar_volume_20d")[i0:i1][:, cols]
    else:
        panel = panel.slice_dates(panel.dates[i0], panel.dates[i1 - 1])
        sectors = ctx.sectors
        rs = ctx.bank.get("rs_rank")[i0:i1]
        adr = ctx.bank.get("adr_pct", length=20)[i0:i1]
        dv = ctx.bank.get("dollar_volume_20d")[i0:i1]

    res = run_backtest(g, panel, sub_sig, sectors, ctx.cfg,
                       rs_rank=rs, adr=adr, dollar_volume_20d=dv)
    return res, len(panel.symbols)


# ----------------------------------------------------------------------
def _overlay_available(g: Genome, ctx: DataContext, i0: int, i1: int) -> str:
    """Reject a genome whose overlay data is absent or empty in this window.

    Without this check a genome that switches on the fundamentals or news gate
    is silently evaluated with that gate doing nothing — so the search would
    credit the overlay for a result it had no part in, and could "discover"
    that turning it on is free. Unavailable is an honest INVALID, not a pass.
    """
    for switch, keys, label in (
        ("gates.use_fundamentals", ("eps_yoy", "rev_yoy", "beat_streak"), "fundamentals"),
        ("gates.use_news", ("news_sentiment", "news_articles"), "news-impact"),
    ):
        if not g[switch]:
            continue
        present = [k for k in keys if k in ctx.bank.extra]
        if not present:
            return f"{label} overlay requested but not loaded"
        window = ctx.bank.extra[present[0]][i0:i1]
        if not np.isfinite(window).any():
            return f"{label} overlay has no data in this evaluation window"
    return ""


def evaluate(g: Genome, ctx: DataContext, rung: int = 1) -> Evaluation:
    """Score a genome on the DEV period. Rung 0 is the cheap screening pass."""
    cfg = ctx.cfg
    folds = ctx.folds()

    if rung == 0:
        span = folds[-max(1, cfg.search.rung0_folds):]
        i0, i1 = span[0].i0, span[-1].i1
        mask = ctx.rung0_symbol_mask()
    else:
        i0, i1 = ctx.dev_range()
        mask = None

    unavailable = _overlay_available(g, ctx, i0, i1)
    if unavailable:
        return Evaluation(g.hash, rung, False, unavailable)

    try:
        res, uni = _run_window(g, ctx, i0, i1, mask)
    except Exception as exc:            # a pathological genome must not kill the run
        log.warning("evaluation failed for %s: %s", g.hash, exc)
        return Evaluation(g.hash, rung, False, f"error: {exc}")

    bench = ctx.bench_returns[i0:i1]
    m = summarize(res, cfg.risk_free_annual, bench)
    ev = Evaluation(g.hash, rung, True, metrics=m, daily_returns=res.returns,
                    dates=ctx.dates[i0:i1], result=res, universe_size=uni)

    if rung >= 1:
        for f in folds:
            a, b = f.i0 - i0, f.i1 - i0
            if a < 0 or b > len(res.returns):
                continue
            sub = res.returns[a:b]
            tf = res.trades_frame()
            n_tr = 0
            if len(tf):
                n_tr = int(((tf["entry_idx"] >= a) & (tf["entry_idx"] < b)).sum())
            from .metrics import max_drawdown, sharpe
            sub_eq = np.cumprod(1.0 + sub)
            ev.fold_metrics.append({
                "fold": f.name,
                "start": str(pd.Timestamp(f.start).date()),
                "end": str(pd.Timestamp(f.end).date()),
                "sharpe": sharpe(sub, cfg.risk_free_annual),
                "return": float(sub_eq[-1] - 1.0) if sub.size else 0.0,
                "max_drawdown": max_drawdown(sub_eq),
                "n_trades": n_tr,
                "days": int(sub.size),
            })

    ok, why = _validity(ev, cfg, rung)
    ev.valid, ev.reason = ok, why
    return ev


def _validity(ev: Evaluation, cfg: LabConfig, rung: int) -> tuple[bool, str]:
    """Hard feasibility checks — separate from the reward.

    These are not "bad scores", they are "this is not a strategy": too few
    trades to say anything, no capital deployed, or a fold that would have
    ended the account. Encoding them as reward penalties would let the search
    trade them off against return; as validity checks it cannot.
    """
    r = cfg.reward
    m = ev.metrics
    # Rung 0 sees a fraction of the timeline and a capped universe, so the
    # trade-count floor is scaled to match rather than rejecting everything.
    scale = 0.25 if rung == 0 else 1.0
    if m.get("n_trades", 0) < r.min_trades * scale:
        return False, f"too few trades ({m.get('n_trades', 0)})"
    if m.get("avg_exposure", 0.0) < r.min_exposure:
        return False, f"exposure too low ({m.get('avg_exposure', 0):.1%})"
    if m.get("final_equity", 0.0) <= 0:
        return False, "account ruined"
    if rung >= 1:
        if any(f["max_drawdown"] > r.max_single_fold_dd for f in ev.fold_metrics):
            return False, "a fold breached the drawdown limit"
        thin = [f for f in ev.fold_metrics if f["n_trades"] < r.min_trades_per_fold]
        if len(thin) > len(ev.fold_metrics) // 2:
            return False, "most folds have too few trades to measure"
    return True, ""


def evaluate_holdout(g: Genome, ctx: DataContext, ledger=None,
                     note: str = "") -> Evaluation:
    """Score a genome on the earlier, never-searched period.

    Folds are computed over the holdout window itself, so regime stability
    inside it can be read directly — the point of this window is that it
    contains crises the dev decade does not.

    If a ledger is supplied the use is recorded. That is not bookkeeping: a
    holdout consulted once is evidence, consulted ten times it is a training
    set, and the only defence is counting.
    """
    i0, i1 = ctx.holdout_range()
    if i1 - i0 < 250:
        return Evaluation(g.hash, 3, False, "holdout window has too little data")
    unavailable = _overlay_available(g, ctx, i0, i1)
    if unavailable:
        return Evaluation(g.hash, 3, False, unavailable)
    try:
        res, uni = _run_window(g, ctx, i0, i1, None)
    except Exception as exc:
        return Evaluation(g.hash, 3, False, f"error: {exc}")

    bench = ctx.bench_returns[i0:i1]
    m = summarize(res, ctx.cfg.risk_free_annual, bench)
    ev = Evaluation(g.hash, 3, True, metrics=m, daily_returns=res.returns,
                    dates=ctx.dates[i0:i1], result=res, universe_size=uni)

    # Fold the holdout on its own timeline.
    n = i1 - i0
    k = max(2, ctx.cfg.splits.n_folds)
    size = n // k
    from .metrics import max_drawdown as _mdd, sharpe as _sh
    for f in range(k):
        a = f * size + (ctx.cfg.splits.embargo_days if f else 0)
        b = (f + 1) * size if f < k - 1 else n
        if b - a < 40:
            continue
        sub = res.returns[a:b]
        ev.fold_metrics.append({
            "fold": f"h{f + 1}",
            "start": str(pd.Timestamp(ctx.dates[i0 + a]).date()),
            "end": str(pd.Timestamp(ctx.dates[i0 + b - 1]).date()),
            "sharpe": _sh(sub, ctx.cfg.risk_free_annual),
            "return": float(np.cumprod(1.0 + sub)[-1] - 1.0) if sub.size else 0.0,
            "max_drawdown": _mdd(np.cumprod(1.0 + sub)),
            "n_trades": 0, "days": int(sub.size),
        })
    ev.valid = m.get("n_trades", 0) >= 20
    if not ev.valid:
        ev.reason = "too few holdout trades to judge"
    if ledger is not None:
        ledger.log_event("holdout_used", {
            "genome_hash": g.hash, "note": note,
            "window": [ctx.cfg.splits.holdout_start, ctx.cfg.splits.holdout_end],
            "sharpe": m.get("sharpe"), "n_trades": m.get("n_trades"),
        })
    return ev


def evaluate_vault(g: Genome, ctx: DataContext) -> Evaluation:
    """Open the sealed period. Call once, for one genome, at the very end."""
    i0, i1 = ctx.vault_range()
    if i1 - i0 < 60:
        return Evaluation(g.hash, 2, False, "vault window has too little data")
    unavailable = _overlay_available(g, ctx, i0, i1)
    if unavailable:
        return Evaluation(g.hash, 2, False, unavailable)
    try:
        res, uni = _run_window(g, ctx, i0, i1, None)
    except Exception as exc:
        return Evaluation(g.hash, 2, False, f"error: {exc}")
    bench = ctx.bench_returns[i0:i1]
    m = summarize(res, ctx.cfg.risk_free_annual, bench)
    ev = Evaluation(g.hash, 2, True, metrics=m, daily_returns=res.returns,
                    dates=ctx.dates[i0:i1], result=res, universe_size=uni)
    ev.valid = m.get("n_trades", 0) >= 10
    if not ev.valid:
        ev.reason = "too few vault trades to judge"
    return ev


# ----------------------------------------------------------------------
def build_context(cfg: LabConfig, symbols: list[str], sectors: dict[str, str],
                  use_fundamentals: bool = False, use_news: bool = False,
                  news_lookback: int = 10) -> DataContext:
    """Load prices, compute the shared feature bank, attach optional overlays."""
    store = PriceStore()
    s = cfg.splits
    panel = store.build_panel(symbols, s.warmup_start, s.vault_end)
    log.info("panel: %d sessions x %d symbols (%s .. %s)", panel.shape[0], panel.shape[1],
             panel.dates[0], panel.dates[-1])

    bench_close = benchmark_series(store, cfg.benchmark, panel.dates)
    if not np.isfinite(bench_close).any():
        # Without the benchmark, the regime filter, the RS line and every
        # alpha/beta statistic silently degrade to no-ops — the strategy would
        # be evaluated as something other than what the genome describes.
        raise RuntimeError(
            f"No cached price history for the benchmark `{cfg.benchmark}`. "
            f"Run: strategylab data sync  (it always includes SPY and QQQ)."
        )
    bench_ret = np.zeros(len(bench_close))
    bench_ret[1:] = bench_close[1:] / np.where(bench_close[:-1] > 0, bench_close[:-1], np.nan) - 1.0
    bench_ret = np.nan_to_num(bench_ret, nan=0.0)

    bank = FeatureBank(panel, bench_close)

    if use_fundamentals:
        from .data.fundamentals import FundamentalsStore
        fs = FundamentalsStore()
        bank.extra.update(fs.align(panel.symbols, panel.dates))
        log.info("fundamentals overlay attached")

    if use_news:
        from .data.news import NewsStore
        ns = NewsStore()
        bank.extra.update(ns.align(panel.symbols, panel.dates, news_lookback))
        cov = ns.coverage()
        if cov:
            log.info("news overlay attached, coverage %s .. %s", *cov)

    return DataContext(cfg, symbols, sectors, panel, bank, bench_close, bench_ret)
