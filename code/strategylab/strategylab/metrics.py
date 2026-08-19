"""Performance and overfitting statistics.

Ordinary performance metrics answer "how good did this look?". After a few
hundred searched configurations, that is the wrong question — the best-looking
result out of N trials is a *maximum of N noisy draws*, and its Sharpe is
biased upward by roughly sqrt(2 ln N) standard errors even when every strategy
is worthless.

So this module carries both:
  * descriptive stats (Sharpe, Sortino, drawdown, turnover, hit rate, …)
  * selection-bias corrections — PSR, the Deflated Sharpe Ratio, and PBO —
    that price in how hard the search looked before it found this.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

TRADING_DAYS = 252


# ----------------------------------------------------------------------
# Descriptive
# ----------------------------------------------------------------------
def sharpe(returns: np.ndarray, rf_annual: float = 0.0) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 20:
        return 0.0
    excess = r - rf_annual / TRADING_DAYS
    sd = excess.std(ddof=1)
    if sd <= 1e-12:
        return 0.0
    return float(excess.mean() / sd * math.sqrt(TRADING_DAYS))


def sortino(returns: np.ndarray, rf_annual: float = 0.0) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 20:
        return 0.0
    excess = r - rf_annual / TRADING_DAYS
    downside = excess[excess < 0]
    dd = downside.std(ddof=1) if downside.size > 2 else 0.0
    if dd <= 1e-12:
        return 0.0
    return float(excess.mean() / dd * math.sqrt(TRADING_DAYS))


def max_drawdown(equity: np.ndarray) -> float:
    e = np.asarray(equity, dtype=float)
    if e.size == 0:
        return 0.0
    peak = np.maximum.accumulate(e)
    dd = 1.0 - e / np.where(peak > 0, peak, np.nan)
    return float(np.nanmax(dd)) if np.isfinite(dd).any() else 0.0


def drawdown_duration(equity: np.ndarray) -> int:
    """Longest stretch, in sessions, spent below a prior peak. The metric that
    actually decides whether a strategy gets abandoned in practice."""
    e = np.asarray(equity, dtype=float)
    peak = np.maximum.accumulate(e)
    under = e < peak * (1 - 1e-9)
    longest = cur = 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    return int(longest)


def ulcer_index(equity: np.ndarray) -> float:
    e = np.asarray(equity, dtype=float)
    peak = np.maximum.accumulate(e)
    dd = (1.0 - e / np.where(peak > 0, peak, np.nan)) * 100.0
    dd = dd[np.isfinite(dd)]
    return float(np.sqrt((dd ** 2).mean())) if dd.size else 0.0


def cagr(equity: np.ndarray, n_days: int) -> float:
    e = np.asarray(equity, dtype=float)
    if e.size < 2 or e[0] <= 0 or e[-1] <= 0 or n_days <= 0:
        return 0.0
    years = n_days / TRADING_DAYS
    return float((e[-1] / e[0]) ** (1.0 / max(years, 1e-9)) - 1.0)


def tail_ratio(returns: np.ndarray) -> float:
    """|95th pct| / |5th pct|. Below 1 means the left tail dominates — a shape
    that survives in-sample and destroys accounts out of sample."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r) & (r != 0)]
    if r.size < 50:
        return 1.0
    lo = abs(np.percentile(r, 5))
    hi = abs(np.percentile(r, 95))
    return float(hi / lo) if lo > 1e-12 else 1.0


def turnover(trades: pd.DataFrame, equity: np.ndarray, n_days: int) -> float:
    """Annualised portfolio turnover, in multiples of capital."""
    if trades.empty or n_days <= 0:
        return 0.0
    traded = float((trades["shares"] * trades["entry_price"]).sum()) * 2.0
    avg_equity = float(np.nanmean(equity)) or 1.0
    years = n_days / TRADING_DAYS
    return traded / avg_equity / max(years, 1e-9)


def benchmark_stats(returns: np.ndarray, bench_returns: np.ndarray) -> dict:
    """Alpha, beta, information ratio and the t-stat of alpha.

    The t-stat is the one that matters for the acceptance gate: a strategy can
    post a fine Sharpe purely by being long a rising market, and alpha-t is
    what separates that from an actual edge."""
    r = np.asarray(returns, dtype=float)
    b = np.asarray(bench_returns, dtype=float)
    n = min(r.size, b.size)
    r, b = r[:n], b[:n]
    ok = np.isfinite(r) & np.isfinite(b)
    r, b = r[ok], b[ok]
    if r.size < 60 or b.std() <= 1e-12 or r.std() <= 1e-12:
        return {"alpha_annual": 0.0, "beta": 0.0, "alpha_t": 0.0,
                "information_ratio": 0.0, "correlation": 0.0}
    beta, alpha = np.polyfit(b, r, 1)
    resid = r - (alpha + beta * b)
    se = resid.std(ddof=2) / math.sqrt(r.size) if r.size > 2 else np.nan
    active = r - b
    ir = (active.mean() / active.std(ddof=1) * math.sqrt(TRADING_DAYS)
          if active.std(ddof=1) > 1e-12 else 0.0)
    return {
        "alpha_annual": float(alpha * TRADING_DAYS),
        "beta": float(beta),
        "alpha_t": float(alpha / se) if se and np.isfinite(se) and se > 0 else 0.0,
        "information_ratio": float(ir),
        "correlation": float(np.corrcoef(r, b)[0, 1]),
    }


# ----------------------------------------------------------------------
# Selection-bias corrections
# ----------------------------------------------------------------------
def probabilistic_sharpe(observed_sr: float, n_obs: int, skew: float, kurt: float,
                         benchmark_sr: float = 0.0) -> float:
    """P(true Sharpe > benchmark), adjusting for sample length and for the
    non-normality of the return distribution (Bailey & López de Prado).

    Sharpe assumes IID normal returns. Trading returns are neither: negative
    skew and fat tails both make a given Sharpe *less* trustworthy than the
    textbook standard error suggests, and PSR is what prices that in.
    """
    if n_obs < 30:
        return 0.0
    sr = observed_sr / math.sqrt(TRADING_DAYS)      # per-period
    bsr = benchmark_sr / math.sqrt(TRADING_DAYS)
    denom = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr ** 2
    if denom <= 0:
        return 0.0
    z = (sr - bsr) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return float(stats.norm.cdf(z))


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """Expected maximum Sharpe from `n_trials` independent worthless strategies.

    This is the bar a search has to clear just to be non-random. It grows with
    the number of trials, which is exactly why an unlogged search can never
    make an honest claim.
    """
    if n_trials <= 1 or sr_variance <= 0:
        return 0.0
    e = 0.5772156649015329  # Euler-Mascheroni
    n = float(n_trials)
    z1 = stats.norm.ppf(1.0 - 1.0 / n)
    z2 = stats.norm.ppf(1.0 - 1.0 / (n * math.e))
    return float(math.sqrt(sr_variance) * ((1.0 - e) * z1 + e * z2))


def deflated_sharpe(observed_sr: float, n_obs: int, skew: float, kurt: float,
                    n_trials: int, sr_variance: float) -> float:
    """PSR measured against the expected best-of-N benchmark instead of zero.

    Reading: DSR is the probability the strategy's true Sharpe is positive
    GIVEN that it is the winner of `n_trials` searched configurations. A DSR
    below ~0.95 means the result is indistinguishable from the luckiest draw.
    """
    sr0 = expected_max_sharpe(n_trials, sr_variance)
    return probabilistic_sharpe(observed_sr, n_obs, skew, kurt, benchmark_sr=sr0)


def min_track_record_length(observed_sr: float, skew: float, kurt: float,
                            target_sr: float = 0.0, confidence: float = 0.95) -> float:
    """Observations needed before the Sharpe is distinguishable from target."""
    sr = observed_sr / math.sqrt(TRADING_DAYS)
    tsr = target_sr / math.sqrt(TRADING_DAYS)
    if abs(sr - tsr) < 1e-9:
        return float("inf")
    z = stats.norm.ppf(confidence)
    num = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr ** 2
    return float(1.0 + num * (z / (sr - tsr)) ** 2)


def probability_of_backtest_overfitting(trial_returns: np.ndarray, n_splits: int = 10,
                                        rng: np.random.Generator | None = None,
                                        max_combinations: int = 200) -> float:
    """PBO via Combinatorially Symmetric Cross-Validation (Bailey et al.).

    Chop the timeline into S blocks, repeatedly split them into an in-sample
    and an out-of-sample half, pick the configuration that wins in-sample, and
    look at where it ranks out-of-sample. PBO is the share of splits where the
    in-sample winner lands in the bottom half out of sample.

    A PBO near 0.5 means selecting on backtest performance carries no
    information at all — the search is fitting noise.

    Parameters
    ----------
    trial_returns : (n_periods, n_trials) matrix of per-period returns, one
                    column per configuration evaluated on the SAME timeline.
    """
    import itertools

    R = np.asarray(trial_returns, dtype=float)
    if R.ndim != 2 or R.shape[1] < 2 or R.shape[0] < n_splits * 4:
        return float("nan")
    rng = rng or np.random.default_rng(0)

    n_periods, n_trials = R.shape
    block = n_periods // n_splits
    blocks = [R[i * block:(i + 1) * block] for i in range(n_splits)]

    half = n_splits // 2
    combos = list(itertools.combinations(range(n_splits), half))
    if len(combos) > max_combinations:
        idx = rng.choice(len(combos), size=max_combinations, replace=False)
        combos = [combos[i] for i in idx]

    logits = []
    for ins in combos:
        oos = [i for i in range(n_splits) if i not in ins]
        R_in = np.vstack([blocks[i] for i in ins])
        R_out = np.vstack([blocks[i] for i in oos])
        sr_in = np.array([sharpe(R_in[:, k]) for k in range(n_trials)])
        sr_out = np.array([sharpe(R_out[:, k]) for k in range(n_trials)])
        best = int(np.nanargmax(sr_in))
        # Relative rank of the in-sample winner within the OOS distribution.
        rank = (np.sum(sr_out <= sr_out[best]) ) / (n_trials + 1)
        rank = min(max(rank, 1e-6), 1 - 1e-6)
        logits.append(math.log(rank / (1 - rank)))

    logits = np.array(logits)
    return float(np.mean(logits <= 0.0))


# ----------------------------------------------------------------------
# Aggregate
# ----------------------------------------------------------------------
def summarize(result, rf_annual: float = 0.0,
              bench_returns: np.ndarray | None = None) -> dict:
    """Full metric block for one backtest."""
    r = result.returns
    eq = result.equity
    tf_all = result.trades_frame()
    # A volatility trim is a transaction, not a new position. Counting trims as
    # trades inflates n_trades, dilutes hit rate, and makes a risk overlay look
    # like a trading-frequency change. Costs and turnover still use every row.
    tf = tf_all[tf_all["exit_reason"] != "vol_trim"] if len(tf_all) else tf_all
    n_days = len(eq)
    active = r[np.isfinite(r)]
    nz = active[active != 0]

    sr = sharpe(r, rf_annual)
    # Skew and kurtosis go straight into PSR and the deflated Sharpe, so a
    # garbage moment there silently corrupts the selection-bias correction.
    # scipy warns about catastrophic cancellation on near-identical data; below
    # that threshold the moments are not estimable and the normal defaults are
    # the honest answer.
    _sd = float(nz.std(ddof=1)) if nz.size > 10 else 0.0
    _estimable = nz.size > 10 and _sd > 1e-9 and np.isfinite(_sd)
    skew = float(stats.skew(nz)) if _estimable else 0.0
    kurt = float(stats.kurtosis(nz, fisher=False)) if _estimable else 3.0
    if not np.isfinite(skew):
        skew = 0.0
    if not np.isfinite(kurt):
        kurt = 3.0

    out = {
        "sharpe": sr,
        "sortino": sortino(r, rf_annual),
        "cagr": cagr(eq, n_days),
        "vol_annual": float(active.std(ddof=1) * math.sqrt(TRADING_DAYS)) if active.size > 20 else 0.0,
        "max_drawdown": max_drawdown(eq),
        "drawdown_days": drawdown_duration(eq),
        "ulcer_index": ulcer_index(eq),
        "tail_ratio": tail_ratio(r),
        "skew": skew,
        "kurtosis": kurt,
        "n_days": n_days,
        "n_trades": int(len(tf)),
        "n_transactions": int(len(tf_all)),
        "n_vol_trims": int(len(tf_all) - len(tf)),
        "avg_exposure": float(np.nanmean(result.exposure)),
        "max_positions_used": float(np.nanmax(result.n_positions)) if n_days else 0.0,
        "turnover_annual": turnover(tf_all, eq, n_days),
        "final_equity": float(eq[-1]) if n_days else result.initial_equity,
        "total_return": float(eq[-1] / eq[0] - 1.0) if n_days and eq[0] > 0 else 0.0,
    }
    out["calmar"] = out["cagr"] / out["max_drawdown"] if out["max_drawdown"] > 1e-6 else 0.0
    out["psr"] = probabilistic_sharpe(sr, int(nz.size), skew, kurt)

    if len(tf):
        wins = tf[tf["pnl"] > 0]
        losses = tf[tf["pnl"] <= 0]
        gross_win = float(wins["pnl"].sum())
        gross_loss = float(-losses["pnl"].sum())
        out.update({
            "hit_rate": float(len(wins) / len(tf)),
            "avg_win_r": float(wins["r_multiple"].mean()) if len(wins) else 0.0,
            "avg_loss_r": float(losses["r_multiple"].mean()) if len(losses) else 0.0,
            "expectancy_r": float(tf["r_multiple"].mean()),
            "profit_factor": float(gross_win / gross_loss) if gross_loss > 1e-9 else float("inf"),
            "avg_hold_days": float(tf["hold_days"].mean()),
            "median_hold_days": float(tf["hold_days"].median()),
            "total_costs": float(tf_all["costs"].sum()),
            # Share of GROSS P&L eaten by frictions. Dividing by NET P&L (as is
            # tempting) explodes toward infinity exactly when the strategy is
            # marginal — which is precisely when the number needs to be readable.
            "cost_drag_pct_of_pnl": float(
                tf["costs"].sum() / (abs(tf["pnl"].sum()) + tf["costs"].sum())
            ) if (abs(tf["pnl"].sum()) + tf["costs"].sum()) > 1e-9 else 0.0,
            "capacity_truncated_pct": float(tf["truncated"].mean()),
        })
    else:
        out.update({"hit_rate": 0.0, "avg_win_r": 0.0, "avg_loss_r": 0.0,
                    "expectancy_r": 0.0, "profit_factor": 0.0, "avg_hold_days": 0.0,
                    "median_hold_days": 0.0, "total_costs": 0.0,
                    "cost_drag_pct_of_pnl": 0.0, "capacity_truncated_pct": 0.0})

    # ---- per-side attribution ------------------------------------------
    # Without this, a short sleeve that loses money is invisible behind a
    # portfolio-level Sharpe: the question "did the sleeve pay for itself?"
    # cannot be answered from aggregate statistics.
    if len(tf_all) and "side" in tf_all.columns:
        for label, side in (("long", 1), ("short", -1)):
            sub = tf_all[tf_all["side"] == side]
            out[f"n_{label}"] = int(len(sub))
            out[f"{label}_pnl"] = float(sub["pnl"].sum()) if len(sub) else 0.0
            out[f"{label}_expectancy_r"] = float(sub["r_multiple"].mean()) if len(sub) else 0.0
            out[f"{label}_hit_rate"] = float((sub["pnl"] > 0).mean()) if len(sub) else 0.0
        if "borrow_cost" in tf_all.columns:
            out["total_borrow_cost"] = float(tf_all["borrow_cost"].sum())
        gross = out.get("long_pnl", 0.0) + out.get("short_pnl", 0.0)
        out["short_pnl_share"] = (out.get("short_pnl", 0.0) / gross) if abs(gross) > 1e-9 else 0.0

    if bench_returns is not None:
        out.update(benchmark_stats(r, bench_returns))

    return out
