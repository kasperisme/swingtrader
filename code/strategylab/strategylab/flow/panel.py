"""Stage 1 — panel evidence, before any portfolio exists.

The research spec is emphatic about the ordering, and it is the whole game: if
you jump straight to a P&L curve you will tune parameters until something works
and learn nothing. So this module answers exactly one question:

    Does rho x F predict forward returns beyond standard price momentum?

If that interaction is not significant with controls in, the programme stops.
No portfolio construction rescues a signal that does not exist in the panel.

Method is Fama-MacBeth: run a cross-sectional regression each month, then treat
the resulting coefficient series as the sample. It is used here rather than
pooled OLS because pooled standard errors are badly overstated when residuals
are cross-sectionally correlated — which, in a month where the whole market
moves together, they emphatically are. Newey-West on the coefficient series then
handles the remaining autocorrelation from overlapping information.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from .signals import FlowSignals


@dataclass
class FMResult:
    n_periods: int
    mean_obs: float
    coefficients: dict = field(default_factory=dict)   # name -> stats dict
    r2_mean: float = 0.0
    formula: str = ""

    def table(self) -> str:
        rows = [f"{'variable':<22}{'coef':>10}{'t (NW)':>10}{'p':>10}{'sig':>6}",
                "-" * 58]
        for name, c in self.coefficients.items():
            star = ("***" if c["p"] < 0.01 else "**" if c["p"] < 0.05
                    else "*" if c["p"] < 0.10 else "")
            rows.append(f"{name:<22}{c['coef']:>10.4f}{c['t']:>10.2f}"
                        f"{c['p']:>10.4f}{star:>6}")
        rows.append("-" * 58)
        rows.append(f"periods={self.n_periods}  avg cross-section={self.mean_obs:.0f}  "
                    f"mean R2={self.r2_mean:.3f}")
        return "\n".join(rows)

    def is_significant(self, name: str, alpha: float = 0.05) -> bool:
        c = self.coefficients.get(name)
        return bool(c and c["p"] < alpha)


# ----------------------------------------------------------------------
def _winsorize(s: pd.Series, lo: float = 0.01, hi: float = 0.99) -> pd.Series:
    if s.notna().sum() < 20:
        return s
    a, b = s.quantile(lo), s.quantile(hi)
    return s.clip(a, b)


def _zscore(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=1)
    if not np.isfinite(sd) or sd < 1e-12:
        return s * 0.0
    return (s - s.mean()) / sd


def month_end_indices(dates: np.ndarray) -> np.ndarray:
    """Last trading day of each calendar month."""
    idx = pd.DatetimeIndex(dates)
    df = pd.DataFrame({"i": np.arange(len(idx))}, index=idx)
    return df.groupby([idx.year, idx.month])["i"].max().to_numpy()


def build_dataset(sig: FlowSignals, horizon_days: int = 21,
                  min_names: int = 50,
                  cap_range: tuple[float, float] | None = None,
                  extra: dict[str, np.ndarray] | None = None) -> pd.DataFrame:
    """Long-format panel: one row per (month-end, symbol).

    The forward return is measured from the cross-section date to `horizon_days`
    later, so every predictor is strictly in the past relative to its own target.
    """
    close = None
    dates = pd.DatetimeIndex(sig.dates)
    ends = month_end_indices(sig.dates)

    # Forward return needs prices; reconstruct from the return series to avoid
    # threading the panel through, using cumulative product.
    logret = np.log1p(np.nan_to_num(sig.ret, nan=0.0))
    valid = np.isfinite(sig.ret)
    cum = np.cumsum(np.where(valid, logret, 0.0), axis=0)

    frames = []
    features = {
        "rho": sig.rho, "F": sig.forcing, "t_half": sig.t_half,
        "mom_12_1": sig.mom_12_1, "strev": sig.strev, "turnover": sig.turnover,
        "sigma": sig.sigma, "illiq": sig.illiq, "adv": sig.adv,
        "market_cap": sig.market_cap, "gap": sig.slippage_gap,
        "realised_20d": np.exp(np.vstack([np.full((20, len(sig.symbols)), np.nan),
                                          cum[20:] - cum[:-20]])) - 1.0,
        "rho_ema": sig.rho_ema, "q_break_ratio": sig.q_break_ratio,
    }
    if extra:
        features.update(extra)

    for t in ends:
        t_fwd = t + horizon_days
        if t_fwd >= len(sig.dates):
            continue
        fwd = np.exp(cum[t_fwd] - cum[t]) - 1.0
        # A name must actually trade at both ends, or the "return" is fabricated.
        tradable = valid[t] & valid[t_fwd] & np.isfinite(fwd)
        row = {k: v[t] for k, v in features.items()}
        row["fwd_ret"] = fwd
        d = pd.DataFrame(row, index=pd.Index(sig.symbols, name="symbol"))
        d = d[tradable]
        d["date"] = dates[t]
        frames.append(d.reset_index())

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df = df.replace([np.inf, -np.inf], np.nan)

    if cap_range is not None:
        lo, hi = cap_range
        df = df[(df["market_cap"] >= lo) & (df["market_cap"] < hi)]

    # Derived, monotone transforms of skewed regressors.
    df["log_cap"] = np.log(df["market_cap"].where(df["market_cap"] > 0))
    df["log_illiq"] = np.log(df["illiq"].where(df["illiq"] > 0))
    df["log_turnover"] = np.log(df["turnover"].where(df["turnover"] > 0))

    counts = df.groupby("date")["symbol"].transform("size")
    return df[counts >= min_names].reset_index(drop=True)


def prepare_cross_sections(df: pd.DataFrame, regressors: list[str],
                           interactions: list[tuple[str, str]] | None = None
                           ) -> pd.DataFrame:
    """Winsorise and standardise WITHIN each cross-section.

    Per-date standardisation is what makes the coefficients comparable across a
    decade in which dollar volumes grew by an order of magnitude — an unscaled
    flow variable would otherwise load on the calendar rather than the stock.
    Interactions are formed from the standardised components, so the interaction
    coefficient means "the effect of F, per standard deviation of rho".
    """
    out = []
    for date, g in df.groupby("date", sort=True):
        g = g.copy()
        for col in regressors:
            if col in g.columns:
                g[col + "_z"] = _zscore(_winsorize(g[col]))
        for a, b in (interactions or []):
            za, zb = g.get(a + "_z"), g.get(b + "_z")
            if za is not None and zb is not None:
                g[f"{a}_x_{b}_z"] = _zscore(za * zb)
        out.append(g)
    return pd.concat(out, ignore_index=True)


def _newey_west_t(x: np.ndarray, lags: int) -> tuple[float, float, float]:
    """Mean, Newey-West standard error, and t-stat of a coefficient series."""
    x = x[np.isfinite(x)]
    n = x.size
    if n < 8:
        return float("nan"), float("nan"), float("nan")
    mu = x.mean()
    e = x - mu
    gamma0 = (e @ e) / n
    var = gamma0
    for L in range(1, min(lags, n - 1) + 1):
        w = 1.0 - L / (lags + 1.0)          # Bartlett kernel
        gl = (e[L:] @ e[:-L]) / n
        var += 2.0 * w * gl
    var = max(var, 1e-18)
    se = np.sqrt(var / n)
    return float(mu), float(se), float(mu / se)


def fama_macbeth(df: pd.DataFrame, y: str, xs: list[str],
                 nw_lags: int = 6, min_obs: int = 30) -> FMResult:
    """Cross-sectional regressions each period, then Newey-West on the series."""
    cols = [c for c in xs if c in df.columns]
    coefs: dict[str, list[float]] = {c: [] for c in ["const"] + cols}
    r2s: list[float] = []
    n_obs: list[int] = []

    for _date, g in df.groupby("date", sort=True):
        sub = g[[y] + cols].replace([np.inf, -np.inf], np.nan).dropna()
        if len(sub) < min_obs:
            continue
        X = np.column_stack([np.ones(len(sub))] + [sub[c].to_numpy() for c in cols])
        yy = sub[y].to_numpy()
        try:
            beta, *_ = np.linalg.lstsq(X, yy, rcond=None)
        except np.linalg.LinAlgError:
            continue
        resid = yy - X @ beta
        ss_tot = float(((yy - yy.mean()) ** 2).sum())
        r2s.append(1.0 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0)
        n_obs.append(len(sub))
        for name, b in zip(["const"] + cols, beta):
            coefs[name].append(float(b))

    result = FMResult(n_periods=len(r2s), mean_obs=float(np.mean(n_obs)) if n_obs else 0.0,
                      r2_mean=float(np.mean(r2s)) if r2s else 0.0,
                      formula=f"{y} ~ " + " + ".join(cols))
    for name, series in coefs.items():
        arr = np.array(series, dtype=float)
        mu, se, t = _newey_west_t(arr, nw_lags)
        p = 2.0 * (1.0 - stats.t.cdf(abs(t), df=max(len(arr) - 1, 1))) if np.isfinite(t) else np.nan
        result.coefficients[name] = {"coef": mu, "se": se, "t": t, "p": p,
                                     "n": int(np.isfinite(arr).sum())}
    return result


def quantile_sort(df: pd.DataFrame, sort_on: str, y: str = "fwd_ret",
                  q: int = 5, within: str | None = None) -> pd.DataFrame:
    """Average forward return by quantile of a variable, per cross-section."""
    rows = []
    for date, g in df.groupby("date", sort=True):
        g = g[[sort_on, y] + ([within] if within else [])].dropna()
        if len(g) < q * 10:
            continue
        try:
            g = g.assign(_q=pd.qcut(g[sort_on], q, labels=False, duplicates="drop"))
        except ValueError:
            continue
        for bucket, sub in g.groupby("_q"):
            rows.append({"date": date, "bucket": int(bucket),
                         "ret": float(sub[y].mean()), "n": len(sub)})
    if not rows:
        return pd.DataFrame()
    per = pd.DataFrame(rows)
    out = (per.groupby("bucket")
              .agg(mean_ret=("ret", "mean"), n_periods=("ret", "size"),
                   avg_n=("n", "mean"))
              .reset_index())
    # t-stat of each bucket's time series of mean returns
    ts = []
    for b in out["bucket"]:
        series = per[per["bucket"] == b]["ret"].to_numpy()
        _mu, _se, t = _newey_west_t(series, 6)
        ts.append(t)
    out["t"] = ts
    return out


def long_short_spread(df: pd.DataFrame, sort_on: str, y: str = "fwd_ret",
                      q: int = 5) -> dict:
    """Top-minus-bottom quantile spread, with a Newey-West t-stat."""
    per = []
    for date, g in df.groupby("date", sort=True):
        g = g[[sort_on, y]].dropna()
        if len(g) < q * 10:
            continue
        try:
            b = pd.qcut(g[sort_on], q, labels=False, duplicates="drop")
        except ValueError:
            continue
        hi = g[y][b == b.max()].mean()
        lo = g[y][b == b.min()].mean()
        per.append(hi - lo)
    arr = np.array(per, dtype=float)
    mu, se, t = _newey_west_t(arr, 6)
    p = 2.0 * (1.0 - stats.t.cdf(abs(t), df=max(arr.size - 1, 1))) if np.isfinite(t) else np.nan
    ann = mu * 12.0 if np.isfinite(mu) else np.nan
    return {"sort_on": sort_on, "n_periods": int(arr.size), "mean_monthly": mu,
            "annualised": ann, "t": t, "p": p,
            "sharpe": float(mu / arr.std(ddof=1) * np.sqrt(12)) if arr.size > 2
            and arr.std(ddof=1) > 0 else float("nan")}
