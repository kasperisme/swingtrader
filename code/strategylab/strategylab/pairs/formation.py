"""Pair formation — cointegration, hedge ratio, and the OU speed, fit ONLY on
formation data.

Three things make this defensible rather than another pairs backtest:

* **Nothing crosses the formation/trading boundary.** beta, mu, sigma_s and the
  half-life are estimated on `[f0, f1)` and used unchanged on `[t0, t1)`. The
  trading window never touches an estimator. `tests/test_pairs.py` pins it by
  scrambling the trading window and asserting the formed pairs are identical.

* **The critical value is simulated, not remembered.** Engle-Granger residual
  ADF statistics do not follow the Dickey-Fuller tables, and the MacKinnon
  surface is easy to misquote. `null_distribution()` runs the *identical*
  estimator over independent random walks of the same length and reads the
  quantile off the empirical null. That also yields the expected number of
  spurious pairs among those selected, which is reported rather than hidden.

* **Selection noise is confessed and then neutralised.** Screening ~10k
  candidate pairs at alpha=0.05 admits ~500 false positives by construction.
  This matters for the *level* of convergence and not for the H1 contrast,
  which compares buckets drawn from the same selected set — a false pair is
  equally likely to land in either bucket.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import CACHE_ROOT

log = logging.getLogger(__name__)


@dataclass
class FormationSpec:
    """The pair-formation protocol. Frozen for a study; changing it invalidates
    cross-run comparability the same way `LabConfig.protocol_version` does."""

    formation_days: int = 504            # ~24 months
    trading_days: int = 126              # ~6 months, non-overlapping
    # Eligibility, evaluated on the LAST bar of the formation window and
    # required for the whole of it (a name that becomes liquid mid-formation
    # has a hedge ratio fitted on illiquid prices).
    min_price: float = 5.0
    min_adv_usd: float = 10e6
    min_formation_bars: int = 480        # of `formation_days` possible
    # Cointegration + OU screen.
    coint_alpha: float = 0.05
    adf_lags: int = 1
    min_half_life: float = 5.0           # faster than this is untradeable
    max_half_life: float = 60.0          # slower than this is a fake pair
    min_beta: float = 0.2                # a sane hedge ratio; a within-industry
    max_beta: float = 5.0                # pair with beta<0 is a spurious fit
    # Diversification caps — one sector's regime must not own the panel.
    max_pairs_per_industry: int = 6
    max_pairs_per_symbol: int = 3
    max_pairs: int = 400
    # The news discriminator is only honest where BOTH legs have earnings
    # coverage; otherwise the no-news bucket silently collects the names that
    # happened to be missing from the cache. Same failure the flow universe
    # module documents for its blackout.
    require_earnings_coverage: bool = True
    min_etf_overlap: float = 0.0         # Anton-Polk prior; 0 = off (exploratory)
    null_replications: int = 4000
    seed: int = 11


@dataclass
class Pair:
    a: str
    b: str
    ia: int                              # column index of leg A in the panel
    ib: int
    industry: str
    beta: float                          # log P_A = alpha + beta * log P_B
    alpha: float
    mu: float                            # formation mean of the spread
    sigma: float                         # formation sd of the spread
    adf_t: float
    p_value: float                       # from the simulated null
    half_life: float
    etf_overlap: float
    window: int                          # index of the formation/trading window
    formation_start: str = ""
    formation_end: str = ""
    trade_start: str = ""
    trade_end: str = ""

    def key(self) -> str:
        return f"{self.a}|{self.b}|{self.window}"

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        return d


# ----------------------------------------------------------------------
# The estimator. Vectorised across pairs because the study runs ~10k candidate
# pairs per window and ~25 windows.
# ----------------------------------------------------------------------
def ols_pair(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Regress one series on each column of X with a constant.

    y: (T,)   X: (T, K)  ->  (alpha (K,), beta (K,), residuals (T, K))
    """
    ym = y.mean()
    xm = X.mean(axis=0)
    yc = y - ym
    xc = X - xm
    var = (xc * xc).sum(axis=0)
    var = np.where(var > 0, var, np.nan)
    beta = (xc * yc[:, None]).sum(axis=0) / var
    alpha = ym - beta * xm
    resid = y[:, None] - alpha[None, :] - beta[None, :] * X
    return alpha, beta, resid


def adf_t(E: np.ndarray, lags: int = 1) -> np.ndarray:
    """t-statistic on gamma in  dE_t = gamma*E_{t-1} + sum_i delta_i dE_{t-i} + u.

    No constant and no trend: the residual of a cointegrating regression that
    already carries an intercept has mean zero by construction, and adding a
    second one shifts the null distribution.

    E: (T, K) -> (K,) t-statistics. Vectorised: K independent 2x2 (or (1+lags))
    normal-equation solves done as one batched `np.linalg.solve`.
    """
    E = np.asarray(E, dtype=np.float64)
    T, K = E.shape
    dE = np.diff(E, axis=0)                       # (T-1, K); dE[k] = E[k+1]-E[k]
    n = T - 1 - lags
    if n <= lags + 4:
        return np.full(K, np.nan)

    y = dE[lags:]                                 # y[k'] uses dE[k], k=lags..T-2
    cols = [E[lags:T - 1]]                        # E_{t-1}
    for i in range(1, lags + 1):
        cols.append(dE[lags - i: T - 1 - i])      # dE_{t-i}
    Z = np.stack(cols, axis=0)                    # (p, n, K)
    p = Z.shape[0]

    # Batched normal equations: (K, p, p) and (K, p).
    XtX = np.einsum("ank,bnk->kab", Z, Z)
    Xty = np.einsum("ank,nk->ka", Z, y)
    out = np.full(K, np.nan)
    # A singular system means a degenerate residual series (a constant column,
    # or a leg with no variation); those pairs are dropped, not patched.
    ok = np.isfinite(XtX).all(axis=(1, 2)) & np.isfinite(Xty).all(axis=1)
    dets = np.full(K, 0.0)
    if ok.any():
        dets[ok] = np.linalg.det(XtX[ok])
    ok &= np.abs(dets) > 1e-18
    if not ok.any():
        return out

    idx = np.flatnonzero(ok)
    inv = np.linalg.inv(XtX[idx])                 # (k, p, p)
    coef = np.einsum("kab,kb->ka", inv, Xty[idx])
    fitted = np.einsum("ank,ka->nk", Z[:, :, idx], coef)
    ssr = ((y[:, idx] - fitted) ** 2).sum(axis=0)
    s2 = ssr / max(1, (n - p))
    se = np.sqrt(np.maximum(s2 * inv[:, 0, 0], 1e-300))
    out[idx] = np.where(se > 0, coef[:, 0] / se, np.nan)
    return out


def half_life(E: np.ndarray) -> np.ndarray:
    """OU half-life in trading days from an AR(1) with a constant on the residual.

    Reported as +inf when the fitted phi is >=1 (no reversion) and as NaN when
    phi <=0 (alternating, not an OU process) — both are rejected by the band
    filter rather than silently coerced into a number.
    """
    E = np.asarray(E, dtype=np.float64)
    lag, cur = E[:-1], E[1:]
    lm, cm = lag.mean(axis=0), cur.mean(axis=0)
    lc, cc = lag - lm, cur - cm
    var = (lc * lc).sum(axis=0)
    var = np.where(var > 0, var, np.nan)
    phi = (lc * cc).sum(axis=0) / var
    with np.errstate(divide="ignore", invalid="ignore"):
        hl = np.where((phi > 0) & (phi < 1), np.log(2.0) / -np.log(np.clip(phi, 1e-12, 1 - 1e-12)),
                      np.where(phi >= 1, np.inf, np.nan))
    return hl


# ----------------------------------------------------------------------
# The simulated null.
# ----------------------------------------------------------------------
def null_distribution(T: int, lags: int = 1, replications: int = 4000,
                      seed: int = 11, cache_dir: Path | None = None) -> np.ndarray:
    """Empirical null of the Engle-Granger residual ADF statistic.

    Two independent Gaussian random walks of length T are regressed on one
    another and the residual ADF statistic recorded, using the *same* code path
    the study uses. Cached on disk keyed by (T, lags, replications, seed) —
    the null is a property of the protocol, not of the data.
    """
    d = Path(cache_dir or (CACHE_ROOT / "pairs"))
    d.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{T}|{lags}|{replications}|{seed}".encode()).hexdigest()[:16]
    path = d / f"eg_null_{key}.npy"
    if path.exists():
        try:
            return np.load(path)
        except Exception:
            pass

    rng = np.random.default_rng(seed)
    stats = np.empty(replications, dtype=np.float64)
    block = 500
    done = 0
    while done < replications:
        k = min(block, replications - done)
        w = rng.standard_normal((T, 2 * k)).cumsum(axis=0)
        y_all, x_all = w[:, :k], w[:, k:]
        resid = np.empty((T, k))
        for j in range(k):
            _, _, r = ols_pair(y_all[:, j], x_all[:, j:j + 1])
            resid[:, j] = r[:, 0]
        stats[done:done + k] = adf_t(resid, lags=lags)
        done += k
    stats = np.sort(stats[np.isfinite(stats)])
    np.save(path, stats)
    return stats


def null_pvalue(stat: np.ndarray, null: np.ndarray) -> np.ndarray:
    """Left-tail p-value against the simulated null (more negative = stronger)."""
    stat = np.asarray(stat, dtype=np.float64)
    out = np.full(stat.shape, np.nan)
    ok = np.isfinite(stat)
    if null.size and ok.any():
        out[ok] = np.searchsorted(null, stat[ok], side="right") / float(null.size)
    return out


# ----------------------------------------------------------------------
# Eligibility and windows.
# ----------------------------------------------------------------------
def trading_sessions(panel, min_share: float = 0.20) -> np.ndarray:
    """Rows of the panel that are genuine US equity sessions.

    The panel's date index is the UNION of every symbol's dates, so ONE bad
    vendor bar on a non-trading day creates a row on which every other name is
    NaN. That is not a cosmetic problem here: pair formation needs a jointly
    complete price matrix, so a single such row silently empties the candidate
    set for every formation window that contains it. It cost this study the
    last vault window before it was found, which is why the filter is explicit
    and logged rather than folded into a `dropna`.

    A row survives if it is a weekday AND at least `min_share` of the names
    that have started trading by then are priced.
    """
    days = pd.DatetimeIndex(panel.dates)
    weekday = days.dayofweek < 5
    finite = np.isfinite(panel.close)
    started = (finite.cumsum(axis=0) > 0).sum(axis=1)
    share = finite.sum(axis=1) / np.maximum(1, started)
    return np.asarray(weekday) & (share >= min_share)


def drop_non_sessions(panel, min_share: float = 0.20):
    """Return (panel_without_bogus_rows, dropped_dates)."""
    from ..data.prices import Panel
    keep = trading_sessions(panel, min_share)
    if keep.all():
        return panel, []
    dropped = [str(d) for d in panel.dates[~keep]]
    return Panel(dates=panel.dates[keep], symbols=list(panel.symbols),
                 open=panel.open[keep], high=panel.high[keep], low=panel.low[keep],
                 close=panel.close[keep], volume=panel.volume[keep]), dropped


def eligible_mask(panel, spec: FormationSpec) -> np.ndarray:
    """(n_days, n_symbols) bool — tradeable that day on price and liquidity."""
    close = panel.close
    adv = pd.DataFrame(close * panel.volume).rolling(20, min_periods=15).mean().to_numpy()
    ok = np.isfinite(close) & (close > spec.min_price)
    ok &= np.greater(adv, spec.min_adv_usd, out=np.zeros_like(ok), where=np.isfinite(adv))
    return ok


def formation_windows(panel, start: str, end: str, spec: FormationSpec) -> list[dict]:
    """Non-overlapping trading windows, each preceded by its own formation window.

    `start`/`end` bound the TRADING periods, so the panel must reach back
    `formation_days` before `start` or the first window is dropped.
    """
    dates = panel.dates
    t0 = panel.date_index(start)
    stop = min(len(dates), panel.date_index(end) + 1)
    out = []
    w = 0
    while t0 + 5 < stop:
        f0, f1 = t0 - spec.formation_days, t0
        t1 = min(stop, t0 + spec.trading_days)
        if f0 >= 0:
            out.append({"window": w, "f0": f0, "f1": f1, "t0": t0, "t1": t1,
                        "formation_start": str(dates[f0]), "formation_end": str(dates[f1 - 1]),
                        "trade_start": str(dates[t0]), "trade_end": str(dates[t1 - 1])})
            w += 1
        else:
            log.warning("dropping trading window at %s — panel starts too late for a "
                        "%d-day formation period", dates[t0], spec.formation_days)
        t0 += spec.trading_days
    return out


# ----------------------------------------------------------------------
# ETF-ownership overlap (the Anton-Polk linkage prior).
# ----------------------------------------------------------------------
def etf_overlap_matrix(symbols: list[str], weights_loader) -> dict[str, dict[str, float]]:
    """Proportional overlap of each name's ETF holder base, in [0, 1].

    For each name, the vector v_s[f] = (market value of s held by ETF f) /
    (total held by all ETFs). Overlap(A,B) = sum_f min(v_A[f], v_B[f]) — 1 when
    the two names are held by exactly the same funds in the same proportions,
    0 when the holder bases are disjoint.

    LIMITATION, and it is not small: `etf-stock-exposure` is a CURRENT snapshot,
    so this carries look-ahead. It is therefore reported as a covariate and
    never used as a formation filter by default (`min_etf_overlap = 0`).
    """
    vecs: dict[str, dict[str, float]] = {}
    for s in symbols:
        rows = weights_loader(s) or []
        v: dict[str, float] = {}
        for r in rows:
            etf = r.get("etf")
            try:
                mv = float(r.get("market_value") or 0.0)
            except (TypeError, ValueError):
                continue
            if etf and mv > 0:
                v[etf] = v.get(etf, 0.0) + mv
        tot = sum(v.values())
        if tot > 0:
            vecs[s] = {k: x / tot for k, x in v.items()}
    return vecs


def _overlap(va: dict, vb: dict) -> float:
    if not va or not vb:
        return float("nan")
    keys = va.keys() & vb.keys()
    return float(sum(min(va[k], vb[k]) for k in keys))


# ----------------------------------------------------------------------
# The formation pass.
# ----------------------------------------------------------------------
def form_pairs(panel, window: dict, industries: dict[str, str], spec: FormationSpec,
               eligible: np.ndarray | None = None,
               earnings_have: set[str] | None = None,
               etf_vectors: dict | None = None,
               null: np.ndarray | None = None) -> tuple[list[Pair], dict]:
    """Form the tradeable pair book for one window. Returns (pairs, funnel)."""
    f0, f1 = window["f0"], window["f1"]
    close = panel.close[f0:f1]
    if eligible is None:
        eligible = eligible_mask(panel, spec)
    elig = eligible[f0:f1]

    funnel: dict = {}
    bars = np.isfinite(close).sum(axis=0)
    keep = (bars >= spec.min_formation_bars) & (elig.sum(axis=0) >= spec.min_formation_bars)
    funnel["names with a full, liquid formation window"] = int(keep.sum())

    if spec.require_earnings_coverage and earnings_have is not None:
        keep &= np.array([s in earnings_have for s in panel.symbols])
        funnel["after earnings-date coverage"] = int(keep.sum())

    ind = np.array([industries.get(s) or "NONE" for s in panel.symbols], dtype=object)
    keep &= ind != "NONE"
    funnel["after industry label present"] = int(keep.sum())

    logp = np.log(np.where(close > 0, close, np.nan))
    T = f1 - f0
    if null is None:
        null = null_distribution(T, spec.adf_lags, spec.null_replications, spec.seed)
    crit = float(np.quantile(null, spec.coint_alpha)) if null.size else -3.34
    funnel["simulated EG critical value"] = round(crit, 3)

    groups: dict[str, list[int]] = {}
    for j in np.flatnonzero(keep):
        groups.setdefault(str(ind[j]), []).append(int(j))

    cand = 0
    incomplete = 0
    rows: list[dict] = []
    for industry, members in groups.items():
        if len(members) < 2:
            continue
        cols = np.array(members)
        X = logp[:, cols]
        # A name with any NaN inside the formation window would poison every
        # pair it appears in; the bar count above admits a few, so drop them.
        good = np.isfinite(X).all(axis=0)
        incomplete += int((~good).sum())
        cols, X = cols[good], X[:, good]
        m = len(cols)
        if m < 2:
            continue
        cand += m * (m - 1) // 2

        # Engle-Granger is asymmetric in which leg is the regressand, so both
        # directions are fitted and the stronger one kept.
        best: dict[tuple[int, int], dict] = {}
        for i in range(m):
            others = np.ones(m, bool)
            others[i] = False
            if not others.any():
                continue
            a_, b_, resid = ols_pair(X[:, i], X[:, others])
            t = adf_t(resid, lags=spec.adf_lags)
            hl = half_life(resid)
            sig = resid.std(axis=0, ddof=1)
            mu = resid.mean(axis=0)
            oth = np.flatnonzero(others)
            for q, jj in enumerate(oth):
                ci, cj = int(cols[i]), int(cols[jj])
                k = (min(ci, cj), max(ci, cj))
                cur = {"ia": ci, "ib": cj, "industry": industry,
                       "alpha": float(a_[q]), "beta": float(b_[q]), "mu": float(mu[q]),
                       "sigma": float(sig[q]), "adf_t": float(t[q]),
                       "half_life": float(hl[q])}
                prev = best.get(k)
                if prev is None or (np.isfinite(cur["adf_t"])
                                    and not np.isfinite(prev["adf_t"])) \
                   or (np.isfinite(cur["adf_t"]) and cur["adf_t"] < prev["adf_t"]):
                    best[k] = cur
        rows.extend(best.values())

    funnel["dropped for an incomplete formation window"] = incomplete
    funnel["candidate pairs (within industry)"] = cand
    if not rows:
        return [], funnel

    df = pd.DataFrame(rows)
    df["p_value"] = null_pvalue(df["adf_t"].to_numpy(), null)
    n0 = len(df)
    df = df[np.isfinite(df["adf_t"])]
    df = df[df["adf_t"] <= crit]
    funnel[f"cointegrated at alpha={spec.coint_alpha:g}"] = int(len(df))
    funnel["expected spurious at that alpha"] = int(round(n0 * spec.coint_alpha))

    df = df[(df["half_life"] >= spec.min_half_life) & (df["half_life"] <= spec.max_half_life)]
    funnel[f"half-life in [{spec.min_half_life:g}, {spec.max_half_life:g}] days"] = int(len(df))
    df = df[(df["beta"] >= spec.min_beta) & (df["beta"] <= spec.max_beta)]
    funnel[f"hedge ratio in [{spec.min_beta:g}, {spec.max_beta:g}]"] = int(len(df))
    df = df[df["sigma"] > 1e-6]

    # ETF-ownership overlap: a covariate, and optionally a floor.
    if etf_vectors is not None and len(df):
        syms = panel.symbols
        ov = [_overlap(etf_vectors.get(syms[int(r.ia)], {}),
                       etf_vectors.get(syms[int(r.ib)], {})) for r in df.itertuples()]
        df["etf_overlap"] = ov
        if spec.min_etf_overlap > 0:
            df = df[df["etf_overlap"].fillna(0.0) >= spec.min_etf_overlap]
            funnel[f"ETF overlap >= {spec.min_etf_overlap:.2f}"] = int(len(df))
    else:
        df["etf_overlap"] = np.nan

    # Diversification caps, applied to the strongest pairs first.
    df = df.sort_values("adf_t").reset_index(drop=True)
    per_ind: dict[str, int] = {}
    per_sym: dict[int, int] = {}
    chosen = []
    for r in df.itertuples():
        if len(chosen) >= spec.max_pairs:
            break
        if per_ind.get(r.industry, 0) >= spec.max_pairs_per_industry:
            continue
        if per_sym.get(r.ia, 0) >= spec.max_pairs_per_symbol:
            continue
        if per_sym.get(r.ib, 0) >= spec.max_pairs_per_symbol:
            continue
        per_ind[r.industry] = per_ind.get(r.industry, 0) + 1
        per_sym[r.ia] = per_sym.get(r.ia, 0) + 1
        per_sym[r.ib] = per_sym.get(r.ib, 0) + 1
        chosen.append(r)
    funnel["after diversification caps"] = len(chosen)

    syms = panel.symbols
    pairs = [Pair(a=syms[int(r.ia)], b=syms[int(r.ib)], ia=int(r.ia), ib=int(r.ib),
                  industry=str(r.industry), beta=float(r.beta), alpha=float(r.alpha),
                  mu=float(r.mu), sigma=float(r.sigma), adf_t=float(r.adf_t),
                  p_value=float(r.p_value), half_life=float(r.half_life),
                  etf_overlap=float(r.etf_overlap) if np.isfinite(r.etf_overlap) else float("nan"),
                  window=int(window["window"]),
                  formation_start=window["formation_start"],
                  formation_end=window["formation_end"],
                  trade_start=window["trade_start"], trade_end=window["trade_end"])
             for r in chosen]
    return pairs, funnel
