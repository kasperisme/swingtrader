"""Hold the whole screen — the benchmark every strategy on this universe must beat.

Three studies now point the same way: the breakout trigger underperforms a
random entry in the momentum universe, no conditioner sorts expectancy, and base
structure does not separate triggers. The implied alternative is to stop timing
anything and simply own what the screen qualifies.

That is a portfolio question, not a signal question, so it is simulated as a
portfolio: equal weight across every qualifying name, rebalanced on a schedule,
weights drifting with returns in between, costs charged on realised turnover,
and cash whenever the screen is empty. The cash leg is the interesting part —
the trend template stops qualifying names in a bear market, so the book
de-risks on its own without any regime rule bolted on.

Honesty notes that bear directly on the result:

  * **Cash earns nothing here.** Over 2004-2026 that is materially unfair to a
    strategy that is often partly in cash; the number reported is therefore a
    floor, not a best estimate.
  * **A delisted name is held at its last print.** Without delisting reasons the
    alternative is to guess, and this assumption is the optimistic one.
  * **Survivorship is the dominant caveat** and it is quantified below rather
    than waved at, because a momentum screen in a survivorship-biased panel is
    exactly the setup that manufactures a fake result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

log = logging.getLogger(__name__)

TRADING_DAYS = 252


@dataclass
class HoldSpec:
    rebalance: str = "M"                 # "W" | "M" | "Q"
    cost_bps_per_side: float = 13.0
    max_weight: float = 1.0              # 1.0 = pure equal weight, no cap
    cash_annual: float = 0.0             # deliberately conservative
    min_names: int = 1
    # Scale exposure by how many names currently qualify, against a TRAILING
    # median of that count. The screen's breadth collapses in a bear market —
    # median 63 names in 2008 and 26 in 2009 against 206 overall — and a rule
    # that goes fully invested whenever one name qualifies throws away exactly
    # the information the screen is providing. The trailing median is used, not
    # a full-sample one, so the calibration is point-in-time.
    breadth_scaled: bool = False
    breadth_window: int = 252
    # --- optional signal tilt -------------------------------------------
    # "none" | "top_half" (hold only the better half) | "rank_weight"
    # (weight proportional to cross-sectional rank).
    #
    # Names with no signal are given the MIDDLE rank, not dropped. On the news
    # overlay 62% of the universe carries no article on a given day, and
    # dropping them would silently turn a tilt into a different, much smaller
    # universe — so the comparison would no longer be paired and the P&L
    # difference would measure the universe change rather than the tilt.
    tilt_mode: str = "none"
    # --- concentration ---------------------------------------------------
    # Hold only the best `top_n` names by score. 0 = hold everything that
    # qualifies. `hysteresis_mult` keeps an incumbent as long as it is still
    # inside the top (top_n * mult) — without it a one-stock book churns every
    # time two names swap places, and a full round trip on 100% of capital is
    # 26bp a switch.
    top_n: int = 0
    hysteresis_mult: float = 2.0


def _rebalance_days(dates: np.ndarray, freq: str) -> np.ndarray:
    """Sessions on which the book is allowed to change.

    "D" means evaluate every session — the book reconsiders its holding daily and
    switches the moment a better candidate appears. That is a different strategy
    from monthly review, not a parameter tweak: the switch rule and the review
    frequency together decide how much of the ranking's movement is noise the
    book pays to chase.
    """
    idx = pd.DatetimeIndex(dates)
    if freq.upper() == "D":
        return np.arange(len(idx))
    s = pd.Series(np.arange(len(idx)), index=idx)
    return np.sort(s.groupby(idx.to_period(freq)).max().to_numpy())


def _tilt_weights(picks: np.ndarray, sig_row: np.ndarray, mode: str) -> np.ndarray:
    """Relative weights over `picks` under a tilt. Sums to 1.

    The median is taken over names that ACTUALLY HAVE a signal, not over the
    whole cross-section. With the news overlay 62% of the universe carries no
    article on a given day; giving those the middle rank and then cutting at the
    overall median makes the median equal to that middle rank, so `>= median`
    keeps everyone and the tilt becomes a no-op. It did: 13 of 15 months came
    back as exactly zero difference, which read as "the tilt does not help"
    when the truth was "the tilt never happened".

    So `top_half` now drops the weaker half OF THE NAMES WITH NEWS and holds the
    rest, which keeps "no news is not bad news" while still being a real tilt.
    """
    k = picks.size
    if mode == "none" or k < 4:
        return np.full(k, 1.0 / k)
    v = sig_row[picks].astype(float)
    known = np.isfinite(v)
    if known.sum() < 4:
        return np.full(k, 1.0 / k)

    from scipy import stats as _st
    r = np.full(k, 0.5)
    r[known] = _st.rankdata(v[known]) / (known.sum() + 1.0)

    if mode == "top_half":
        w = np.ones(k)
        cut = np.median(r[known])
        w[known & (r < cut)] = 0.0          # drop the weak half of the covered set
    elif mode == "rank_weight":
        w = r
    elif mode == "inverse":
        # Weight inversely to the signal — for a RISK signal this equalises each
        # name's risk contribution instead of removing names. That distinction
        # is the whole point: filtering on predicted volatility cut return
        # faster than it cut risk, because it threw away diversification.
        # Sizing keeps every name and only changes how much of each is held.
        v2 = np.where(np.isfinite(v) & (v > 0), v, np.nan)
        med = np.nanmedian(v2) if np.isfinite(v2).any() else 1.0
        v2 = np.where(np.isfinite(v2), v2, med)
        w = 1.0 / np.maximum(v2, 1e-6)
        # Cap the ratio so one very quiet name cannot become the whole book.
        w = np.minimum(w, 5.0 * np.median(w))
    else:
        raise ValueError(f"unknown tilt_mode {mode!r}")
    tot = w.sum()
    return w / tot if tot > 0 else np.full(k, 1.0 / k)


def _select_top(picks: np.ndarray, sig_row: np.ndarray, held: np.ndarray,
                spec: HoldSpec) -> np.ndarray:
    """The `top_n` names by score, with the incumbent given the benefit of the doubt.

    Ranking is descending on the score; names with no score cannot be selected
    at all, because "hold the best" needs a best. An incumbent is retained while
    it stays inside the top `top_n * hysteresis_mult`, which is what stops the
    book trading itself to death on rank noise.
    """
    if spec.top_n <= 0 or picks.size <= spec.top_n:
        return picks
    v = sig_row[picks].astype(float)
    ok = np.isfinite(v)
    if ok.sum() < spec.top_n:
        return picks[:spec.top_n]
    cand = picks[ok]
    order = np.argsort(-v[ok], kind="stable")
    ranked = cand[order]

    keep_band = ranked[:max(spec.top_n, int(spec.top_n * spec.hysteresis_mult))]
    incumbents = [j for j in held if j in set(keep_band.tolist())]
    out = list(incumbents[:spec.top_n])
    for j in ranked:
        if len(out) >= spec.top_n:
            break
        if j not in out:
            out.append(int(j))
    return np.array(out, dtype=int)


def run_hold(panel, mask: np.ndarray, spec: HoldSpec, start: int = 0,
             tilt_signal: np.ndarray | None = None,
             score: np.ndarray | None = None):
    """Equal-weight the qualifying set, rebalanced on `spec.rebalance`.

    Returns (daily portfolio return series, diagnostics). Signals are read on
    the close of day t and executed at the open of t+1, so `ret[k]` is the
    return from open k to open k+1 earned by weights set on close k-1.
    """
    open_ = panel.open
    n, m = open_.shape
    with np.errstate(invalid="ignore", divide="ignore"):
        R = np.vstack([open_[1:] / open_[:-1] - 1.0, np.full((1, m), np.nan)])
    R = np.where(np.isfinite(R), R, 0.0)

    rebal = set(_rebalance_days(panel.dates, spec.rebalance).tolist())
    counts_all = mask.sum(axis=1).astype(float)
    norm = (pd.Series(counts_all).rolling(spec.breadth_window, min_periods=60)
            .median().shift(1).to_numpy())
    w = np.zeros(m)
    daily = np.zeros(n)
    exposure = np.zeros(n)
    counts = np.zeros(n, dtype=int)
    turnover_total = 0.0
    tilt_rebalances = tilt_effective = 0
    holdings_log: list[tuple[int, tuple]] = []
    switches = 0
    cash_daily = spec.cash_annual / TRADING_DAYS

    for k in range(max(1, start), n - 1):
        t = k - 1
        if t in rebal:
            picks = np.flatnonzero(mask[t] & np.isfinite(open_[k]))
            if spec.top_n > 0 and picks.size:
                sig = score if score is not None else tilt_signal
                if sig is None:
                    raise ValueError("top_n requires a score matrix")
                picks = _select_top(picks, sig[t], np.flatnonzero(w > 0), spec)
            target = np.zeros(m)
            if picks.size >= spec.min_names:
                gross = 1.0
                if spec.breadth_scaled and np.isfinite(norm[t]) and norm[t] > 0:
                    gross = float(min(1.0, picks.size / norm[t]))
                flat = np.full(picks.size, 1.0 / picks.size)
                rel = (_tilt_weights(picks, tilt_signal[t], spec.tilt_mode)
                       if (tilt_signal is not None and spec.tilt_mode != "none")
                       else flat)
                if spec.tilt_mode != "none":
                    tilt_rebalances += 1
                    if not np.allclose(rel, flat):
                        tilt_effective += 1
                target[picks] = gross * rel
                if spec.top_n > 0:
                    cur = tuple(sorted(picks.tolist()))
                    if not holdings_log or holdings_log[-1][1] != cur:
                        switches += 1
                        holdings_log.append((int(k), cur))
                if spec.max_weight < 1.0:
                    target = np.minimum(target, spec.max_weight)
            turn = float(np.abs(target - w).sum())
            turnover_total += turn
            daily[k] -= turn * spec.cost_bps_per_side * 1e-4
            w = target
        counts[k] = int((w > 0).sum())
        invested = float(w.sum())
        exposure[k] = invested
        daily[k] += float(w @ R[k]) + (1.0 - invested) * cash_daily
        # Weights drift with the market until the next rebalance.
        grown = w * (1.0 + R[k])
        tot = grown.sum() + (1.0 - invested)
        if tot > 0:
            w = grown / tot

    eq = np.cumprod(1.0 + daily[:n - 1])
    diag = {"rebalances": len(rebal), "turnover_total": turnover_total,
            "worst_12m": float(np.min([eq[i + 252] / eq[i] - 1.0
                                       for i in range(0, max(1, len(eq) - 252), 21)]))
            if len(eq) > 300 else None,
            "avg_exposure": float(exposure[start:n - 1].mean()),
            "median_names": int(np.median(counts[counts > 0])) if (counts > 0).any() else 0,
            "annual_turnover": float(turnover_total / max(1e-9, (n - start) / TRADING_DAYS)),
            # A tilt that never changes the weights produces a perfect null, and
            # that null is about the tilt construction, not the signal.
            "tilt_rebalances": tilt_rebalances,
            "tilt_effective_share": (tilt_effective / tilt_rebalances
                                     if tilt_rebalances else None),
            # What the book actually DID, not what it was configured to do.
            "switches": switches,
            "switches_per_year": (switches / max(1e-9, (n - start) / TRADING_DAYS)
                                  if spec.top_n > 0 else None),
            "median_hold_days": (float(np.median(np.diff([h[0] for h in holdings_log])))
                                 if len(holdings_log) > 2 else None),
            "holdings_log": holdings_log[:400]}
    return daily[:n - 1], diag


def buy_and_hold(panel, symbol: str = "SPY", start: int = 0) -> np.ndarray:
    j = panel.symbols.index(symbol)
    o = panel.open[:, j]
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.append(o[1:] / o[:-1] - 1.0, np.nan)
    return np.where(np.isfinite(r), r, 0.0)[:len(o) - 1]


def stats_of(r: np.ndarray, bench: np.ndarray | None = None) -> dict:
    r = np.asarray(r, dtype=float)
    eq = np.cumprod(1.0 + r)
    years = len(r) / TRADING_DAYS
    cagr = float(eq[-1] ** (1 / years) - 1.0) if years > 0 and eq[-1] > 0 else float("nan")
    vol = float(r.std(ddof=1) * np.sqrt(TRADING_DAYS))
    sharpe = float(r.mean() / r.std(ddof=1) * np.sqrt(TRADING_DAYS)) if r.std(ddof=1) > 0 else float("nan")
    peak = np.maximum.accumulate(eq)
    dd = float((eq / peak - 1.0).min())
    out = {"total_return": float(eq[-1] - 1.0), "cagr": cagr, "vol": vol,
           "sharpe": sharpe, "max_drawdown": dd, "years": float(years)}
    if bench is not None:
        b = np.asarray(bench, dtype=float)[:len(r)]
        cov = np.cov(r, b)
        beta = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] > 0 else float("nan")
        active = r - b
        te = float(active.std(ddof=1) * np.sqrt(TRADING_DAYS))
        out |= {
            "beta": beta,
            "information_ratio": float(active.mean() / active.std(ddof=1)
                                       * np.sqrt(TRADING_DAYS)) if active.std(ddof=1) > 0 else float("nan"),
            "tracking_error": te,
        }
        # Alpha and its t-stat, Newey-West at 21 lags for daily overlap.
        X = np.column_stack([np.ones(len(r)), b])
        coef, *_ = np.linalg.lstsq(X, r, rcond=None)
        resid = r - X @ coef
        s2 = (resid ** 2).sum() / (len(r) - 2)
        se = float(np.sqrt(s2 * np.linalg.inv(X.T @ X)[0, 0]))
        out |= {"alpha_annual": float(coef[0] * TRADING_DAYS),
                "alpha_t": float(coef[0] / se) if se > 0 else float("nan")}
    return out


def survivorship_report(panel, mask: np.ndarray) -> dict:
    """How much of the book sits in names that stop trading — the caveat, sized.

    A momentum screen in a survivorship-biased panel is the canonical way to
    manufacture a fake result, so this reports the exposure rather than
    mentioning the risk in passing.
    """
    close = panel.close
    n = close.shape[0]
    last_seen = np.full(close.shape[1], -1)
    fin = np.isfinite(close)
    for j in range(close.shape[1]):
        w = np.flatnonzero(fin[:, j])
        if w.size:
            last_seen[j] = int(w[-1])
    ends_early = last_seen < (n - 20)
    held = mask.sum(axis=0)
    held_early = held[ends_early].sum()
    return {
        "names_ever_qualified": int((held > 0).sum()),
        "of_which_stop_trading": int(((held > 0) & ends_early).sum()),
        "share_of_holding_days_in_names_that_stop": float(held_early / max(1, held.sum())),
        "note": ("The FMP plan page-caps the delisted feed at ~57 tickers against "
                 "5,762 live listings, so most companies that failed are simply "
                 "absent from the panel rather than present and losing. This "
                 "measures what little of the effect is captured; the missing "
                 "part biases every return below upward and cannot be sized "
                 "from this data."),
    }
